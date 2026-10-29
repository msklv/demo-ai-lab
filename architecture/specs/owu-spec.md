# Спецификация установки Open WebUI (чат к моделям стенда)

> **Версия:** v1.3 (2026-10-28) · **Статус:** **развёрнуто 2026-10-28 (Argo CD, ns `owu`); O1–O3 сняты,
> O4–O6 (вход SSO, edge, диалог) — нет**
> **Цель:** шаг 2 демо — веб-чат к моделям GPUStack для аудитории: вход через Keycloak (SSO), модель
> `gemma-4-12B` по ключу GPUStack, файлы и чаты в Longhorn.
> **Внешнее имя:** `owu.demo-ai-lab.ru` (LAN — split-DNS на `.230`, снаружи — Cloudflare Tunnel).
> **Механизм развёртывания:** Argo CD — каталог `gitops/apps/owu` (Application создаёт ApplicationSet
> `apps`), helm-релиз внутри Argo-каталога нет: чарт ставится Argo как Helm-source **или** values рендерятся
> в манифесты; секреты — `Secret` в кластере, значения вне git.

Стиль-образцы: `architecture/specs/k8s-install-spec.md` (F\*), `architecture/specs/external-access-spec.md` (E\*),
`architecture/specs/keycloak-spec.md` (K\*), `architecture/specs/gpustack-spec.md` (G\*). Эта спека занимает букву **O**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Чарт | `open-webui/open-webui` **17.0.0** (appVersion **0.12.0**), репо `https://open-webui.github.io/helm-charts` | `helm search repo open-webui --versions` (2026-10-28); чарт = официальный, в Helm-репах консоли уже есть |
| Образ | `ghcr.io/open-webui/open-webui:0.12.0` (чарт при пустом `image.tag` подставляет AppVersion) — индекс `sha256:1565038903151ced924b5a3226f73f40f16963df4b910441f6391f10144afdaa`, amd64-манифест `sha256:208e824dd445548da7bd655a5e24718bf88112a7f60a807b5adb09096f2fd10b`, слои amd64 **1543 MiB / 19** | `skopeo inspect`/`--raw` (2026-10-28). **Чарт не умеет пин по digest** — рендерит `image: <repo>:<tag>` (`workload-manager.yaml:61`), поэтому фиксируем тег + сверяем digest в приёмке |
| Namespace | `owu` (создаёт ApplicationSet `apps` по имени каталога) | изоляция, TLS-секрет в своём ns (правило E-серии) |
| Реплики | **1** (`replicaCount: 1`) | SQLite + файловое состояние; 2 реплики требуют Postgres + Redis + RWX + внешнюю векторную БД — вне демо |
| Состояние | PVC **5Gi** `longhorn` RWO, монтируется в `/app/backend/data` (чаты, uploads, `vector_db/`, локальные эмбеддинги) | дефолт чарта 2Gi; 5Gi с запасом на загрузки |
| БД | SQLite (`DATABASE_URL` не задаём) + митигация на сетевом томе: `DATABASE_POOL_SIZE=1`, `DATABASE_SQLITE_PRAGMA_BUSY_TIMEOUT=30000` | у Longhorn сетевой том; с 0.9.0 async-backend даёт `QueuePool limit`/`database is locked` на сетевых ФС |
| Redis / websocket | `websocket.enabled: true`, `websocket.manager: ""`, `redis.enabled: false` | с одной репликой Redis не нужен; иначе чарт поднимает лишний контейнер `redis` |
| Ollama и прочие сабчарты | `ollama.enabled: false`, `pipelines.enabled: false`, `tika.enabled: false`, `terminals.enabled: false` | иначе тянется ollama-сабчарт (GPU не отдаём) |
| LLM-бэкенд | GPUStack: `openaiBaseApiUrl: https://api.demo-ai-lab.ru/v1`, ключ — `openaiApiKeyExistingSecret` (Secret в ns `owu`), `enableOllamaApi=false` | единственный инференс стенда — GPUStack (G0–G7). **Свой ключ `owu-gemma`** (id 6, только `gemma-4-12B`): whisper в чате не нужен, ключ `demo-step2` остаётся у `spk`. В списке моделей owu остаётся одна gemma — фильтр подключения `model_ids: ["gemma-4-12B"]` |
| SSO | чарт `sso.enabled: true`, `sso.oidc.*` → `OAUTH_CLIENT_ID/SECRET`, `OPENID_PROVIDER_URL`, `OAUTH_PROVIDER_NAME`; остальное через `extraEnvVars` | рендер проверен по `workload-manager.yaml:386-420` (гейт `sso.oidc.enabled`) |
| Redirect URI | `https://owu.demo-ai-lab.ru/oauth/oidc/callback` (явно в `OPENID_REDIRECT_URI`) | путь приложения (доки sso/OIDC + Keycloak-туториал) |
| Роли SSO | `ENABLE_OAUTH=true`, `ENABLE_OAUTH_SIGNUP=true`, `DEFAULT_USER_ROLE=user`, `ENABLE_SIGNUP=false`, `ENABLE_OAUTH_PERSISTENT_CONFIG=false` | иначе новые SSO-юзеры «висят» в `pending`, а env перестаёт быть источником правды |
| Ingress | **свой** `Ingress` класс `higress` + `Certificate` в ns `owu` (ClusterIssuer `letsencrypt-wildcard`), `ingress.enabled: false` у чарта | правило E-серии: TLS-секрет читается только в ns Ingress'а; ingress чарта не даёт нужного контроля |
| `WEBUI_URL` | `https://owu.demo-ai-lab.ru` через `extraEnvVars` | при `ingress.enabled: false` чарт его не выставит, а без него ломаются ссылки/редиректы |
| Публичность | **наружу публикуется** (демо-сервис шага 2), админка — только админ-роль в самом приложении | решение E6: демо-сервисы публичны; CI/CD-админок у owu нет |
| Пробы | `readinessProbe` `/health` (порт http), `livenessProbe` `/health`, `startupProbe` `/health` failureThreshold 30 | дефолты чарта — пустые `{}`: без проб под получает трафик до готовности БД |
| Ресурсы | requests `250m/1Gi`, limits `1/2Gi` | ориентир (доковского минимума нет; slim-idle ≈292 MiB), уточняется замером в O3 |
| Размещение | `affinity.nodeAffinity.preferred` на `demo-ai-lab/role=ingress` (02/03), `podAntiAffinity.preferred` к себе; **без hard-pin** | жёсткий `nodeSelector` = `Pending` при потере узла; k8s-04 занят GPUStack |
| Приоритет | `PriorityClass` не заводим; `resources` заданы (выше) | на 02/03 нет pressure, но пробы/лимиты обязательны — QoS Burstable |
| Секреты | `Secret owu-secrets`: `WEBUI_SECRET_KEY`, `OPENAI_API_KEY`; клиентские — `Secret` OIDC (из сида Keycloak) | в git только имена; значения — в приватных файлах/сиде |

