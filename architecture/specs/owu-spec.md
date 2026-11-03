# Спецификация установки Open WebUI (чат к моделям стенда)

> **Версия:** v1.6 (2026-11-03) · **Статус:** **развёрнуто 2026-10-28 (Argo CD, ns `owu`); O1–O3 сняты;
> O4–O6 (вход SSO, edge, диалог) сняты по факту 28–29.10; RAG-эмбеддинги и реранк переведены на модели
> 780M 2026-11-03 (§7.4)**
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
| LLM-бэкенд | GPUStack: `openaiBaseApiUrl: https://api.demo-ai-lab.ru/v1`, ключ — `openaiApiKeyExistingSecret` (Secret в ns `owu`), `enableOllamaApi=false` | единственный инференс стенда — GPUStack (G0–G7). **Один ключ ко всем моделям — `owu-all`** (id 22, решение владельца 2026-11-02, §7.2): переключение моделей между кейсами не требует перевыпуска ключа; что видно в чате — режет фильтр подключения `model_ids: ["gemma-4-12B", "Qwen3.8-27B-UD"]` (whisper/guard в чат не выставляются). Ключи `owu-gemma` (id 6) и `demo-step2` для OWU не используются (не отзывать без решения), `demo-step2` остаётся у `spk` |
| RAG (эмбеддинги/реранк) | **наши модели 780M в GPUStack через env**: `bge-m3` (dim 1024, `/v1/embeddings`) + `bge-reranker-v2-m3` (`/v1/rerank`, только при гибридном поиске) — §7.4 | локальный `sentence-transformers/all-MiniLM-L6-v2` не тянется (384 dim и CPU); пара живёт на iGPU k8s-04, ту же карту делят оба кейса 05/06 |
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
| Ротация ключа GPUStack | новый ключ (scope — все модели) в UI → записать в **webui.db** `openai.api_keys[0]` → `rollout restart`. `Secret owu-secrets`/values действуют только до первого старта (R-O3) — менять их бесполезно |
| Смена `WEBUI_SECRET_KEY` | разлогинивает всех; делать только с остановкой |
| Ограничение моделей | Workspace → Models → hidden/private (ENV-ручки нет) |

### 7.1 Второе подключение — внешняя модель через `llm-svc.`

Подключения OpenAI-совместимых моделей живут **в БД OWU** (таблица `config`, ключи
`openai.api_base_urls`, `openai.api_keys`, `openai.api_configs`), а не в `values`: values задаёт
только первое подключение (GPUStack) через `openaiBaseApiUrl` + `openaiApiKeyExistingSecret`, а после
первого старта конфиг живёт в БД (риск R-O3).

**Правило (2026-11-02):** в env/values — **только первое подключение** (`OPENAI_API_BASE_URL` =
`https://api.demo-ai-lab.ru/v1`). Второе (`llm-svc.`) в env **не прописывается**: его место — БД OWU
(`openai.api_base_urls[1]`, `openai.api_keys[1]`, `openai.api_configs["1"]`). Вариант с
`OPENAI_API_BASE_URLS`/`OPENAI_API_KEYS` отклонён: это второй набор ключей в манифесте/env, дублирование
источника истины и лишний секрет вне Secret. Минус решения: второе подключение не в git и не
восстанавливается Argo — после пересоздания PVC/переустановки его надо завести заново по блоку ниже
(бэкап `webui.db` лежит на том же PVC, см. «Применение»).

Второе подключение (2026-11-01) — `deepseek-flash` через `llm-svc.demo-ai-lab.ru`: внешняя модель в UI
идёт тем же защищённым маршрутом, что и программные клиенты (DLP, страж fail-closed, квоты, ключ
провайдера на шлюзе), а не напрямую к провайдеру.

