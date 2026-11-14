# GPUStack под Argo CD — перенос

> **Версия:** v1.0 (2026-11-14) · **Статус:** **выполнено** — Application `gpustack` ведёт релиз,
> `ansible/gpustack-upgrade.sh` удалён
> **Было:** единственный компонент стенда, который ставился императивно — `helm upgrade` с консоли
> плюс допатчи `sts/gpustack-server` и `ds/gpustack-worker` скриптом.
> **Стало:** Application `gpustack` (ApplicationSet `infra-apps`) инflирует чарт kustomize'ом
> (`helmCharts`, OCI 2.2.3) и накладывает патчи; секреты, которые чарт не умеет принимать извне, —
> `scripts/gpustack_secrets.sh` вне Argo.
> **Решение:** ADR-0011 · **Спека сервиса:** `architecture/specs/gpustack-spec.md` (§4.1–4.3, §7) ·
> **Каталог:** `gitops/infra-apps/gpustack/` (+ `README.md` — как апгрейдить и откатывать)
> **Замеры:** 2026-11-14, живой кластер + рендер в `argocd-repo-server` (kustomize 5.8.1, helm 4.2.1)

## 1. Что перенесено

| Объект | Было | Стало |
|---|---|---|
| Релиз `gpustack` (чарт `gpustack-chart` 2.2.3, OCI) | `helm upgrade` с консоли через обёртку | инflация чарта kustomize'ом в Application `gpustack` |
| values | `ansible/values-gpustack.yaml` | `gitops/infra-apps/gpustack/values-gpustack.yaml` (`helmCharts.valuesFile`) |
| `envFrom` c `gpustack-oidc` (SSO) | `kubectl patch sts` после каждого `helm upgrade` | JSON-патч `/envFrom/-` в `kustomization.yaml` |
| `securityContext.capabilities` сервера | `kubectl patch sts` (иначе embedded PostgreSQL не стартует) | JSON-патч `/securityContext/capabilities` |
| CPU-воркер на k8s-01 | `kubectl patch ds` (780M, bge-модели) | JSON-патч `nodeSelector` |
| `registration-token`, `gpustack-jwt-key` | генерировал Helm (`lookup`+`randAlphaNum`) | **вне рендера** (`$patch: delete`), создаёт `scripts/gpustack_secrets.sh` |
| `gpustack-oidc` | Secret вручную, ключ клиента Keycloak `gps` | то же, но создание/ротация — скриптом |
| Ingress + Certificate (`api.demo-ai-lab.ru`) | уже были под Argo (`30-ingress.yaml`) | без изменений, тот же Application |
| Оператор, kueue, NFD, CSI-драйверы (5 релизов ns) | helm с консоли | **остались helm** — см. §8 |

## 2. Механизм и почему он такой

`gitops/infra-apps/gpustack/kustomization.yaml`:

```yaml
resources: [30-ingress.yaml]
helmCharts:
  - {name: gpustack-chart, repo: oci://registry-1.docker.io/gpustack, version: 2.2.3,
     releaseName: gpustack, namespace: gpustack, valuesFile: values-gpustack.yaml}
patches:   # 2a envFrom, 2b capabilities, 3 nodeSelector, +2 `$patch: delete` на секреты
```

- **Почему не `Application` с helm-источником.** Чарт 2.2.3 не умеет `server.extraEnvFrom` (envFrom
  захардкожен), жёстко рендерит `securityContext` сервера и `nodeSelector` CPU-воркера. Helm-источник
  отдал бы в кластер «сырой» рендер, и первый же sync снял бы патчи — ровно то, что сегодня делает
  `helm upgrade` без скрипта.
- **Почему не multi-source (helm + kustomize).** Argo применяет источники независимо: kustomize-источник
  не видит вывод helm-источника, патчить его нельзя. Multi-source годится только для «values во втором
  источнике», а не для пост-рендера.
- **Почему не форк и не вендоринг чарта.** `helmCharts` даёт «чарт + пост-рендер» без обслуживания
  форка (13 шаблонов, которые придётся диффать на каждом апгрейде) и без 388 КБ чужого кода в репо.
  Чарт тянется из публичного OCI при рендере и кэшируется в `charts/` каталога приложения
  (в git не попадает — `.gitignore`, при eviction кэша тянется заново).