## 2. Предпосылки — проверено 2026-10-28

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc                       # longhorn (default), longhorn-static
kubectl get ingressclass             # higress
kubectl get nodes -o custom-columns='N:.metadata.name,RAM:.status.allocatable.memory,CPU:.status.allocatable.cpu,ROLE:.metadata.labels.demo-ai-lab/role'
kubectl top nodes
kubectl -n longhorn-system get nodes.longhorn.io -o custom-columns='N:.metadata.name,AVAIL:.status.diskStatus.*.storageAvailable'
dig +short @192.168.10.1 owu.demo-ai-lab.ru    # LAN
dig +short @1.1.1.1      owu.demo-ai-lab.ru    # edge
curl -s -o /dev/null -w '%{http_code}\n' https://api.demo-ai-lab.ru/v1/models   # 401 без ключа
```

| Факт | Значение (замер) |
|---|---|
| StorageClass | `longhorn` default, `Immediate`, expansion on; свободно: 02/03/04 ≈ 244 GiB, 01 ≈ 68,7 GiB (вне пула реплик) |
| Ingress | class `higress`, VIP `.230`, `externalTrafficPolicy: Local`; образец пары Ingress+Certificate — `keycloak/auth-demo-tls` |
| Ноды | 01 — 30,5 GiB/16 CPU (компьют), 02 и 03 — 14,8 GiB/12 CPU, метка `demo-ai-lab/role=ingress`, 04 — 28,1 GiB/16 CPU (GPUStack/инференс) |
| Занято RAM | 02 — 6287 Mi (**свободно ≈8,6 GiB**), 03 — 5827 Mi (≈9,3 GiB), 01 — 5565 Mi, 04 — 21306 Mi (≈6,8 GiB) |
| DNS | `owu.demo-ai-lab.ru`: LAN → `192.168.10.230`, снаружи → anycast Cloudflare. **Отдельную DNS-запись не заводим**, но любой Ingress сразу публикуется наружу |
| Keycloak | issuer `https://auth.demo-ai-lab.ru/realms/dev`; клиенты сидятся `scripts/keycloak_seed.py`, приватные секреты — `keycloak-clients.local.md`; сейчас есть `gps`, `agent-runtime`, `mcp` |
| GPUStack | `api.demo-ai-lab.ru`, модели `gemma-4-12B` и `whisper-turbo` в состоянии `RUNNING`; `/v1/*` без ключа → **401** |
| Pod-сеть | Cilium cluster-pool `10.0.0.0/8` маска 24 (для trusted-proxies/лимитов) |