```json
// config: openai.api_configs["1"]   (пути: api_base_urls[1] = https://llm-svc.demo-ai-lab.ru/v1,
//                                     api_keys[1]     = тот же статический ключ)
{"enable": true, "tags": [], "prefix_id": "", "model_ids": ["deepseek-flash"],
 "connection_type": "external", "auth_type": "none",
 "headers": {"x-api-key": "<ключ llm-svc из llm.local.md>"},
 "forward_cookies": false, "passthrough_params": []}
```

- `auth_type: none` + `headers` — потому что `llm-svc.` проверяет статический ключ в заголовке
  `x-api-key` (плагин `key-auth`), а OWU по умолчанию шлёт `Authorization: Bearer <ключ>`. Порядок в
  коде: `open_webui/utils/headers.py: get_headers_and_cookies` → `config.get('headers')` (кастомные
  заголовки накладываются после auth и умеют подстановки вида `{{USER_EMAIL}}`).
- `model_ids` режет список подключения до нужных моделей — так же из первого подключения убран whisper.
  Факт 2026-11-02: `api_configs["0"].model_ids = ["gemma-4-12B", "qwen3.8-27b"]`,
  `api_configs["1"].model_ids = ["deepseek-flash"]`. Модели `qwen3.8-27b` в каталоге GPUStack сейчас
  **нет** (она не задеплоена), поэтому в списке появится только после её заведения; `gemma-4-12B`
  видна, когда инстанс запущен.
- Применение: правка трёх строк `config` в `/app/backend/data/webui.db`, затем
  `kubectl -n owu rollout restart sts/owu-open-webui` — конфиг читается на старте. Бэкап кладём **на PVC**
  (`cp /app/backend/data/webui.db /app/backend/data/webui.db.bak-<ts>`): `/tmp` внутри пода стирается
  при рестарте, то есть ровно тогда, когда бэкап и понадобится.
- Проверка: из пода `owu` запрос с заголовком `x-api-key` к `https://llm-svc.demo-ai-lab.ru/v1/models`
  → `200`; в UI в списке моделей появляется `deepseek-flash`.
- Диагностика «модель есть, а чат падает»: 503 `guard unavailable: request blocked (fail-closed)`
  в логах OWU означает недоступный страж на маршруте — смотри ключ `guard` и доступ к модели
  `Qwen3Guard-Gen-4B` (страж вызывается через `api.demo-ai-lab.ru`, регистр `guard`).

### 7.2 Ключ OWU → GPUStack: доступ ко всем моделям (правило 2026-11-02)

OWU подключается к GPUStack **одним ключом с доступом ко всем моделям** — `owu-all` (id 22,
`allowed_model_ids: null`; значение в `gpustack-admin.local.md`). Причина: демо переключает резидентов
карты между кейсами (gemma ↔ `Qwen3.8-27B-UD`); per-model ключ требовал бы пересборки Access Control и
ключа в БД OWU на каждое переключение, а пересборка списка на существующем ключе — грабля «ключ
внезапно теряет прежние модели» (403 `Not allowed to access model`).

Разделение ответственности:
- **ключ** (`owu-all`) решает, что OWU *разрешено*; гейт GPUStack и так отдаёт в `/v1/models` только
  реально `RUNNING` модели — переключение кейса = `Start`/`Stop` в GPUStack, OWU подхватывает список сам;
- **фильтр подключения** `openai.api_configs["0"].model_ids` (webui.db) решает, что *показываем* в чате:
  сейчас `gemma-4-12B` + `Qwen3.8-27B-UD`; ASR/страж в список не вносить;
- `beellama-test` (id 21) — только для API-приёмки спеки `architecture/specs/gpustack-custom-backend-spec.md`, OWU им не работает.

Порядок правки — как в §7.1 (правка `config` в webui.db + `rollout restart`), проверка — репликация
запроса OWU из пода (GET `/models` + POST `/chat/completions` с `tools`+`tool_choice: auto`): BeeLlama
корректно переносит tools-обвязку OWU (ответ `stop`, вызова инструмента нет) — грабли v1.2 (vLLM 400) тут нет.

### 7.3 Движок извлечения документов — Docling стенда, через env (2026-11-02)

