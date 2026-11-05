# План: перенос GPUStack под Argo CD

> **Версия:** v0.1 (2026-11-06) · **Статус:** план, **не начато** — работы после HighLoad++ (1 декабря)
> **Зачем:** сейчас GPUStack — единственный компонент стенда, который ставится императивно
> (`helm upgrade` с консоли + допатчи StatefulSet скриптом). Остальные 11 приложений ведутся Argo CD.
> **Чего не делаем сейчас:** до показа не трогаем — перенос связан с adopt'ом релиза, возможным
> пересозданием `sts/gpustack-server` и риском потерять SSO/модели на сцене.
> **Связанные документы:** `architecture/specs/gpustack-spec.md` (G7, «Механизм развёртывания»),
> `ansible/gpustack-upgrade.sh`, `gitops/` (ApplicationSet `apps`), ADR-0004.

## 1. Что переносим

| Объект | Сейчас | Куда |
|---|---|---|
| Релиз `gpustack` (чарт `gpustack-chart` 2.2.3, OCI) | `helm upgrade` вручную через `ansible/gpustack-upgrade.sh` | Argo CD Application с helm-источником |
| values | `ansible/values-gpustack.yaml` | тот же файл (или `gitops/values/gpustack.yaml`) как `valueFiles` |
| Секрет OIDC-клиента (`gpustack-oidc`) | Secret создаётся вне git, подмешивается патчем `envFrom` после helm | Secret вне Argo (ручной apply / SOPS), ссылка в патче |
| `securityContext` сервера | патч `sts` вне helm (embedded postgres требует `SETUID/SETGID/CHOWN/DAC_OVERRIDE/FOWNER`) | тот же декларативный патч-слой |
| Оператор GPUStack, kueue, csi-driver-s3/nfs | отдельные helm-релизы в ns `gpustack` | решить: включать в Application или оставить отдельно |

## 2. Шаги

- [ ] **A1. Схема.** Выбрать: один Argo Application (helm + kustomize multi-source) или Application
      на релиз. Зафиксировать `releaseName: gpustack`, `namespace: gpustack` — **иначе adopt не
      случится и Argo попытается создать второй релиз**.
- [ ] **A2. Секреты.** Описать, чем создаются `gpustack-oidc`, `registration-token`,
      `gpustack-jwt-key`; проверить, что `sync` Argo их не удаляет (`Prune=false`/вне Application).
- [ ] **A3. `envFrom`.** Проверить, есть ли в чарте 2.2.3 `server.extraEnvFrom`; если нет —
      Argo multi-source: helm-чарт + Kustomize-патч поверх StatefulSet (заменяет шаг скрипта).
- [ ] **A4. `securityContext`.** Туда же вынести патч из A3 (caps для postgres). Без него сервер
      поднимается, но embedded Postgres не стартует: `su: cannot set groups: Operation not permitted`.
- [ ] **A5. Adopt.** Подключить Application к существующему релизу server-side apply; проверить,
      что PVC 20Gi и `sts/gpustack-server` не пересоздаются лишний раз (данные GPUStack — в PVC).
- [ ] **A6. Остальные релизы ns `gpustack`.** Решить судьбу оператора, kueue и CSI-драйверов:
      в тот же Application (Sync waves) или отдельные приложения.
- [ ] **A7. Приёмка.** SSO-вход в UI; `/v1/models` → 200; модели `running`; под сервера стабилен
      после двух `sync`; откат (sync предыдущей ревизии) описан и проверен.
- [ ] **A8. Доки.** `gpustack-spec` («Механизм развёртывания»), `architecture/ARCHITECTURE.md` §7, ADR о переносе;
      `ansible/gpustack-upgrade.sh` — либо удалить, либо оставить только для аварийного отката.

## 3. Риски

| Риск | Следствие | Чем снимаем |
|---|---|---|
| Adopt не сработал (другой release name/namespace) | Argo создаёт второй релиз, две БД, конфликт портов | A1: сверить имена до sync, `diff` плана Argo |
| `sync` затирает `envFrom`/`securityContext` патчи | SSO пропадает, postgres не стартует | A3/A4: патчи в том же Application (Kustomize), а не вне GitOps |
| Пересоздание `sts` при первом sync | простой API на минуты, риск для PVC | окно после показа, бэкап PVC/`pg_dump` до работ |
| Секрет OIDC попадёт в git | утечка клиентского секрета | A2: Secret вне Application; в git только имя |

## 4. Критерий готовности

`helm list -n gpustack` больше не требует ручных шагов: изменение values в git → Argo sync →
сервер с новыми настройками, SSO и модели живы, `kubectl -n gpustack get sts gpustack-server`
не содержит полей, пришедших из `kubectl patch` вне GitOps.