**Блокер предусловия:** ключа модели GPUStack нет (`api_keys` — только системные записи). Создаётся
владельцем в UI GPUStack (`API Keys → Create`), значение — в `gpustack-admin.local.md`; без него `owu`
не ответит ни на один запрос.

## 3. Секреты и приватные файлы

| Файл | Что внутри | Кто читает |
|---|---|---|
| `owu-admin.local.md` (0600, gitignored) | `WEBUI_SECRET_KEY`, admin-учётка приложения (создаётся headless через `WEBUI_ADMIN_EMAIL/PASSWORD` либо первым SSO-админом), ключ модели GPUStack | агент, человек |
| `keycloak-clients.local.md` | `owu` client secret (сид) | сид, Keycloak |
| `gpustack-admin.local.md` | admin GPUStack + ключи моделей | агент, человек |

- `.gitignore` — одно правило `*.local.md`; приёмка: `git check-ignore -v owu-admin.local.md` → матчится.
- В кластере: `Secret owu-secrets` (`WEBUI_SECRET_KEY`, `OPENAI_API_KEY`), `Secret owu-oidc`
  (`OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`) — создаёт сид/скрипт, в git только `envFrom`/`secretKeyRef`.
- `WEBUI_SECRET_KEY` обязан быть одинаковым на всех репликах (сейчас реплика одна, но ключ фиксируем
  в Secret, а не генерим при старте).
- Приёмка гигиены: собрать значения из приватных файлов и прогнать по `git ls-files`; отдельно
  пре-коммит-фильтр `AGENTS.md`.

## 4. Развёртывание

Состав `gitops/apps/owu/`:

| Файл | Что | Sync-wave |
|---|---|---|
| `10-secrets.yaml` → **не в git** | `Secret owu-secrets`, `Secret owu-oidc` создаются сидом/`kubectl create secret` до первого синка | — |
| `20-helm.yaml` | `Application`-совместимый рендер: helm-чарт `open-webui` 17.0.0 с values ниже (Argo `helm.valuesObject`), ns `owu` | 0 |
| `30-ingress.yaml` | `Certificate owu-demo-tls` + `Ingress` класс `higress` → `svc/<release>-open-webui:8080` | 0 |

Ключевые values (почему именно так):