Загрузка файлов в чат пардится **наш же Docling** (`architecture/specs/doc-spec.md`), а не встроенный pypdf.
Источник настройки — **env пода** (gitops `values/owu.yaml` → перерендер → sync), НЕ БД: DB-вариант
проверки 02.11 был откачен владельцем. Механика этого билда (`models/config.py`): `ENABLE_PERSISTENT_CONFIG`
по умолчанию `true`, поэтому строка таблицы `config` **перекрывает** env, а при **отсутствии** строки
берётся `default_value` = env-дефолт; `seed_defaults` при старте досевает только отсутствующие строки.
Значит для этих ключей строк в `config` быть не должно — их нет (удалены 02.11), значения приходят из env:

| Env (values → манифест) | Значение | Зачем |
|---|---|---|
| `CONTENT_EXTRACTION_ENGINE` | `docling` | выбор движка (key `rag.content_extraction_engine`, config.py:874) |
| `DOCLING_SERVER_URL` | `http://docling.doc.svc.cluster.local:5001` | **FQDN обязателен**: дефолт `http://docling:5001` — имя сервиса в ns `doc`, из ns `owu` не резолвится |
| `DOCLING_PARAMS` | `{"ocr_preset": "ru-en"}` | **обязательно**: OWU шлёт только свои фиксированные поля form-data, а docling без `ocr_preset` идёт `auto` и плохо берёт кириллицу (грабля doc-spec v1.2) |
| `DOCLING_API_KEY` | не задаём | `DOCLING_SERVE_API_KEY` на стенде нет (закрытие Higress'ом, не ключом) |

Грабли env-пути:
- если кто-то сохранит Settings → Documents в UI, `upsert` создаст строки `rag.docling_*` и **зафиксирует
  в БД то, что показано в форме** — env для этих ключей перестанет влиять. Симптом: поменяли values,
  sync прошёл, а движок прежний. Диагностика: `select * from config where key like '%docling%'`;
  лечение — удалить строки + `rollout restart` (досеется из env);
- применение — только коммит values + перерендер манифеста (команда в `gitops/apps/owu/README.md`) +
  sync (Argo пересоздаст под по изменению pod-template); руками env в под не лить (GitOps).

Контракт: `DoclingLoader` (`retrieval/loaders/main.py`) → `POST /v1/convert/file` (multipart,
`to_formats=md,json`) — штатная синхронная ручка docling-serve, контракт v1.38.2 проверен 2026-11-02
репликацией запроса из пода `owu`: `status: success`, `md_content` читается; в логах docling-serve
конвертация видна. Тяжёлые документы идут через синхронный лимит docling (`MAX_SYNC_WAIT=600` с 2026-11-03;
было 120 — сканы с OCR не успевали и OWU получал `504`), для
пакетов длинных PDF остаётся async-путь docling напрямую (не через OWU).

### 7.4 Эмбеддинги и реранк RAG — `bge-m3` + `bge-reranker-v2-m3` на 780M (2026-11-03)

RAG Open WebUI (Knowledge/загрузки в чат) считает эмбеддинги **на нашем стенде**, а не локальной
sentence-transformers-моделью: движок `openai` = любой OpenAI-совместимый эндпоинт, у нас — GPUStack.
Реранк — `external`, наш vLLM-инстанс `bge-reranker-v2-m3`. Обе модели заведены как модели GPUStack
кастомным бэкендом на 780M (`architecture/specs/gpustack-spec.md` §4.6).

Источник настройки — **env пода** (gitops `values/owu.yaml` → перерендер → sync), механика та же, что
в §7.3: строка таблицы `config` перекрывает env, поэтому для этих ключей строк в БД быть не должно.

| Env (values → манифест) | Значение | Зачем |
|---|---|---|
| `RAG_EMBEDDING_ENGINE` | `openai` | движок эмбеддингов; поля «OpenAI API URL / Embedding Model» в UI появляются **только** при этом значении (`Documents.svelte:1031`) |
| `RAG_EMBEDDING_MODEL` | `bge-m3` | имя модели в `/v1/embeddings`; dim **1024** (у дефолтного all-MiniLM — 384) |
| `RAG_OPENAI_API_BASE_URL` | `https://api.demo-ai-lab.ru/v1` | тот же шлюз GPUStack, что и у чата |
| `RAG_OPENAI_API_KEY` | из `owu-secrets/OPENAI_API_KEY` | это ключ `owu-all`; per-model ключ даёт `403 Not allowed to access model bge-m3` |
| `RAG_EMBEDDING_BATCH_SIZE` | `8` | замер bge-m3 на 780M: батч 8 ≈ 2.3k tok/s, одиночные запросы вдвое хуже |
| `RAG_EMBEDDING_MODEL_AUTO_UPDATE` | `False` | не тянуть модель с HF (внешней модели нет локально) |
| `ENABLE_RAG_HYBRID_SEARCH` | `true` | **условие работы реранка**: без гибридного поиска OWU реранк не вызывает вообще |
| `RAG_RERANKING_ENGINE` | `external` | включает `ExternalReranker` (`routers/retrieval.py:182` — `if reranking_model and engine == 'external'`) |
| `RAG_RERANKING_MODEL` | `bge-reranker-v2-m3` | уходит в payload как `model` |
| `RAG_EXTERNAL_RERANKER_URL` | `https://api.demo-ai-lab.ru/v1/rerank` | полный URL ручки, а не база |
| `RAG_EXTERNAL_RERANKER_API_KEY` | из `owu-secrets/OPENAI_API_KEY` | `Authorization: Bearer …`; отдельной переменной, потому что дефолт — пустая строка, а не `OPENAI_API_KEY` |
| `RAG_RERANKING_BATCH_SIZE` | `8` | столько пар «запрос/чанк» уходит в одном запросе |

Контракт реранкера (`retrieval/models/external.py`, 0.12): `POST <URL>` с
`{"model", "query", "documents": [...], "top_n": len(documents)}` и `Authorization: Bearer <ключ>`,
ответ читается из `data["results"]` по полю `relevance_score` — ровно схема vLLM `/v1/rerank`.

Грабли (каждая проверена 03.11):

1. **Ключ в env был чужой.** `Secret owu-secrets/OPENAI_API_KEY` хранил `demo-step2`
   (модели `gemma-4-12B`, `whisper-turbo`), потому что env применяется только при **первом** старте
   (R-O3), а дальше OWU живёт на ключе из БД (`owu-all`). Эмбеддинги с этим ключом отвечали
   `403 Not allowed to access model bge-m3`. Лечение: `OPENAI_API_KEY` = `owu-all` (значение из
   `gpustack-admin.local.md`), после чего env и БД согласованы; `RAG_OPENAI_API_KEY` наследует его.
2. **Строки `config` перекрывают env** — те же 10 ключей: `rag.embedding_engine`,
   `rag.embedding_model`, `rag.openai.api_base_url`, `rag.openai.api_key`, `rag.enable_hybrid_search`,
   `rag.reranking_engine`, `rag.reranking_model`, `rag.external_reranker_url`,
   `rag.external_reranker_api_key`, `rag.external_reranker_timeout`. Удалены 03.11 (бэкап
   `webui.db.bak-20261103-002043` на PVC) → `rollout restart` → `seed_defaults` пересоздал их из env
   (проверено: `"openai"`, `"bge-m3"`, `true`, `"external"`, `"bge-reranker-v2-m3"`).
3. **Сохранение страницы Documents в UI** делает `upsert` и фиксирует в БД то, что в форме, — после
   этого env для этих ключей не влияет (как и в §7.3).
4. **Смена размерности ломает старые коллекции** (384 → 1024). На 03.11 в OWU не было ни одной базы
   знаний (`knowledge: 0`), поэтому переход безопасен; при появлении знаний переиндексация обязательна.
5. **Селектор «Embedding Model Engine» пропадает целиком** только при `BYPASS_EMBEDDING_AND_RETRIEVAL=true`
   (`Documents.svelte:1001`); мы его не ставим. Если полей OpenAI URL/Model «не видно» — значит движок
   всё ещё `Default (SentenceTransformers)`.

Приёмка (03.11): env в поде = значения выше; строки `config` пересозданы из env; из **пода OWU**
`POST /v1/embeddings` → 200, dim 1024, `POST /v1/rerank` → 200 (payload и заголовок — как в контракте);
в логах инстанса `bge-m3` виден `POST /v1/embeddings 200`. Прогон реальной загрузки документа и
поиска с реранком — за владельцем в UI (Knowledge → загрузить → вопрос).

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
- `architecture/ARCHITECTURE.md` §5 — RAM-бюджет размещения (OWU ≈1 GiB на 03; свободно ≈9,3 GiB на 28.10).
- `references/service-spec-authoring.md` — правила оформления спеки.

| Версия | Дата | Что |
|---|---|---|
| v1.6 | 2026-11-03 | **RAG переведён на модели 780M через env (§7.4).** `RAG_EMBEDDING_ENGINE=openai` + `RAG_EMBEDDING_MODEL=bge-m3` (dim 1024, батч 8) + `RAG_OPENAI_API_BASE_URL=api./v1`; `ENABLE_RAG_HYBRID_SEARCH=true` + `RAG_RERANKING_ENGINE=external` + `RAG_RERANKING_MODEL=bge-reranker-v2-m3` + `RAG_EXTERNAL_RERANKER_URL=api./v1/rerank`. Удалены 10 строк-перекрытий `rag.*` из `webui.db` (env побеждает лишь при отсутствии строки; бэкап БД на PVC). `Secret owu-secrets/OPENAI_API_KEY` переведён с `demo-step2` на `owu-all` — старым ключом эмбеддинги получали `403 Not allowed to access model bge-m3`. Проверено из пода: `/v1/embeddings` 200 (dim 1024), `/v1/rerank` 200. Латентность тёплого вызова на 780M: 0.18 с / 0.08 с |
| v1.7 | 2026-11-02 | **Docling в OWU — через env, правки БД откачены владельцем:** env `CONTENT_EXTRACTION_ENGINE`/`DOCLING_SERVER_URL`/`DOCLING_PARAMS` в gitops values→манифест; строки `rag.docling_*`/`rag.content_extraction_engine` удалены из `config` (механика этого билда: строка перекрывает env, отсутствие строки = env; §7.3). До sync движок дефолтный (`basic`) |
| v1.6 | 2026-11-02 | **Извлечение документов OWU = Docling стенда (§7.3):** `rag.content_extraction_engine=docling`, URL внутри кластера по FQDN (`http://docling.doc.svc.cluster.local:5001`, дефолт `http://docling:5001` межнейменносно не резолвится), `rag.docling_params={"ocr_preset":"ru-en"}` — без пресета docling идёт `auto` и теряет кириллицу (doc-spec v1.2). Репликация DoclingLoader-запроса из пода owu: `success`, md есть |
| v1.5 | 2026-11-02 | **OWU → GPUStack одним ключом со всеми моделями (§7.2, решение владельца):** новый ключ `owu-all` (id 22) записан в webui.db `openai.api_keys[0]`; фильтр `model_ids[0]` = `gemma-4-12B` + `Qwen3.8-27B-UD` (мёртвый id `qwen3.8-27b` убран — модель заведена как `Qwen3.8-27B-UD`); ad-hoc подключение `beellama-test` из БД снято. Проверено репликацией OWU-запроса из пода: `/models` → `Qwen3.8-27B-UD`, chat с `tools`+`auto` → `144`, finish `stop`. `owu-gemma`/`demo-step2` для OWU не используются, не отозваны |
| v1.4 | 2026-11-02 | **Два провайдера в OWU, второй — только в БД.** Env/values оставлены с одним подключением (`api.`); `llm-svc.` (DeepSeek flash, DLP+страж fail-closed) заведён вторым подключением в `config` БД: `api_base_urls[1]`, `api_keys[1]`, `api_configs["1"]` с `auth_type: none` и заголовком `x-api-key` (см. §7.1). Причина: `OPENAI_API_BASE_URLS`/`OPENAI_API_KEYS` кладут второй ключ в env и дублируют источник истины. Фильтры: локальное подключение — `gemma-4-12B` + `qwen3.8-27b`, внешнее — только `deepseek-flash` (v4-pro скрыт). Факты: `qwen3.8-27b` в GPUStack отсутствует, `gemma` остановлена — список локальных моделей пуст, пока инстанс не запущен; страж 4B занимает карту, поэтому gemma и внешний маршрут одновременно не работают |
| v1.3 | 2026-10-28 | **Список моделей и параметры чата.** (1) whisper из owu убран: отдельный ключ GPUStack `owu-gemma` (только `gemma-4-12B`; на whisper — 403) + фильтр подключения `model_ids`; (2) `BYPASS_MODEL_ACCESS_CONTROL=true` — в 0.12 модель внешнего подключения без записи в workspace-БД видна **только админу** (`utils/models.py: elif user.role == 'admin'`), поэтому обычный SSO-юзер видел пустой список; курируемая workspace-модель не годится — у неё `missing_base_model` и чат падает `Model not found`; (3) `max_tokens` задаётся админским `DEFAULT_MODEL_PARAMS` **плоским** словарём (`{"max_tokens": 2048}` → `models.default_params`), а НЕ по id модели: с ключом по id параметр молча не применялся (замер: 4892 токена в ответе), после правки — ровно 2048, `finish_reason=length`. Тип модели остаётся `connection_type=external`: Open WebUI считает «внутренними» только модели Ollama, у GPUStack Ollama-API нет (0 путей в openapi; `/ollama/api/tags` и `/api/tags` → 404) |
| v1.2 | 2026-10-28 | **Чат не работал из-за тул-коллинга (исправлено вне `owu`)**: Open WebUI прикладывает встроенные инструменты к каждому запросу (`tools` + `tool_choice: "auto"`), а vLLM в GPUStack отвечал `400 "auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set` — падал даже обычный диалог. В модель `gemma-4-12B` добавлены `--enable-auto-tool-choice --tool-call-parser gemma4` (пересозданием инстанса); правок в `owu` не потребовалось. Проверка API: обычный диалог, `tools`+`auto` → 200 с `tool_calls`, стрим → 200. O6 — диалог подтверждён на уровне API, проверка в UI за владельцем |
| v1.1 | 2026-10-28 | **Развёрнуто через Argo CD** (`gitops/apps/owu`, Application `owu` — Synced/Healthy): O1 — ключ модели `demo-step2` (id 5, `gemma-4-12B`+`whisper-turbo`) выдан через API GPUStack и записан в `gpustack-admin.local.md`; O2/O3 — под 1/1, PVC Bound, LAN `/` → 200. Факты, поправившие спеку: (1) ApplicationSet `apps` не умеет helm-source → чарт **отрендерен в plain-манифесты** (`20-open-webui.yaml`), values — `gitops/values/owu.yaml`; (2) при `persistence.enabled` чарт создаёт **StatefulSet** `owu-open-webui`, не Deployment; (3) Service публикуется на **80** (targetPort 8080) — Ingress ссылается на 80; (4) клиент Keycloak `owu` заведён сидом, `redirectUris` сверены admin-API. O4–O6 не сняты |
| v1.0 | 2026-10-28 | Первая версия. Живой замер: чарт 17.0.0/appVersion 0.12.0, digest образа и рендер `sso.oidc`→`OAUTH_*` по шаблонам, свободная RAM 02/03, DNS LAN/edge, отсутствие ключа GPUStack (`401`), Longhorn-ёмкости. Не установлено |
