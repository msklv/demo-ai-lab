# ADR-0011: GPUStack под Argo CD — чарт инflируется kustomize'ом, патчи и секреты — вне helm

- Дата: 2026-11-14
- Статус: Accepted (решение владельца «делай сейчас», 2026-11-14); выполнено в тот же день,
  Application `gpustack` — Synced/Healthy
- Связанные: ADR-0001 (Higress как единственный ingress), ADR-0007 (модельный набор и GPU-бюджет),
  F6 (`gitops/` — единственная точка деплоя), `architecture/specs/gpustack-spec.md` (механизм — §4.1–4.3),
  `architecture/specs/gpustack-argocd-migration.md` (перенос: замеры, грабли)

## Контекст

До 2026-11-14 GPUStack был **единственным** компонентом стенда, который ставился императивно:
`helm upgrade` с консоли плюс идемпотентные допатчи скриптом `ansible/gpustack-upgrade.sh`
(`envFrom` с OIDC-секретом, `securityContext.capabilities` для embedded PostgreSQL, пин CPU-воркера
на k8s-01). Остальные приложения ведутся Argo CD из git. Чем это плохо:

- любая команда `helm upgrade` мимо скрипта **молча** снимает патчи: SSO пропадает, embedded
  PostgreSQL не стартует, bge-модели уходят в «No suitable workers»;
- значения патчей (какие именно поля и почему) живут в bash-скрипте, а не в ревьюируемом манифесте;
- состояние кластера нельзя воспроизвести из git, drift не виден.

Три вещи, которых чарт `gpustack-chart` 2.2.3 не умеет и которые нужны стенду:

1. `server.extraEnvFrom` отсутствует — `envFrom` сервера захардкожен (`registration-token`,
   `<release>-jwt-key`, ConfigMap `server-config`), а секрет OIDC-клиента в values попасть не может;
2. `securityContext` сервера и `nodeSelector` CPU-воркера рендерятся жёстко (нет ключей values);
3. `registration-token` / `server-jwt-secret` рендерятся через `lookup` + `randAlphaNum`: в
   `helm template` (единственный способ рендера под Argo) кластера нет → **новое случайное значение
   на каждом рендере** (вечный `OutOfSync`, ротация JWT-ключа и токена регистрации воркеров).

Замер дельты «рендер чарта vs живой кластер» (31 объект, 2026-11-14): расходятся ровно три поля
(`envFrom`, `capabilities`, `nodeSelector`) и два секрета — остальное совпадает байт-в-байт.

## Решение

**Релиз `gpustack` ведёт Argo CD; чарт не форкается и не вендорится, а инflируется kustomize'ом
с патчами; секреты, которые нельзя рендерить, создаются скриптом вне Argo.**

| Что | Как |
|---|---|
| Источник | `gitops/infra-apps/gpustack/`: `kustomization.yaml` (`helmCharts` — OCI-чарт `gpustack-chart` 2.2.3, `releaseName: gpustack`) + `values-gpustack.yaml` + `30-ingress.yaml` |
| Патчи | JSON6902: `envFrom/-` с `gpustack-oidc`; `securityContext.capabilities` сервера; `nodeSelector` DS `gpustack-worker` |
| Секреты | `registration-token` и `gpustack-jwt-key` — `$patch: delete` из рендера; `gpustack-oidc` никогда не был в рендере. Все три создаёт `scripts/gpustack_secrets.sh` (`--init`), Argo их не трекает и не prune'ит |
| Кластер | `argocd-cm`: `kustomize.buildOptions: --enable-helm` (флаг opt-in; вне git — Argo CD поставлен helm'ом с консоли, долг F6) |
| Helm | `helm upgrade`/`uninstall` для релиза `gpustack` **запрещены**; записи `sh.helm.release.v1.gpustack.*` удаляются после обкатки |
| Вне объёма | 5 вспомогательных helm-релизов ns (`kueue`, NFD, device-manager, csi-s3, csi-nfs) остались helm — отдельная задача; их values пока не в git |

Почему не «Application с helm-источником»: Argo отдал бы в кластер сырой рендер, и первый же sync
снял бы все допатчи — ровно та проблема, которую перенос должен убрать. Почему не multi-source
(helm + kustomize): Argo применяет источники независимо и не умеет патчить вывод одного другим.
Почему не форк/вендоринг чарта: 13 шаблонов пришлось бы диффать и ре-вендорить на каждом апгрейде
(388 КБ с сабчартом), а выигрыш — только в офлайн-рендере.

## Последствия

**Плюсы**

- git — источник правды: апгрейд = bump `helmCharts[0].version` + `image.tag`, ревью в одном диффе;
- `sync`/`selfHeal` больше не снимают патчи — SSO, старт PostgreSQL и пин воркера перестали быть
  «ручным шагом после helm upgrade»;
- adopt прошёл без роллаута: рендер совпал с живым состоянием, sync за 6 с, `sts` `generation`
  16 → 16, поды не пересоздавались (замер 2026-11-14);
- откат — `argocd app rollback` при снятом `--sync-policy none`; появился видимый drift.

**Минусы и ограничения**

- чарт **не в git**: рендер тянет его из публичного OCI (кэш — `charts/` каталога приложения,
  в `.gitignore`); при недоступности Docker Hub рендер падает (устраняется вендорингом, если станет
  проблемой);
- `git revert` каталога — **не** откат: прежняя ревизия без `helmCharts` заставит Argo заprune'ить
  объекты чарта. Откат — только через историю Application / `--cascade=orphan` (runbook в
  `gitops/infra-apps/gpustack/README.md`);
- `releaseName: gpustack` зафиксировано жёстко: смена имени Application/релиза = второй StatefulSet и
  второй PVC вместо adopt'а;
- `post-install/post-upgrade` джоба чарта (ytt → оператор) стала PostSync-хуком: отрабатывает на
  каждом sync (идемпотентна, TTL 1 сутки) — видимый шум, не риск;
- `argocd-cm` (`--enable-helm`) — настройка вне git: при переустановке Argo CD её надо вернуть
  (команда — в шапке `kustomization.yaml`);
- ручные `kubectl patch` по этим объектам теперь будут сняты `selfHeal` — это и есть цель, но
  привычку «поправил в кластере» придётся убрать;
- `helm rollback` для релиза недоступен (до удаления helm-записей — недоступен только формально:
  пользоваться им нельзя).

## Альтернативы (рассмотрены и отклонены)

1. **Application с helm-источником** (и патчи — вручную после sync). Отклонено: воспроизводит
   сегодняшнюю проблему, только в Argo; `selfHeal` будет откатывать ручные патчи.
2. **Multi-source: helm-чарт + Kustomize-патч поверх.** Технически невозможно: каждый источник
   применяется независимо, пост-рендера в Argo CD нет (`PostRender` — возможность Flux).
3. **Вендоринг/форк чарта в репозиторий** с правкой шаблонов. Отклонено: обслуживание форка на каждом
   апгрейде, 388 КБ чужого кода и лицензионная атрибуция в публичном репо; патчи kustomize дают тот же
   результат без форка.
4. **Оставить helm + скрипт** (status quo). Отклонено: единственный императивный компонент стенда,
   патчи вне ревью, SSO/PostgreSQL зависят от того, вспомнил ли оператор про скрипт.
5. **Перенести сразу весь namespace** (5 вспомогательных релизов). Отложено: их values вообще не в git,
   а выигрыш для демо ниже риска перезапуска CSI/NFD; отдельная задача — сначала вынести values в git.