```yaml
replicaCount: 1
image: { repository: ghcr.io/open-webui/open-webui, tag: "0.12.0", pullPolicy: IfNotPresent }
ollama: { enabled: false }
pipelines: { enabled: false }
tika: { enabled: false }
terminals: { enabled: false }
enableOpenaiApi: true
openaiBaseApiUrl: "https://api.demo-ai-lab.ru/v1"
openaiApiKeyExistingSecret: owu-secrets      # ключ модели GPUStack
openaiApiKeyExistingSecretKey: OPENAI_API_KEY
websocket: { enabled: true, manager: "", redis: { enabled: false } }
persistence: { enabled: true, size: 5Gi, accessModes: [ReadWriteOnce], storageClass: longhorn }
sso:
  enabled: true
  enableSignup: true
  oidc:
    enabled: true
    providerName: Keycloak
    providerUrl: "https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration"
    clientExistingSecret: owu-oidc
    clientIdExistingSecretKey: OAUTH_CLIENT_ID
    clientSecretExistingSecretKey: OAUTH_CLIENT_SECRET
    scopes: "openid email profile"
extraEnvVars:
  - { name: WEBUI_URL,                         value: "https://owu.demo-ai-lab.ru" }
  - { name: ENABLE_OAUTH,                      value: "True" }
  - { name: OPENID_REDIRECT_URI,               value: "https://owu.demo-ai-lab.ru/oauth/oidc/callback" }
  - { name: ENABLE_OAUTH_PERSISTENT_CONFIG,    value: "False" }
  - { name: ENABLE_SIGNUP,                     value: "False" }
  - { name: DEFAULT_USER_ROLE,                 value: "user" }
  - { name: WEBUI_SECRET_KEY,                  valueFrom: { secretKeyRef: { name: owu-secrets, key: WEBUI_SECRET_KEY } } }
  - { name: DATABASE_POOL_SIZE,                value: "1" }
  - { name: DATABASE_SQLITE_PRAGMA_BUSY_TIMEOUT, value: "30000" }
  - { name: ENABLE_DB_MIGRATIONS,              value: "true" }
  # модель внешнего подключения без записи в workspace-БД иначе видна только админу
  - { name: BYPASS_MODEL_ACCESS_CONTROL,       value: "true" }
resources:
  requests: { cpu: 250m, memory: 1Gi }
  limits:   { cpu: "1", memory: 2Gi }
readinessProbe: { httpGet: { path: /health, port: http }, initialDelaySeconds: 20, periodSeconds: 10 }
livenessProbe:  { httpGet: { path: /health, port: http }, initialDelaySeconds: 60, periodSeconds: 20, failureThreshold: 5 }
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        preference: { matchExpressions: [{ key: demo-ai-lab/role, operator: In, values: [ingress] }] }
```

- **Порт сервиса** — `8080` (`http`), чарт сам создаёт `Service`.
- Модель по умолчанию / список моделей: ENV-ограничения нет — доступ режется в Workspace → Models
  (hidden/private) после первого входа админом.
- `ENABLE_OAUTH_SIGNUP` рендерится из `sso.enableSignup`, `OAUTH_*` — из `sso.oidc.*`; остальное
  (`ENABLE_OAUTH`, `OPENID_REDIRECT_URI`, `DEFAULT_USER_ROLE`, `ENABLE_SIGNUP`) чарт не рендерит —
  только `extraEnvVars` (проверено `grep templates/`).

## 5. Конфигурация домена (Keycloak)

| Параметр клиента | Значение |
|---|---|
| clientId | `owu` (короткое имя хоста = clientId, правило `architecture/endpoints.md`) |
| тип | confidential, standard flow |
| redirect URI | `https://owu.demo-ai-lab.ru/oauth/oidc/callback` |
| web origins | `https://owu.demo-ai-lab.ru` |
| scopes | `openid email profile` (обязательны `openid`, `email`) |

Сидинг — расширение `scripts/keycloak_seed.py` (идемпотентный upsert: PUT с merge атрибутов, секрет
сохраняется); ручные правки в UI Keycloak источником правды не считаются. Приёмка сида — `GET` клиента
через admin API + факт входа.

## 6. Фазы и приёмка

### O1. Ключ модели GPUStack (предусловие, делает владелец в UI)

`api.demo-ai-lab.ru` → API Keys → Create → ключ в `gpustack-admin.local.md`.
Приёмка: `curl -H "Authorization: Bearer $KEY" https://api.demo-ai-lab.ru/v1/models` → `200` и в списке
`gemma-4-12B`.

### O2. Каркас в git + секреты

Каталог `gitops/apps/owu` (values + Ingress + Certificate), `Secret`-ы создаются до синка.
Приёмка: `kubectl -n argocd get app owu` → `Synced`; `kubectl -n owu get secret owu-secrets owu-oidc`.

### O3. Установка и базовый health

```bash
kubectl -n owu get pods,svc,pvc
kubectl -n owu rollout status deploy/owu-open-webui --timeout=300s
kubectl -n owu exec deploy/owu-open-webui -- curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/health
```
Приёмка: под `1/1`, PVC `Bound`, `/health` → `200`, рестартов 0; замер `kubectl top pod` пишется в §8
(заменить ориентир `1Gi/2Gi` фактическим).