- **Требование к кластеру (единственное, вне git):** `kustomize.buildOptions: --enable-helm` в
  `argocd-cm`. Флаг opt-in: он ничего не меняет для каталогов без `helmCharts`. Команда — в шапке
  `kustomization.yaml`; аргумент, почему это не в git: сам Argo CD поставлен helm'ом с консоли
  (долг F6), его `argocd-cm` живёт вне репозитория.

## 3. Файлы

| Файл | Что |
|---|---|
| `gitops/infra-apps/gpustack/kustomization.yaml` | чарт + 5 патчей, sync-wave-объекты ingress'а |
| `gitops/infra-apps/gpustack/values-gpustack.yaml` | values релиза (файл обязан быть внутри каталога kustomization — load restrictor) |
| `gitops/infra-apps/gpustack/README.md` | апгрейд, откат, что за патчи и почему |
| `scripts/gpustack_secrets.sh` | `--init`: `registration-token`, `gpustack-jwt-key`, `gpustack-oidc`; без флага — только проверка |
| `ansible/gpustack-upgrade.sh` | **удалён** (его роль целиком перешла в патчи kustomize) |

## 4. Грабли (проверены замером)

1. **`lookup` + `randAlphaNum` в шаблонах секретов.** `templates/registration-token.yaml` и
   `server-jwt-secret.yaml` читают существующий Secret через `lookup`, а при его отсутствии генерируют
   случайное значение. `helm template` (единственный способ рендера в Argo) кластер не видит → новое
   значение **на каждом рендере**: приложение вечно `OutOfSync`, а после рестарта пода сервер получает
   новый JWT-ключ (ломаются выданные ключи/сессии) и новый registration-токен (воркеры теряют
   регистрацию). Лечение: `$patch: delete` обоих Secret'ов в рендере + отдельный скрипт.
2. **`releaseName: gpustack` обязателен.** Чарт называет объекты `<release>-server`, `<release>-jwt-key`;
   любое другое имя (или отсутствие `releaseName` при Application с другим именем) = второй StatefulSet,
   второй PVC, `gpustack-jwt-key` под другим именем.
3. **`valuesFile` не может выходить за каталог kustomization** — kustomize режет по load restrictor
   («security; file … is not in or below …»). Поэтому values лежит рядом с `kustomization.yaml`,
   а не в `gitops/values/`.