### O4. SSO

Вход через `https://auth.demo-ai-lab.ru/realms/dev` → callback `/oauth/oidc/callback`.
Приёмка: `admin-test@demo-ai-lab.ru` входит, роль `user` (не `pending`); в Keycloak — запись о сессии;
`ENABLE_SIGNUP=False` проверен попыткой локальной регистрации (должна отсутствовать).

### O5. Публикация и путь

```bash
curl -s -o /dev/null -w '%{http_code}\n' --resolve owu.demo-ai-lab.ru:443:192.168.10.230 https://owu.demo-ai-lab.ru/
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 https://owu.demo-ai-lab.ru/        # снаружи (VM-egress)
```
Приёмка: LAN `200`, edge `200` (не 530/1033), серт `CN=owu.demo-ai-lab.ru` от LE.

### O6. Приёмка шага

Диалог с `gemma-4-12B` из UI (LAN и снаружи), загрузка файла в чат, ответ по нему; `kubectl -n gpustack
logs` — запрос дошёл до модели; таймаут ответа фиксируется замером (для репетиции шага 2).

## 7. Операции

| Задача | Как |
|---|---|
| Health | `kubectl -n owu get pods`; `GET /health`; `scripts/k8s_health.py --brief` |
| Бэкап | снапшот Longhorn тома `owu` (чаты/uploads) перед демо и апгрейдом; SQLite — только при остановленной реплике (`scale 0`), иначе копия без гарантий |
| Апгрейд | поднять `image.tag`/чарт в git → `Sync`; проверить `ENABLE_PERSISTENT_CONFIG=false` (иначе часть env игнорируется) |
| Ротация ключа GPUStack | новый ключ в UI → обновить `Secret owu-secrets` → `rollout restart` |
| Смена `WEBUI_SECRET_KEY` | разлогинивает всех; делать только с остановкой |
| Ограничение моделей | Workspace → Models → hidden/private (ENV-ручки нет) |

## 8. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-O1** | SQLite на сетевом томе Longhorn: `database is locked`/`QueuePool limit` под нагрузкой | `DATABASE_POOL_SIZE=1`, `BUSY_TIMEOUT=30000`; при повторении — Postgres в ns `owu` (путь миграции) |
| **R-O2** | Дефолт `DEFAULT_USER_ROLE=pending` + `ENABLE_SIGNUP=True` → SSO-юзеры «висят», регистрация открыта | явные env (см. §4), проверка в O4 |
| **R-O3** | ConfigVar-переменные после первого старта читаются из БД | `ENABLE_OAUTH_PERSISTENT_CONFIG=false`; менять env только с пересозданием БД либо в админке |
| **R-O4** | Чарт не пинит digest — образ под тем же тегом может измениться | сверять digest в O3 (`imageID`), фиксировать в §10; апгрейд — только осознанно |
| **R-O5** | Одна реплика + RWO-том: при потере узла под не переедет | preferred-affinity, RTO = переаттач Longhorn 1–3 мин; в демо-сценарии owu критичен → репетиция с таймером |
| **R-O6** | Память: локальные эмбеддинги и pypdf-экстрактор растут при загрузке файлов | лимит 2Gi + мониторинг; при OOM — `RAG_EMBEDDING_ENGINE=openai` (эмбеддинги на 780M) |
| **R-O7** | Публичный чат без квот — любой внешний пользователь жжёт GPU | SSO-вход обязателен (локальные учётки выключены), лимиты на ингрессе при необходимости |

## 9. Что забывают в таких спеках (и что решено здесь)

| Пункт | Решение |
|---|---|
| TLS в namespace Ingress'а | свой `Certificate owu-demo-tls`, не wildcard из `demo-test` |
| `WEBUI_URL` при выключенном ingress чарта | задаётся через `extraEnvVars` |
| Пробы | чарт по умолчанию без проб — заданы в values |
| Ключ модели | без ключа GPUStack UI открывается, но чат `401` — предусловие O1 отдельной фазой |
| Список моделей | ENV-ручки нет: Workspace → Models |
| Бэкап SQLite | только при остановленной реплике |