4. **`git revert` — не откат.** Прежняя ревизия каталога без `helmCharts` заставит Argo заprune'ить все
   объекты чарта (STS, Services, Secret'ы). Откат — `argocd app rollback` при снятом `--sync-policy none`
   или `argocd app delete --cascade=orphan`. Описано в `gitops/infra-apps/gpustack/README.md`.
5. **Helm-запись релиза остаётся** (`helm list -n gpustack` → revision 11). `helm upgrade`/`helm uninstall`
   для `gpustack` запрещены: они начнут воевать с Argo за те же поля. Записи удаляются после обкатки
   (не сделано на 2026-11-14).
6. **Хуки чарта.** `post-install,post-upgrade` джоба (`ytt | kubectl apply` для оператора) в Argo
   становится PostSync-хуком: отрабатывает на каждом sync, идемпотентна, TTL 1 сутки — шум, не риск.
   `pre-delete` джоба (удаление оператора) мапится на `PreDelete`: при удалении Application оператор
   будет удалён — это и есть её смысл.
7. **Патчи — только точечные `add`/`replace`.** Замена всего блока `securityContext` (как делал старый
   скрипт, выставляя `allowPrivilegeEscalation: true`) отличается от живого состояния (`false` + caps)
   и даёт лишний роллаут. В патче — только `capabilities`, как в кластере.
8. **Оператор и его Service рендерит ytt-джоба из ConfigMap**, а не Argo: они вне git и вне истории
   Application (в `helm get manifest` их нет и не было). Отдельная задача — вынести их в git.

## 5. Замер: рендер == кластер

Перед пушем каталог прогнан **тем же рендерером, что в кластере** (kustomize 5.8.1 + helm 4.2.1 в
`argocd-repo-server`), вывод сравнён с живым состоянием:

- 31 объект (29 от чарта без двух Secret'ов + Certificate/Ingress);
- `kubectl diff -n gpustack -f <рендер>` — пусто, кроме аннотаций `argocd.argoproj.io/tracking-id`,
  которые Argo добавит сам при первом sync, и двух хук-джоб (Argo их как ресурсы не создаёт);
- значит первый sync — no-op: `sts/gpustack-server` не пересоздаётся, PVC не трогается, поды не
  перезапускаются. Именно поэтому перенос сделан без ожидания HighLoad++.

**Факт после sync (2026-11-14, 04:07:57 → 04:08:03 MSK):** операция `Succeeded` за 6 с,
`status.resources` = 29 (31 минус 2 хук-джобы), `sts/gpustack-server` — `generation` остался **16**,
под `gpustack-server-0` создан 2026-11-08 (не пересоздавался), рестартов 0; воркеры на k8s-04 и
k8s-01 — те же поды. Приёмка после sync: `/healthz` → 200, `/auth/config` → `is_oidc=true`
(SSO-клиент `gps` жив, `gpustack-oidc` в `envFrom` на месте), `/v1/models` без ключа → 401
(ключевой путь закрыт, как и должен). `scripts/k8s_health.py --brief`: 15 PASS, 0 FAIL (единственный
WARN — накопленные рестарты longhorn/kube-vip/cilium, они вне ns `gpustack` и нашим изменением не
затронуты).

## 6. Сделано по шагам

1. `argocd-cm` ← `kustomize.buildOptions: --enable-helm`, рестарт `argocd-repo-server`; все приложения
   (14) остались `Synced/Healthy`.
2. `kustomization.yaml` + переезд values; два Secret'а выведены из рендера; `ansible/gpustack-upgrade.sh`
   удалён; добавлен `scripts/gpustack_secrets.sh` (проверка → OK на трёх Secret'ах).
3. Pre-flight: рендер в repo-server + `kubectl diff` (§5).
4. Push → Argo sync (6 с, no-op) → приёмка из §5; доки и ADR-0011 в том же коммите/следом.

## 7. Traceability с планом v0.1

| Пункт плана | Чем закрыт |
|---|---|
| A1 «выбрать схему, `releaseName`/`namespace`» | kustomize `helmCharts`, `releaseName: gpustack`, `namespace: gpustack` (§2) |
| A2 «секреты, чтобы sync их не удалял» | `$patch: delete` + `scripts/gpustack_secrets.sh`; Argo их не трекает и не prune'ит |
| A3 «`extraEnvFrom` в чарте 2.2.3?» | нет такого ключа → JSON-патч `/envFrom/-` |
| A4 «`securityContext` тем же патч-слоем» | JSON-патч `capabilities` (без замены всего блока) |
| A5 «adopt без пересоздания sts» | рендер совпал с живым — sync no-op (§5) |
| A6 «судьба оператора, kueue, CSI» | остались отдельными helm-релизами (§8) |
| A7 «приёмка: SSO, /v1/models, два sync» | §6 + приёмка после sync |
| A8 «доки, судьба скрипта» | этот документ, `gpustack-spec` §4.1–4.3/§7, `gitops/README.md`, ADR-0011; скрипт удалён |

## 8. Что осталось (вне объёма переноса)

- **5 helm-релизов ns `gpustack`** (`kueue`, `node-feature-discovery`, `operator-device-manager`,
  `csi-driver-s3`, `csi-driver-nfs`) по-прежнему ставятся с консоли, и их values **не в git**. Это
  отдельный долг: либо те же kustomize-каталоги, либо хотя бы вынести values в git.
- **Helm-записи** `sh.helm.release.v1.gpustack.*` — удалить после обкатки, вместе с ними уходит
  возможность `helm rollback` (остаётся `argocd app rollback`).
- **Оператор (Deployment/Service)** — вынести из ytt-джобы в git (см. §4.8).
- **`argocd-cm`** — настройка `--enable-helm` вне git; при переустановке Argo её надо вернуть.

## 9. История ревизий

| Версия | Дата | Что |
|---|---|---|
| v1.0 | 2026-11-14 | Перенос выполнен: kustomize `helmCharts` + 5 патчей, секреты скриптом, `ansible/gpustack-upgrade.sh` удалён. Замер: 31 объект, `kubectl diff` пуст, adopt без роллаута |
| v0.1 | 2026-11-06 | План (A1–A8), предполагался multi-source helm+kustomize и риск пересоздания `sts` при adopt |