Открытые вопросы:

1. **Реплики:** остаёмся на 1 + SQLite (рекомендация) или Postgres + Redis + 2 реплики (стоимость — два
   новых компонента и RWX-том). *(Рекомендация: 1 реплика; переезд — отдельной задачей.)*
2. **Эмбеддинги для файлов в чате:** локальные в поде (RAM) или `RAG_EMBEDDING_ENGINE=openai` с моделью
   эмбеддингов на 780M. *(Решается после того, как RAG-стек поднимет `bge-m3`.)*
3. **Гость без SSO:** нужен ли демо-режим «просто спросить» — тогда отдельный пользователь с
   ограниченной квотой, а не открытая регистрация.

## 10. Связанные документы и история версий

- `architecture/endpoints.md` — адрес `owu`, кто за SSO.
- `architecture/specs/keycloak-spec.md` — клиенты, сид, redirect-правила.
- `architecture/specs/gpustack-spec.md` — модели и ключи API.
- `references/service-spec-authoring.md`, `references/demo-plan.md` (RAM-бюджет шага 2).

| Версия | Дата | Что |
|---|---|---|
| v1.3 | 2026-10-28 | **Список моделей и параметры чата.** (1) whisper из owu убран: отдельный ключ GPUStack `owu-gemma` (только `gemma-4-12B`; на whisper — 403) + фильтр подключения `model_ids`; (2) `BYPASS_MODEL_ACCESS_CONTROL=true` — в 0.12 модель внешнего подключения без записи в workspace-БД видна **только админу** (`utils/models.py: elif user.role == 'admin'`), поэтому обычный SSO-юзер видел пустой список; курируемая workspace-модель не годится — у неё `missing_base_model` и чат падает `Model not found`; (3) `max_tokens` задаётся админским `DEFAULT_MODEL_PARAMS` **плоским** словарём (`{"max_tokens": 2048}` → `models.default_params`), а НЕ по id модели: с ключом по id параметр молча не применялся (замер: 4892 токена в ответе), после правки — ровно 2048, `finish_reason=length`. Тип модели остаётся `connection_type=external`: Open WebUI считает «внутренними» только модели Ollama, у GPUStack Ollama-API нет (0 путей в openapi; `/ollama/api/tags` и `/api/tags` → 404) |
| v1.2 | 2026-10-28 | **Чат не работал из-за тул-коллинга (исправлено вне `owu`)**: Open WebUI прикладывает встроенные инструменты к каждому запросу (`tools` + `tool_choice: "auto"`), а vLLM в GPUStack отвечал `400 "auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set` — падал даже обычный диалог. В модель `gemma-4-12B` добавлены `--enable-auto-tool-choice --tool-call-parser gemma4` (пересозданием инстанса); правок в `owu` не потребовалось. Проверка API: обычный диалог, `tools`+`auto` → 200 с `tool_calls`, стрим → 200. O6 — диалог подтверждён на уровне API, проверка в UI за владельцем |
| v1.1 | 2026-10-28 | **Развёрнуто через Argo CD** (`gitops/apps/owu`, Application `owu` — Synced/Healthy): O1 — ключ модели `demo-step2` (id 5, `gemma-4-12B`+`whisper-turbo`) выдан через API GPUStack и записан в `gpustack-admin.local.md`; O2/O3 — под 1/1, PVC Bound, LAN `/` → 200. Факты, поправившие спеку: (1) ApplicationSet `apps` не умеет helm-source → чарт **отрендерен в plain-манифесты** (`20-open-webui.yaml`), values — `gitops/values/owu.yaml`; (2) при `persistence.enabled` чарт создаёт **StatefulSet** `owu-open-webui`, не Deployment; (3) Service публикуется на **80** (targetPort 8080) — Ingress ссылается на 80; (4) клиент Keycloak `owu` заведён сидом, `redirectUris` сверены admin-API. O4–O6 не сняты |
| v1.0 | 2026-10-28 | Первая версия. Живой замер: чарт 17.0.0/appVersion 0.12.0, digest образа и рендер `sso.oidc`→`OAUTH_*` по шаблонам, свободная RAM 02/03, DNS LAN/edge, отсутствие ключа GPUStack (`401`), Longhorn-ёмкости. Не установлено |
