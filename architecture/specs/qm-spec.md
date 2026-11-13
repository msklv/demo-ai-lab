# qm — мультиагентный рантайм стенда (`qm.demo-ai-lab.ru`): SSO, org `demo-lab`, 3 MCP, две модели, эмбеддинги, песочницы

> **Версия:** v1.0 (2026-11-12) · **Статус:** **спека, не установлено** — Ingress для `qm.` не заведён
> (`architecture/endpoints.md`: «план: шаг 4»), ns `qm` в кластере отсутствует (проверено 2026-11-12).
> **Цель:** шаг 4 демо — мультипользовательский агентный рантайм **qm** ([`yc-software/qm`](https://github.com/yc-software/qm),
> форк `msklv/qm`) в кластере стенда: вход по **SSO Keycloak** (`auth.demo-ai-lab.ru`, realm `dev`), организация
> **`demo-lab`**, две модели (**`Qwen3.8-27B-UD`** локально через `api.`/GPUStack и **`deepseek-flash`**
> снаружи через `llm-svc.`), **три MCP-сервера стенда** (`doc.`, `ysrch.`, `mon.`), семантическая память на
> эмбеддингах **`bge-m3`**, песочницы агентов (режим — решение владельца, §4).
> **Внешнее имя:** `qm.demo-ai-lab.ru` — LAN через split-DNS на `.230`, снаружи — edge (ADR-0004).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/qm/` (plain-манифесты, как `her/`, `fc/`);
> upstream-чарт `deploy/helm` **рендерится в файл** через `gitops/values/qm.yaml` (дисциплина `owu-spec` §4).
> Secret'ы создаются **до** первого синка и в git не попадают.
> Ничего секретного здесь нет: ключи — в `qm.local.md` / `keycloak-clients.local.md` (в `.gitignore`), в кластере — Secret `qm-runtime`.
>
> **Что решено владельцем:** кастомные образы форка `v0.1.17-ai-lab` (§1.1), SSO (§6), org `demo-lab` (§1),
> две модели (§7), все три MCP (§8), эмбеддинг `bge-m3` (§7.4). **Что требует решения:** режим песочниц (§4.4)
> и судьба «системы извлечения данных» Firecrawl (§8.3).

Стиль-образцы: `architecture/specs/hermes-spec.md` (H\*), `architecture/specs/owu-spec.md` (O\*),
`architecture/specs/keycloak-spec.md` (K\*), `architecture/specs/llm-proxy-spec.md` (P\*),
`architecture/specs/gpustack-spec.md` (G\*), `references/service-spec-authoring.md` (метод). Эта спека занимает
букву **Q**. Решения ADR не пересматриваются: ADR-0003 (размещение), ADR-0004 (внешний доступ),
ADR-0006/0008 (внешний LLM только через `llm-svc.` за DLP и стражем).

---

## 0. Что уточнила сверка с исходниками (2026-11-12)

Сверялись: `msklv/qm` на теге **`v0.1.17-ai-lab`** (HEAD `6b8aa69`), `deploy/helm`, `deploy/core/Dockerfile`,
`src/config.ts`, `src/sandbox/*`, `src/api/routes/admin/*`, `src/model/*`, `src/deployment/secret-schema.ts`.
Всё ниже — факт из кода/реестра, а не «как обычно бывает у агентных платформ».

| Что | Ожидание «по аналогии» | Факт (проверено 2026-11-12) |
|---|---|---|
| Состав сервисов | отдельные поды/web-ui/portal/admin | **В v0.1.17 семь старых сервисов свёрнуты в один `core`**: `SERVICE_NAMES = [core, egress-proxy]`, web-UI + портал входа + админ-панель оператора (`/settings`) вшиты в образ (`deploy/core/Dockerfile` копирует `plugins/{chassis,auth,portal,web-ui}` внутрь core). Один Ingress → **порт 8000** (публичный front door), API — 8080 только внутри ns |
| Картинки релиза | тег `v0.1.17` в GHCR | Форк собирает **`v0.1.17-ai-lab`** (workflow `branch-images.yml`, матрица: `core`, `egress-proxy`, `sandbox-base`). Дигайлы сверены запросом к GHCR 2026-11-12 и совпали с присланными владельцем (§1.1). Анонимный pull работает (пакеты публичные) — `imagePullSecret` не нужен |
| База | «SQLite/PG на выбор» | `DATABASE_URL` **обязателен** (`secret-schema.ts`: `requiredWhen: production`), миграции на старте; семантическая память требует расширения **pgvector** (`CREATE EXTENSION vector` из миграции `memory/vectors/0001` → нужен суперпользователь в URL). В compose-таргете CLI поднимает именно `pgvector/pgvector:0.8.1-pg16` |
| Сандбоксы в кластере | «есть же helm — значит и сандбоксы» | **Бэкенда `k8s` нет.** В v0.1.17 доступны `local, sprites, smolmachines, e2b, modal, porter, agent37, superserve, do-managed-agents, render, aws` (`sandbox-settings.ts`); [deploy/helm/README.md](https://github.com/msklv/qm/blob/v0.1.17-ai-lab/deploy/helm/README.md) прямо пишет: *«A supported sandbox backend and its credentials. Kubernetes hosting does not configure sandbox provisioning»*. `local` управляет Docker CLI/демоном и адресует сандбокс **по имени контейнера в том же демоне**, что и core (`coreContainer`), иначе публикует `127.0.0.1:<random>` — из пода это недостижимо. Разбор и варианты — §4 |
| Контракт песочницы | «тяжёлый агент внутри» | Сандбокс = **exec-daemon по HTTP на 8080**: `GET /health`, `POST /exec {cmd,timeoutSec}`, `POST /write {path,b64}`, `POST /read {path}` (`src/sandbox/local-sandbox.ts`). Образ-обёртка = `FROM sandbox-base` + `/opt/qm/agent.mjs` (`ensureLocalSandboxImage`). **LLM-цикл и MCP-вызовы идут из core**, не из песочницы |
| MCP | «connector на пользователя» | Реестр MCP **админский**: `PUT /v1/admin/mcp-servers/<id>` `{url, auth: none\|bearer\|client-credentials\|oauth-user, approval, catalog, credentialScope}` (`src/api/routes/admin/mcp-servers.ts`). Секреты лежат в core, в песочницы не попадают. Вызовы делает **core** (`src/tools/primitives.ts` → `createMcpClient`), поэтому MCP-хосты должны быть достижимы из ns `qm`, а не из сандбоксов |
| Авторизация MCP | «любые заголовки» | Поддерживается только `Authorization: Bearer` (`McpAuth`, `src/mcp/mcp-client.ts`). **`mon.` (Kuvasz) требует `X-API-KEY`** → нужен патч форка (§8.2) |
| Эмбеддинги | «OPENAI_BASE_URL и любой /embeddings» | Каталог эмбеддингов = *overlay-модели* (`kind: "embedding"`, `provider` строго `openai`, `src/model/model-overlay.ts`) + модели шлюза, обнаруженные по `mode === "embedding"` в `/models`. **Custom-provider эмбеддинги не умеет** (`src/model/custom-providers.ts` — только chat). GPUStack в `/v1/models` не отдаёт `mode` → путь один: overlay + `OPENAI_BASE_URL` на GPUStack (§7.4) |
| Модели | «id как у вендора» | Custom-provider модель живёт под **`custom/<provider>/<id>`** (`CUSTOM_MODEL_PREFIX`), и именно эта строка идёт в `base-model`/`webui-models`/повороты. Встроенного каталога deepseek в v0.1.17 нет |
| Org | «любое имя в UI» | `ORG_ID` (env core, `config.ts:210`), дефолт `default-org`. Переименование позже = пере-ключевание всех org-скоупов в БД, поэтому ставим `demo-lab` сразу |
| Флоу входа | «свой логин/пароль» | Встроенный брокер (magic-link, `/idp`) включается `auth.enabled=true`; для Keycloak — **`auth.enabled=false` + явные `OIDC_*`** (`plugins/portal/src/index.ts` читает `OIDC_ISSUER/…_AUTH_ENDPOINT/…_TOKEN_ENDPOINT/…_USERINFO_ENDPOINT/…_JWKS_URI/…_CLIENT_ID/…_CLIENT_SECRET/…_SCOPES/…_PRINCIPAL_CLAIM/…_ALLOWED_EMAIL_DOMAIN`). Redirect — **`${PUBLIC_WEB_URL}/auth/callback`** |
| Облачные песочницы | «нужно собирать шаблон» | E2B публикует готовый шаблон **`qm-sandbox:v1.0.0`** ([docs/e2b-template.md](https://github.com/msklv/qm/blob/v0.1.17-ai-lab/docs/e2b-template.md)) → облачный тест = ключ + `E2B_TEMPLATE_ID`, без сборки |

---

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образы | `ghcr.io/msklv/qm/core@sha256:1b7dcacb…` (243 MiB), `…/egress-proxy@sha256:b757dae3…` (387 MiB), `…/sandbox-base@sha256:4468eb19…` (886 MiB) | форк-тег **`v0.1.17-ai-lab`** (owner, 2026-11-11; run 43002212997 — success, 3 job'а). Дигайлы сверены 2026-11-12: совпадают с присланными; amd64, пакеты публичные. Тег двигаем **только** сменой дигайла в `gitops/values/qm.yaml` |
| Namespace | `qm` (создаётся каталогом `gitops/apps/qm/00-namespace.yaml`, sync-wave `-1`) | один ns на сервис (паттерн `her/`, `fc/`) |
| Размещение core | `nodeAffinity.preferred`: **k8s-05 → k8s-01**; `PriorityClass demo-stand-critical` | k8s-05 (14,8 GiB, занято 5,1 GiB / 33 %) — worker без GPU, рядом Firecrawl (потребитель §8.3), NVMe 1 ТБ; k8s-01 (32 GiB, 12,6 GiB / 53 %) — резерв. Пара 02/03 **не годится**: 70 %/67 % RAM, там ingress. k8s-04 — GPUStack, под на сцене не должен конкурировать с инференсом. Hard-`nodeSelector` не ставим (потеря узла = `Pending`) |
| Реплики core | **1**, `strategy: Recreate` | состояние в PG + `/data` (PVC RWO); HA не нужна, RTO = реаттач тома Longhorn (§10) |
| Ресурсы core | requests `500m`/`2Gi`, limits `2`/`4Gi` | чарт по умолчанию 1 Gi/2 Gi — мало: in-core теперь и web-UI, и портал, и цикл агента, и индексация памяти. Цифра предварительная, уточняется `kubectl top` в Q3 |
| Ресурсы egress-proxy | requests `100m`/`256Mi`, limits `512Mi`, **cap `NET_ADMIN`** | Envoy + authz; `NET_ADMIN` нужен для iptables-заглушки metadata-эндпоинта (`deploy/egress-proxy/start.sh`). Включается только вместе с песочницами (Q8) |
| PostgreSQL | свой StatefulSet в ns `qm`: `pgvector/pgvector:0.8.1-pg16@sha256:16e62164a405447dca191079a924ee5b8a9dbf04fe53128701ffbea857b37782` (amd64, 156 MiB), PVC **8 Gi** `longhorn` | `DATABASE_URL` обязателен; pgvector нужен для памяти; в URL — **суперпользователь** (миграция делает `CREATE EXTENSION vector`). Отдельный PG, не общий: qm мигрирует схему сам |
| Данные core | PVC **10 Gi** `longhorn`, `mountPath: /data` | `SNAPSHOT_STORE`/`TRANSFER_STORE` по умолчанию `local` → артефакты, шары сессий, вложения. S3 в кластере нет (`csi-s3` из GPUStack не переиспользуем) |
| Ingress | свой `Certificate qm-demo-tls` (ClusterIssuer **`letsencrypt-wildcard`**) + Ingress class `higress`, host `qm.demo-ai-lab.ru`, `/` → `service/qm-core:8000` | TLS-секрет читается только в ns Ingress'а (правило E-серии). Вход и API — с одного порта 8000; 8080 наружу не публикуется |
| Публичность | **сразу публичный, но только за SSO** (как `owu.`) | это пользовательский демо-сервис шага 4; вход ограничен Keycloak-realm `dev` + доменный гейт `demo-ai-lab.ru`. `lan-only-ui` не навешиваем; если до приёмки SSO нужно закрыть — временно тот же `WasmPlugin lan-only-ui` (снять в Q4) |
| Org | `ORG_ID=demo-lab` | решение владельца; `org:demo-lab` — id всех org-скоупов |
| Публичный URL | `publicUrl: https://qm.demo-ai-lab.ru` → core получает `PUBLIC_WEB_URL`, `AGENT_API_URL`, `PUBLIC_API_URL=http://qm-core:8080` | `PUBLIC_API_URL` — не косметика: без него агенты **не получают** инструменты `cron`/`webhook`/`share` и не работает self-service коннекторов (`coreToolOptions` в `src/harness/agent-tools.ts`) |
| Модели | два custom-provider'а: `gpustack` → `Qwen3.8-27B-UD`, `llm-svc` → `deepseek-flash` (§7) | обе — OpenAI-совместимые; встроенного каталога нет, ключи — в store core, не в env |
| Эмбеддинг | overlay-модель `bge-m3` + `memory-embedding-model=org:demo-lab` (§7.4) | 1024 измерения (проверено живым вызовом) |
| MCP | `docling`, `yandex-search`, `kuvasz` — по in-cluster DNS (§8) | из ns `qm` проверено: 200 / 200 / 401-по-дизайну |
| Песочницы | **решение владельца** — три варианта в §4 | внутри кластера сегодня нельзя без работы; §4.4 — рекомендация |
| Хостинг приложений qm | **не настраиваем** (`DEPLOY_PROVIDER` пуст) | «published apps» агентов — вне сцены; egress и домены приложений не нужны |
| Секреты | `scripts/qm_secrets.sh` → Secret `qm-runtime` (envFrom) + `qm-pg` (пароль БД) | §3; в `secretEnv` чарта значения **не** кладём (Helm хранит их в истории релиза) |

### 1.1 Пины (проверено в реестре 2026-11-12)

```bash
# анонимный токен + HEAD манифеста по тегу → docker-content-digest
for r in core egress-proxy sandbox-base; do
  T=$(curl -s "https://ghcr.io/token?scope=repository:msklv/qm/$r:pull" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
  curl -sI -H "Authorization: Bearer $T" \
    -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/msklv/qm/$r/manifests/v0.1.17-ai-lab" | grep -i docker-content-digest
done
```

| Сервис | Дигайл | Размер (сжатый) |
|---|---|---|
| `core` | `sha256:1b7dcacb6165adb53eec4839ccbb323ba6d4ff2ed51e74bb6b3f34a4dabba319` | 243 MiB |
| `egress-proxy` | `sha256:b757dae340e46a84770fe9e13938a9bf0d4dcc5541d4b8741419d806f54c51fc` | 387 MiB |
| `sandbox-base` | `sha256:4468eb19bef0f13d16f6f15ad42f0f63a08eeaac67610542667547550d87c2f5` | 886 MiB (браузер внутри) |

---

## 2. Предпосылки — проверено 2026-11-12

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get nodes -o custom-columns='NODE:.metadata.name,RAM:.status.allocatable.memory,CPU:.status.allocatable.cpu'
kubectl top nodes
kubectl get ns | grep -E '^(qm|pg)' || echo "ns qm отсутствует"
kubectl get certificate,ingress -A | grep qm || echo "маршрута qm нет"
```

| Что | Факт |
|---|---|
| Кластер | v1.35.9, containerd 2.2.1, Cilium (pod-CIDR `10.0.0.0/8`/24), Longhorn `longhorn` (r=2) default, ingressclass `higress`, VIP `.230` на 02/03 |
| RAM/CPU | k8s-01 32 GiB (53 %), k8s-02 14,8 (70 %), k8s-03 14,8 (67 %), k8s-04 28 GiB (60 %), **k8s-05 14,8 GiB (33 % — 10 GiB свободно)** |
| Хранилище | Longhorn: свободно 78 GiB (01) и 239 GiB (02) в пулах; занято 15 PVC (doc, fc, её 20Gi и т.д.) |
| ns `qm` | **отсутствует**; Ingress/Certificate `qm.` — нет (как и записано в `architecture/endpoints.md`) |
| ClusterIssuer | `letsencrypt-wildcard` (True, DNS-01), `letsencrypt-http01` (True, HTTP-01 — путь `her.`/`mon.`) |
| GPUStack (`api./v1/models`, ключ из `gpustack-admin.local.md`) | отдаёт **`bge-m3`, `bge-reranker-v2-m3`, `Qwen3.8-27B-UD`**; запущены только эмбеддинг и реранкер (поды `bge-m3-*`, `bge-reranker-*`), **27B остановлен** → для его ответа нужен кейс 01 (`cases/01-27b-one-card.md`) |
| `bge-m3` | `POST /v1/embeddings` → `dims 1024` (живой вызов) |
| `llm-svc.` | `GET /v1/models` с ключом: `deepseek-flash` (ctx **1 048 576**, max out 393 216, вход text+image), `deepseek-v4-pro`; без ключа — 401 |
| Keycloak | realm `dev`; клиент **`qm` ещё не заведён** (в `keycloak-clients.local.md` есть только `llm-qm` для шлюза); пользователи `admin-test@demo-ai-lab.ru` (роль `app-admin`), `user-test@…`, пул `devrel01…20` |
| MCP из LAN | `doc. /mcp` → 200, `ysrch. /mcp` → 200, `mon. /mcp` без ключа → 401, с `X-API-KEY` → 200, с `Bearer` → 401 |
| MCP из кластера (проверено из пода `her`) | `http://docling.doc.svc.cluster.local:8000/mcp` → 200, `http://yandex-search.ysrch.svc.cluster.local:8766/mcp` → 200, `http://kuvasz.monitoring.svc.cluster.local:8080/mcp` → 401 (по дизайну) |
| Firecrawl (`fc`) | 5 подов Running (45 ч), `firecrawl-api.fc.svc:3002`; `POST /v2/scrape {"url":"https://example.com"}` из пода → `success:true` + markdown; **Ingress и MCP-обёртки нет** (фаза C6 спеки `firecrawl-spec.md`) |
| Образы форка | доступны анонимно, дигайлы = §1.1 |

**Чего в предпосылках нет и это осознанно:** публичного IP и любых внешних адресов площадки (AGENTS.md), паролей
и ключей (они в `*.local.md`), адресов узлов вида `user@host`.

---

## 3. Секреты

| Файл (вне git, `*.local.md`) | Что внутри | Кто читает |
|---|---|---|
| `qm.local.md` | 5 секретов подписи/шифрования (`CORE_SIGNING_SECRET`, `CAPABILITY_SECRET`, `PORTAL_IDENTITY_SECRET`, `CONNECTOR_SECRET_KEY`, `SKILL_SIGNING_SECRET`), `PORTAL_SESSION_SECRET`, пароль `qm-postgres`, ключ GPUStack **`qm`** (allowed-models: `Qwen3.8-27B-UD`, `bge-m3`), статический ключ `llm-svc` (тот же, что у `owu`/`spk`) | `scripts/qm_secrets.sh` |
| `keycloak-clients.local.md` | `qm-client-secret` (появится в Q4) | `scripts/keycloak_seed.py`, `scripts/qm_secrets.sh` |

Правила:

- пять секретов — **уникальные**, `openssl rand -hex 32`; `CORE_SIGNING_SECRET`/`SKILL_SIGNING_SECRET`/`CONNECTOR_SECRET_KEY` ≥ 32 символов (иначе core не стартует, `isInvalidSecret`).
- в кластере: Secret **`qm-runtime`** (envFrom, создаётся `scripts/qm_secrets.sh qm`) и Secret **`qm-pg`** (пароль PG, монтируется в StatefulSet). В gitops — только ссылки на имена.
- в `deploy/helm/values.yaml` `secretEnv` **не заполняем**: Helm пишет эти значения в историю релиза. Все секреты — через `envFrom`.
- приёмка гигиены: `git ls-files | grep -E '\.local\.(md|pem)$|(^|/)\.env'` → пусто; сборка значений из `qm.local.md` и прогон по всем `git ls-files` → 0 хитов (шаг из `references/service-spec-authoring.md` §4).

---

## 4. Режим песочниц: контракт, варианты, рекомендация

### 4.1 Что QM требует от песочницы (контракт, не «примерно»)

`src/sandbox/sandbox.ts` + `exec-sandbox-base.ts`: exec с раздельными stdout/stderr/exit, файловые операции
(read/write/list/remove, каталоги), адресуемость из core, **сессии процессов**, home-снимки, teardown/park,
принудительный egress. Для `local` конкретно: core вызывает `docker run` (имя `qm-sbx-<scope>-<hash>`, сеть
`qm-net-<scope>…`), затем говорит с демоном **`http://<container>:8080`** (`coreContainer` задан) либо
`http://127.0.0.1:<порт>` (задан `-p 127.0.0.1:0:8080`). Перед первым стартом обязателен **образ-обёртка**
`qm-sandbox-local:latest` (или `LOCAL_SANDBOX_IMAGE`), иначе `local sandbox image … not found — build it`.

### 4.2 Инвентарь бэкендов v0.1.17 (`SANDBOX_BACKEND`, `src/sandbox/sandbox-settings.ts`)

| Бэкенд | Что нужно | Годится в контуре? |
|---|---|---|
| `local` | Docker-демон + CLI + образ-обёртка, **тот же демон, что у core** | да, если core рядом с демоном |
| `e2b` | `E2B_API_KEY` + шаблон (публичный `qm-sandbox:v1.0.0`) + публичный egress | только как тест: песочницы **вне** контура |
| `modal`, `sprites`, `agent37`, `superserve`, `smolmachines`, `render`, `porter`, `aws`, `do-managed-agents` | токены и аккаунты вендоров, egress | нет (санкций/бюджета нет, демо про «внутри стенда») |
| **`k8s`** | — | **отсутствует в коде**; добавление — §4.3 вариант C |

### 4.3 Варианты «песочницы рядом с кластером» (сравнение)

**A. Облако (E2B), как тест продукта.** `SANDBOX_BACKEND=e2b`, `E2B_TEMPLATE_ID=qm-sandbox:v1.0.0`,
ключ в Secret; шаблон готовый — собирать нечего. Плюсы: проверяем весь агентский цикл (exec/файлы/сессии) за
час-два, ноль нагрузки на стенд. Минусы: песочница (и данные, которые агент в неё кладёт) **уходит из контура** —
на сцене это противоречит смыслу показа «изолированный рантайм внутри стенда»; нужен публичный egress из пода
core; платно. **Куда:** только как сравнительный прогон до демо, «снять вопрос, что продукт работает».

**B. Docker на выделенной ноде + core с `hostNetwork`.** Ставим Docker на **k8s-05** (там же, где core),
монтируем `/var/run/docker.sock` в под core и даём `hostNetwork: true`; `SANDBOX_BACKEND=local`,
`QM_CORE_CONTAINER` **не** задаём (тогда `local` публикует `127.0.0.1:<random>` на ноде — а core в hostNetwork
этот loopback видит). Образ-обёртку собираем один раз на ноде из `sandbox-base@sha256:4468eb19…` + `agent.mjs`
(`cli/templates/aws/microvm-agent/agent.mjs`, ровно так, как это делает `ensureLocalSandboxImage`).
Плюсы: **без кода**, песочницы физически на стенде, весь набор инструментов уже в `sandbox-base` (браузер, node 24,
python 3.11). Минусы и они серьёзные: (1) `docker.sock` = root ноды для core — это уже не «агент в песочнице», а
«сервис с правами на ноду» (в публичной доке — только статус, детали в локальном отчёте ИБ, если понадобится);
(2) сандбоксы-контейнеры **не учитываются планировщиком** — по RAM/CPU они невидимы для kubelet, при
переполнении ноды OOM-killer убивает что попало (в т.ч. Firecrawl/Kuvasz); (3) один узел ⇒ нет переезда;
(4) под core в hostNetwork (`:8080`/`:8000` уходят в сеть ноды, DNS-политики кластера не действуют);
(5) при падении пода core контейнеры-сандбоксы остаются на ноде (мусор до `docker rm`). **Куда:** как быстрый
локальный компромисс на время показа, если песочницы нужны раньше, чем появится вариант C.

**C. Новый бэкенд `k8s` в форке (Pod = песочница).** Песочница = Pod с образом-обёрткой (`sandbox-base` +
`agent.mjs`, слушает 8080), core создаёт/удаляет Pod и говорит с ним **`http://<podIP>:8080`** — контракт тот же,
что у `local`, поэтому адаптер = клиент k8s API + exec/fs поверх HTTP-демона и переиспользование
`createExecSandboxBase`/`exec-file-ops`/`home-snapshot`. Точки касания (по reference `adding-a-sandbox-backend`
скилла `qm-development`): `sandbox-settings.ts` (union + `K8sSandboxEnv` + строка ошибки), `secret-schema.ts`
(union), `wiring.ts` (фабрика), `deploy/helm/values.yaml` + README чарта, [docs/deploy-directory.md](https://github.com/msklv/qm/blob/v0.1.17-ai-lab/docs/deploy-directory.md), тесты
(`test/config.test.ts` — на маппинг env→опции, не только на фабрику), RBAC (`ServiceAccount` + `Role`: pods,
pods/exec, PVC, events), `image` — новый артефакт сборки `ghcr.io/msklv/qm/sandbox-local` (Dockerfile в
`deploy/sandbox-local/`, добавить в матрицу `branch-images.yml`). Плюсы: сандбоксы **в кластере** — планировщик,
квоты, переезд подов, Longhorn для home-scope, никаких прав на ноду; egress-proxy остаётся единственной точкой
выхода. Минусы: это код (по объёму — как самый маленький существующий бэкенд `porter-sandbox.ts`, 454 строки,
плюс конфиг/тесты/RBAC), и он нужен **до** приёмки песочниц. **Куда:** целевой вариант.

**D. Docker-in-Docker в поде.** Отклонён: privileged-под, вложенный демон (overlay поверх overlay → `vfs`,
диск), образ песочницы (~0,9 ГБ сжатого / ~2,5 ГБ распакованного) внутри каждого пода, адресация снова по именам внутри dind. Сложность C без его
плюсов.

### 4.4 Рекомендация

| Этап | Что делаем | Зачем |
|---|---|---|
| 1 (сразу) | Q1–Q7: core + PG + SSO + org `demo-lab` + две модели + 3 MCP + `bge-m3`, **сандбоксы выключены** | агент при этом уже работает: модель, инструменты MCP, память и cron — всё в core; без сандбокса ход деградирует до текста (нет exec/файлов), но демо инструментов и моделей снимается |
| 2 (если песочницы нужны к дате) | **B** на k8s-05 (Docker + hostNetwork), решение владельца по риску `docker.sock` | день работы, локальные песочницы без кода |
| 3 (целевой) | **C**: бэкенд `k8s` в форке + образ `sandbox-local` + RBAC | песочницы внутри кластера штатно; после него B демонтируется (Docker с ноды снять) |
| вне сцены | **A** (E2B) как разовый сравнительный прогон, если надо доказать, что «работает не только у нас» | не тратим стендовую RAM, но данные уходят наружу — только тест |

Порядок «сначала C, потом сцена» даёт корректную картинку, но требует кода; порядок «B сегодня, C потом» даёт
демо раньше и сохраняет C как архитектурный финал. **A не заменяет ни то, ни другое** — это проверка продукта,
а не стенда.

---

## 5. Развёртывание

### 5.1 Состав каталога `gitops/apps/qm/`

| Файл | Что | sync-wave |
|---|---|---|
| `00-namespace.yaml` | Namespace `qm`, метка `app.kubernetes.io/part-of: demo-ai-lab` | −1 |
| `10-pg.yaml` | Secret `qm-pg` **не здесь** (создаётся скриптом), StatefulSet + Service `qm-pg`, PVC 8 Gi (через `volumeClaimTemplates`) | 0 |
| `20-core.yaml` | **рендер чарта** `deploy/helm` форка (`helm template qm … -f gitops/values/qm.yaml`) → Deployment/Service/PVC/Secret-ссылки. Правка только через рендер (`gitops/values/qm.yaml` + команда в `README.md`) | 1 |
| `25-egress.yaml` | Deployment + Service `qm-egress-proxy` (cap `NET_ADMIN`) — **включается в Q8** | 1 |
| `30-sandbox-rbac.yaml` | ServiceAccount + Role/RoleBinding для варианта C (pods, pods/exec, pvc) — Q8 | 1 |
| `40-ingress.yaml` | `Certificate qm-demo-tls` (wave 1) + Ingress → `qm-core:8000` (wave 2) | 1/2 |
| `README.md` | команда рендера, что нельзя править руками, как менять пин | — |

`gitops/values/qm.yaml` (эскиз, проверен `helm template` 2026-11-12 — рендерится без ошибок):

```yaml
publicUrl: https://qm.demo-ai-lab.ru
image: {repository: ghcr.io/msklv/qm, separator: "/", tag: ""}
auth: {enabled: false}                 # внешний IdP — Keycloak (§6)
ingress: {enabled: false}              # свой Ingress в 40-ingress.yaml
services:
  core:
    enabled: true
    imageRef: ghcr.io/msklv/qm/core@sha256:1b7dcacb6165adb53eec4839ccbb323ba6d4ff2ed51e74bb6b3f34a4dabba319
    replicas: 1
    persistence: {enabled: true, size: 10Gi, storageClass: longhorn}
    env:
      ORG_ID: demo-lab
      PUBLIC_API_URL: http://qm-core:8080
      NODE_ENV: production
      # OIDC_* — §6 (без них портал в production не пройдёт валидацию)
  egress-proxy:
    enabled: false                     # Q8
    imageRef: ghcr.io/msklv/qm/egress-proxy@sha256:b757dae340e46a84770fe9e13938a9bf0d4dcc5541d4b8741419d806f54c51fc
envFrom:
  - secretRef: {name: qm-runtime}
```

Что чарт делает сам (проверено рендером): имя релиза `qm` ⇒ сервис **`qm-core`**; `PORT=8080`, `PUBLIC_PORT=8000`,
`DATA_DIR=/data`, `PUBLIC_WEB_URL`/`AGENT_API_URL` = `publicUrl`; `auth.enabled=false` ⇒ **никаких** `AUTH_*`/`OIDC_*`
не подставляется (внешний IdP настраиваем явно).

### 5.2 Дельты форка, без которых спека не сходится

| # | Дельта | Зачем |
|---|---|---|
| **D-1** | `deploy/helm`: добавить `services.<name>.{nodeAffinity\|nodeSelector\|tolerations\|priorityClassName}` (4 ключа, ~15 строк в `deployment.yaml` + `values.yaml`) | сейчас чарт не умеет ни размещение, ни приоритет — иначе придётся править рендер руками, что ломает дисциплину «правка только через values» |
| **D-2** | `src/mcp/mcp-client.ts` + `mcp-server-store.ts` + admin-роут: необязательный **заголовок** для bearer (`bearerHeader ?? "authorization"`, значение по умолчанию — как сейчас) | Kuvasz (`mon.`) принимает только `X-API-KEY`; без этого «все три MCP» не выполняется (§8.2) |
| **D-3** | `deploy/sandbox-local/Dockerfile` (`FROM sandbox-base`, `COPY agent.mjs /opt/qm/agent.mjs`, `EXPOSE 8080`, `CMD node /opt/qm/agent.mjs`) + строка в матрице `branch-images.yml` | образ-обёртка для варианта B/C; сейчас форк собирает только `sandbox-base` (без демона) |
| **D-4** | бэкенд `k8s` (§4.3 C) | только для целевого режима песочниц |

Порядок: D-1/D-2 — одна сборка (`v0.1.18-ai-lab`), D-3 — к ней же, D-4 — отдельный тег.

### 5.3 PostgreSQL (фрагмент)

```yaml
# 10-pg.yaml — только то, что важно; остальное как в gitops/apps/fc/10-nuq-postgres.yaml
image: pgvector/pgvector:0.8.1-pg16@sha256:16e62164a405447dca191079a924ee5b8a9dbf04fe53128701ffbea857b37782
env:
  POSTGRES_DB: qm
  POSTGRES_USER: postgres          # миграции создают расширение vector → нужен суперпользователь
  POSTGRES_PASSWORD: {secretKeyRef: {name: qm-pg, key: password}}
volumeClaimTemplates: [{metadata: {name: data}, spec: {accessModes: [ReadWriteOnce], storageClassName: longhorn, resources: {requests: {storage: 8Gi}}}}]
```

`DATABASE_URL` в Secret `qm-runtime`: `postgres://postgres:<пароль>@qm-pg:5432/qm`.

---

## 6. SSO: домен `qm` в Keycloak

Клиент — **confidential, standard flow** (как `owu`/`spk`), redirect берём из кода, не угадываем:
`plugins/portal/src/index.ts:170` — `redirectUri = ${PUBLIC_WEB_URL}/auth/callback`.

| Параметр | Значение |
|---|---|
| clientId | `qm` |
| тип | confidential, standard flow (+ service accounts **не** нужны) |
| Valid redirect URIs | `https://qm.demo-ai-lab.ru/auth/callback` |
| Web origins / post logout | `https://qm.demo-ai-lab.ru` (+ `…/*` при желании) |
| секрет | `qm-client-secret` в `keycloak-clients.local.md` (скриптом, не руками в UI) |

Env, которые кладём в `services.core.env` (не секреты) и в Secret (секрет):

| Ключ | Значение |
|---|---|
| `OIDC_ISSUER` | `https://auth.demo-ai-lab.ru/realms/dev` |
| `OIDC_AUTH_ENDPOINT` | `https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/auth` |
| `OIDC_TOKEN_ENDPOINT` | `https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/token` |
| `OIDC_USERINFO_ENDPOINT` | `https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/userinfo` |
| `OIDC_JWKS_URI` | `https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/certs` |
| `OIDC_SCOPES` | `openid profile email` |
| `OIDC_PRINCIPAL_CLAIM` | `email` |
| `OIDC_ALLOWED_EMAIL_DOMAIN` | `demo-ai-lab.ru` (доменный гейт портала; обязателен в production) |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | `qm` / из `keycloak-clients.local.md` |
| `ADMIN_GRANTS` | `admin-test@demo-ai-lab.ru:org_admin` |
| `PORTAL_SESSION_SECRET` | из `qm.local.md` |

Важно: **backchannel должен ходить внутрь кластера.** Портал берёт токен по `OIDC_TOKEN_ENDPOINT` — тот же
внешний хост `auth.demo-ai-lab.ru`. Из ns `qm` он резолвится split-DNS'ом MikroTik: **A → `192.168.10.230`**,
а AAAA — `::1` (стендовая особенность, `architecture/endpoints.md`), поэтому клиент обязан откатиться на IPv4. Проверено
2026-11-12 из пода стенда: `getent ahostsv4 auth.demo-ai-lab.ru` → `.230`, `GET …/.well-known/openid-configuration`
→ **200**; `api.` и `llm-svc.` оттуда же → **401** (без ключа) — то есть все три хоста достижимы из кластера.
Если IPv6-предпочтение где-то всё же сорвёт обмен — заменяем `OIDC_TOKEN_ENDPOINT`/`OIDC_USERINFO_ENDPOINT`/
`OIDC_JWKS_URI` на внутренний адрес сервиса Keycloak (`http://keycloak.keycloak.svc:8080/realms/dev/…`), issuer
оставляем внешним (приёмка — Q4).

Админ-панель оператора — внутри core по `/settings` (портал требует `isAdmin` из `whoami`, грант — `ADMIN_GRANTS`).

---

## 7. Модели и эмбеддинги

### 7.1 Две модели как custom-provider'ы

`PUT /v1/admin/custom-providers/<slug>` (подписанный вызов + `x-admin-actor: admin-test@demo-ai-lab.ru`,
`x-portal-identity`); `validate:false` — чтобы регистрация не зависела от живости эндпоинта.

| Slug | baseUrl | protocol | models[] | Runtime id |
|---|---|---|---|---|
| `gpustack` | `https://api.demo-ai-lab.ru/v1` | `openai` | `[{id: "Qwen3.8-27B-UD", name: "Qwen3.8 27B (локальная, GPUStack)", contextWindow: 128000, maxTokens: 8192}]` | `custom/gpustack/Qwen3.8-27B-UD` |
| `llm-svc` | `https://llm-svc.demo-ai-lab.ru/v1` | `openai` | `[{id: "deepseek-flash", name: "DeepSeek V4.1 Flash (llm-svc)", contextWindow: 1048576, maxTokens: 32768}]` | `custom/llm-svc/deepseek-flash` |

Ключи: GPUStack — новый ключ **`qm`** (allowed-models: `Qwen3.8-27B-UD`, `bge-m3`; выдаётся в UI GPUStack,
значение — в `qm.local.md`); `llm-svc` — статический ключ стенда (тот же, что у `owu`/`spk`; `x-api-key` **или**
`Authorization: Bearer`, оба входа включены).

Дальше — durable-ресурсы org-скоупа (иначе web-поворот уйдёт на `claude-opus-5`/откажется «not enabled for web UI»):

```bash
PUT /v1/admin/scopes/org:demo-lab/base-model       {"modelId":"custom/llm-svc/deepseek-flash"}
PUT /v1/admin/scopes/org:demo-lab/webui-models     {"ids":["custom/llm-svc/deepseek-flash","custom/gpustack/Qwen3.8-27B-UD"]}
PUT /v1/admin/scopes/org:demo-lab/approved-harnesses {"ids":["pi","mock"]}
PUT /v1/admin/scopes/org:demo-lab/runtime          {"harnessId":"pi","modelId":"custom/llm-svc/deepseek-flash"}
```

**Две грабли, обе проверены на соседнем стенде:**

- `GET /v1/admin/model-providers` (его читает онбординг) строится **только** из встроенных провайдеров: custom-provider там никогда не станет `configured:true`, бейдж «Needs a key» — **ложный минус**. Проверять надо store (`hasKey`) и живой поворот, а не онбординг.
- Модель, чей id совпал со встроенной в новом `pi-ai`, резолвится в вендорский эндпоинт **раньше** custom-provider'а (в air-gap это «Connection error» без создания песочницы). В v0.1.17 встроенного `deepseek` нет, и `custom/…`-префикс снимает класс проблемы — но при обновлении тега перепроверяем `resolveModel` (Q-9).

### 7.2 Связка с кейсами (важно для сцены)

`Qwen3.8-27B-UD` живёт на единственном слоте 5070 Ti (`-np 1`) и **не уживается со стражем `llm-svc.`**:
в кейсе 01 внешний маршрут отдаёт `503` (страж снят, fail-closed) — это записано в `hermes-spec` §6 и R-H5.
Значит на сцене два режима, и переключаются они **вручную**, вместе с модельным набором кейса:

| Режим | `llm-svc.` (`deepseek-flash`) | `Qwen3.8-27B-UD` | Что показываем |
|---|---|---|---|
| «внешняя» (по умолчанию) | работает | `Stop` (нет ответа) | модель «снаружи» за шлюзом с DLP — основной сценарий |
| кейс 01 | `503` (страж снят) | работает | модель «внутри», на карте стенда |

org-`base-model` переключается тем же `PUT …/base-model`; веб-UI видит список из `webui-models` — то есть обе
модели и в обоих режимах, «сломана» будет только та, что снята.

### 7.3 Ограничения моделей

| Модель | Факт | Следствие |
|---|---|---|
| `deepseek-flash` | ctx 1 048 576, max out 393 216; вход text+image **на стороне провайдера** | длинные сессии не режутся контекстом. Картинку агент всё равно не получит: в v0.1.17 custom-модели объявлены **только текстовыми** (`toRuntimeModel` жёстко ставит `input: ["text"]`, а `input`/`output` в спеке — это цены за токен, не модальности). Vision — только у моделей со своим `input`-набором, т.е. вне custom-provider |
| `Qwen3.8-27B-UD` | 128K, один слот, decode ~81 tok/s на 4K и ~42 на 128K | долгий агентский цикл на 27B — плохая идея для сцены; короткий вопрос — хорошо |

### 7.4 Эмбеддинг `bge-m3` (семантическая память)

Путь единственный (см. §0): **overlay-модель эмбеддинга** + переопределение base URL OpenAI-провайдера.

1. `OPENAI_BASE_URL=https://api.demo-ai-lab.ru/v1` в `services.core.env`; `OPENAI_API_KEY` = ключ GPUStack `qm` (Secret).
   Следствие, которое надо принять осознанно: встроенные openai-модели (`gpt-*`) тоже пойдут на GPUStack и работать
   не будут — на стенде они не используются, но включать их «на всякий случай» нельзя.
2. `PUT /v1/admin/model-registry/bge-m3` `{"kind":"embedding","id":"bge-m3","name":"bge-m3 (GPUStack, 1024)","provider":"openai","verify":true}`
   — `verify` шлёт один (платный, но копеечный) запрос `/embeddings` ключом организации; без `verify:true` модель не включится.
3. `PUT /v1/admin/scopes/org:demo-lab/memory-embedding-model {"modelId":"bge-m3"}`.
4. Приёмка: таблица `memory_fact_vectors` в PG заполняется, `vector_dims(embedding) = 1024`; в логах core нет
   `Embedding request failed`. Проверка живая: `curl api./v1/embeddings -d '{"model":"bge-m3","input":["x"]}'` → 1024 (сделано).

Резервный путь (если `OPENAI_BASE_URL` окажется нежелательным): `MODEL_GATEWAY_URL/API_KEY/API_KEY_HEADER/MODELS` —
но тогда эмбеддинг будет виден только если GPUStack отдаст `mode:"embedding"` в `/models`; сейчас **не отдаёт**
(проверено), то есть путь этот не работает без правки GPUStack. Поэтому — overlay.

---

## 8. MCP и система извлечения данных

### 8.1 Три MCP-сервера стенда

Регистрация — админским `PUT /v1/admin/mcp-servers/<id>` (см. §0); URL — **внутренние DNS**, чтобы не зависеть
от Higress/edge и не платить TLS-хопом (проверено из пода `her` 2026-11-12).

| id | url | auth | approval | Что даёт | Приёмка |
|---|---|---|---|---|---|
| `docling` | `http://docling.doc.svc.cluster.local:8000/mcp` | `none` | `annotations` | разбор документов/OCR (`doc.`) | `GET /v1/admin/mcp-servers` → `tools[]` содержит инструменты docling; поворот «прогони документ» |
| `yandex-search` | `http://yandex-search.ysrch.svc.cluster.local:8766/mcp` | `none` | `annotations` | `web_search`, `gen_search`, `image_search`, … | инструмент `web_search` в `tool_search` и живой вызов |
| `kuvasz` | `http://kuvasz.monitoring.svc.cluster.local:8080/mcp` | `bearer` **`X-API-KEY`** (дельта **D-2**) | `annotations` | состояние мониторинга | ключ `admin-mcp-api-key` из `kuvasz.local.md`; `initialize` → 200 |

Замечания:

- `catalog: true` и `attestActor` **не включаем**: это для «каталога инструментов» и подписи актора; на демо достаточно прямого набора.
- `mon.` закрыт `lan-only-ui` (allowlist `10/8`), но core в кластере ходит с pod-IP `10.x` — allowlist пропускает; снаружи ключ бесполезен, и это правильно.
- секреты MCP (ключ Kuvasz) живут в core (`credentialScope: shared`) и в песочницы не попадают — так устроен store.

### 8.2 Дельта D-2 (иначе Kuvasz не подключить)

`McpAuth` умеет только `Authorization: Bearer` (проверено живым вызовом: `mon.` → 401 с Bearer, 200 с `X-API-KEY`).
Патч: в `McpServer` — необязательное `bearerHeader` (валидация: имя HTTP-заголовка, не из QM-контекста), в
`mcp-client.ts` — `{ [server.bearerHeader ?? "authorization"]: \`Bearer ${token}\` }`. Альтернатива без кода —
крошечный прокси (nginx/envoy-фильтр) перед `mon.`, который переписывает заголовок; выбираем патч: одна строка
контракта, ноль новых контейнеров.

### 8.3 «Система извлечения данных» — Firecrawl: статус и что делать

**Проверено 2026-11-12 (не по докам):** Firecrawl **развёрнут** — ns `fc`, 5 подов Running 45 ч,
`firecrawl-api.fc.svc:3002`, `POST /v2/scrape` из пода стенда → `success:true` + markdown. Чего **нет**: Ingress
(внешнего имени), MCP-обёртки и key-auth — то есть потребителя у него пока нет (это фаза C6 спеки
`firecrawl-spec.md`, и `qm` там назван первым потребителем).

Для qm нужен **MCP-интерфейс**, потому что инструменты агента подключаются только как MCP-серверы (своего
«http-fetch»-инструмента у core нет). Варианты:

| Вариант | Что делаем | Цена |
|---|---|---|
| **C6-min** (рекомендуем) | тонкий MCP-сервер `firecrawl` в ns `fc` (`/mcp`, 3 инструмента: `scrape`, `map`, `crawl`, проксирует `/v2/*` по ClusterIP) + регистрация в qm как 4-го сервера | один манифест + ~200 строк на Python/Node; вписывается в уже принятую фазу C6 |
| без C6 | в qm не подключаем, показываем извлечение через `her`/скрипты | на сцене «qm не умеет читать страницу» — минус к кейсу |
| прямой HTTP из core | патч форка: инструмент `fetch_url` в `src/tools` | дублирует C6, хуже для «каталога MCP» как истории |

Решение по умолчанию — **C6-min**, отдельной фазой Q9 (после песочниц, не блокирует Q1–Q7).

---

## 9. Фазы Q1–Q9

### Q1 — образы, предтяжка, «скелет»
Создать `gitops/apps/qm/{00-namespace.yaml,README.md}` и `gitops/values/qm.yaml`; прогнать пробный под на
k8s-05 с образом core по дигайлу.
**Приёмка:** `.status.containerStatuses[0].imageID` содержит `sha256:1b7dcacb…`; под удалён; ns `qm` в Argo (пустой набор манифестов допустим).

### Q2 — PostgreSQL
Secret `qm-pg` (`scripts/qm_secrets.sh`), StatefulSet + Service `qm-pg`, PVC 8 Gi.
**Приёмка:** `kubectl -n qm exec qm-pg-0 -- psql -U postgres -d qm -c 'select 1'` → 1; PVC Bound.

### Q3 — core
`helm template qm deploy/helm -n qm -f gitops/values/qm.yaml` → `20-core.yaml`, коммит, синк.
**Приёмка:** `kubectl -n qm port-forward svc/qm-core 8080` → `GET /healthz` 200, `/readyz` 200; публичный `:8000/` → 302/401 (страница входа, не 500); `kubectl -n qm exec deploy/qm-core -- env | grep -E 'PUBLIC_API_URL|ORG_ID'` → `http://qm-core:8080`, `demo-lab`;
в PG есть таблицы миграций; `select extversion from pg_extension where extname='vector'` → `0.8.x`.

### Q4 — SSO (Keycloak) и маршрут
Клиент `qm` (скриптом `scripts/keycloak_seed.py`), секрет → `keycloak-clients.local.md`; `OIDC_*`/`PORTAL_SESSION_SECRET` в Secret; `40-ingress.yaml` (Certificate + Ingress).
**Приёмка:** из LAN `curl -I https://qm.demo-ai-lab.ru/` → 302 на `/auth/login`; браузер: вход `admin-test` → возврат на `/auth/callback` → в UI; `admin-test` видит `/settings`, `user-test` — нет; снаружи (через edge) тот же цикл; `dig @192.168.10.1 qm.demo-ai-lab.ru` → `192.168.10.230`.

### Q5 — организация, две модели
`ORG_ID` уже в Q3. Регистрация двух provider'ов, `base-model`/`webui-models`/`approved-harnesses`/`runtime` (§7.1).
**Приёмка:** подписанный `POST /v1/turns` (surface `web`, актор `admin-test@…`) → 202, ответ модели в `session_entries`;
в `runs` модель = `custom/llm-svc/deepseek-flash`; в web-UI список моделей = 2; переключение на `custom/gpustack/Qwen3.8-27B-UD` в режиме кейса 01 → ответ локальной 27B (или внятная ошибка, если карта занята — тогда режим «внешняя»).

### Q6 — все три MCP
Дельты D-1/D-2 в форке → новая сборка `v0.1.18-ai-lab` → пин в `gitops/values/qm.yaml`; регистрация трёх серверов.
**Приёмка:** `GET /v1/admin/mcp-servers` → 3 сервера, `hasBearerToken: true` у `kuvasz`, `tools[]` непустой у всех;
поворот: «сколько хостов не в порядке?» (kuvasz), «найди в вебе X» (ysrch), «разбери этот документ» (docling) — три разных инструмента в одном ответе.

### Q7 — эмбеддинги `bge-m3`
`OPENAI_BASE_URL` + `OPENAI_API_KEY`, overlay `bge-m3`, `memory-embedding-model` (§7.4).
**Приёмка:** `select count(*), min(vector_dims(embedding)) from memory_fact_vectors` → >0 и 1024; память между двумя сессиями возвращает факт (запрос «что мы решили про X»).

### Q8 — песочницы (вариант из §4.4)
- **B:** Docker на k8s-05, образ-обёртка из `sandbox-base@sha256:4468eb19…`+`agent.mjs`, core `hostNetwork` + `hostPath /var/run/docker.sock`, `SANDBOX_BACKEND=local`, `LOCAL_SANDBOX_IMAGE=qm-sandbox-local:v0.1.17-ai-lab`.
  **Приёмка:** ход агента создаёт контейнер `qm-sbx-*`, `docker exec qm-core…`/`curl 127.0.0.1:<порт>/health` → `{"ok":true}`, агент пишет и читает файл; после перезапуска пода песочница подхватывается (`docker start`).
- **C:** бэкенд `k8s` + `25-egress.yaml` + `30-sandbox-rbac.yaml`; `SANDBOX_BACKEND=k8s`, `EGRESS_PROXY_URL=http://qm-egress-proxy:48080`.
  **Приёмка:** ход создаёт Pod `qm-sbx-*` с метками scope; `GET http://<podIP>:8080/health` из core-pod → ok; exec/файлы/сессии — по `npm run smoke`-аналогу; удаление scope удаляет Pod; egress-прокси видит трафик.
**Общая приёмка (оба):** повторный ход переиспользует песочницу; `docker rm -f`/`delete pod` — и следующая создаётся заново; квоты RAM песочницы (вариант C) видны в `kubectl top pod`.

### Q9 — извлечение данных, egress-гигиена, мониторинг
C6-min MCP Firecrawl (§8.3) + регистрация; Kuvasz-монитор на `https://qm.demo-ai-lab.ru/` (expect 302/401) и на `/settings` (LAN-гейт не нужен, но 401 без сессии — норма).
**Приёмка:** агент по «прочитай https://…» возвращает markdown Firecrawl; панель `mon.` показывает `qm.` зелёным; `python3 scripts/k8s_health.py --brief` — без новых WARN.

---

## 10. Операции

| Задача | Как |
|---|---|
| Обновление QM | новый тег форка → дигайлы в `gitops/values/qm.yaml` → рендер → коммит → синк Argo. Тег без дигайла не ставим |
| Изменение env | только через `gitops/values/qm.yaml` (env) или Secret `qm-runtime` (секреты) + рендер; правки живого Deployment Argo откатит |
| Переключение моделей на сцене | `PUT …/base-model` + `Stop/Start` в GPUStack UI по кейсу (`cases/README.md`); порядок — §7.2 |
| Ротация ключей | GPUStack UI → новый ключ `qm` → `qm.local.md`/Secret → рестарт core; ключ `llm-svc` — общий со `spk`/`owu`, менять синхронно (`llm-proxy-spec`) |
| Бэкап | `pg_dump -U postgres qm` из `qm-pg-0` + снапшот PVC `/data` (Longhorn) перед каждым апгрейдом; дампы вне репо |
| Пере-ключевание org | смена `ORG_ID` = SQL-пере-ключевание всех `org:`-скоупов (base_model, webui, skills, soul, security_postures, admin_grants, deployment_identity). Не делать «на лету» без брифа |
| Перезапуск core | `kubectl -n qm rollout restart deploy/qm-core`; сандбоксы (вариант B) живут отдельно, (C) — пересоздаются по требованию |
| Health | `scripts/k8s_health.py` (кластер) + `mon.` (HTTP/TLS); qm-специфичное — `/healthz` 200, `/readyz` 200, публичный `/` 302 на `/auth/login` |

---

## 11. Риски

| # | Риск | Что делаем |
|---|---|---|
| **R-Q1** | 27B и `llm-svc.` взаимоисключающие (страж снят в кейсе 01) | режимы §7.2, переключение вручную; на сцене не «фолбэк», а осознанный выбор кейса |
| **R-Q2** | Песочницы: `docker.sock` (B) = права на ноду; сандбоксы вне планировщика | вариант B — только с решения владельца и на выделенной ноде; целевой C (§4.3) |
| **R-Q3** | Кастомные образы форка — своя сборка, upstream-дрейф | пины по дигайлу, дельты D-1…D-4 перечислены и минимальны; апгрейд только тегом форка |
| **R-Q4** | pgvector/миграции требуют суперпользователя | отдельный PG в ns `qm`, `postgres` в URL; не переиспользовать общий кластер БД |
| **R-Q5** | Custom-provider не виден онбордингу («Needs a key») | не лечим UI-симптом, проверяем живым поворотом; при желании — патч `getModelProviders` (как на GNIVC) |
| **R-Q6** | `OPENAI_BASE_URL` переводит все openai-модели на GPUStack | на стенде openai-модели не используются; при появлении — отдельный провайдер/патч |
| **R-Q7** | Один экземпляр core → RTO 1–3 мин (реаттач PVC) | демо: под на k8s-05, `preferred`-affinity; при потере узла — `kubectl delete pod` после возврата |
| **R-Q8** | RAM k8s-05: core+PG+песочницы рядом с Firecrawl | лимиты 4 Gi у core, песочницы по 2 Gi и не больше 2–3 одновременно; при нехватке — core на k8s-01 |
| **R-Q9** | k8s-бэкенд (C) требует RBAC на pods/PVC в обход обычного GitOps-контура | именованный ServiceAccount `qm-sandbox` с Role в ns `qm`; ничего кластерного |
| **R-Q10** | Kuvasz-MCP на сцене малополезен и требует дельты D-2 | подключаем по решению; при отказе — «все три MCP» превращается в два |

---

## 12. Что забывают в таких спеках (закрыто здесь) и открытые вопросы

| Пункт | Где закрыт |
|---|---|
| Своя БД и путь миграции | §5.3 (свой PG + pgvector, миграции на старте core) |
| TLS в ns Ingress'а | §1 (свой `Certificate`, не wildcard из `demo-test`) |
| Backchannel для клиентов внутри кластера | §6 (внутренний адрес Keycloak — резервный путь в Q4) |
| Нет SMTP | §6: вход только через Keycloak, письма не нужны (брокер выключен) |
| Лимит LE 50/нед | один серт, без перевыпуска в цикле |
| NTP | стенд синхронизирован; JWT-расхождение ловится в Q4 |
| Redirect URI | взят из кода (`/auth/callback`), не угадан |
| PriorityClass и лимиты рядом с GPUStack | `demo-stand-critical`, core не на k8s-04 |
| Бэкап до апгрейда | §10 |

**Открытые вопросы (нужно решение владельца):**

1. **Режим песочниц** (§4.4): B (Docker на ноде, день) / C (бэкенд `k8s`, код) / только A как тест? От ответа зависит Q8 и D-3/D-4.
2. **Публичность**: публикуем `qm.` наружу сразу (как `owu.`) или сначала `lan-only-ui` до приёмки SSO?
3. **Kuvasz-MCP** на сцене нужен? Если нет — дельта D-2 откладывается, «3 MCP» становится 2.
4. **Firecrawl C6-min**: делаем в этой же итерации (Q9) или отдельной задачей после сцены?
5. **GPUStack-ключ `qm`**: allowed-models — только `Qwen3.8-27B-UD`+`bge-m3`, или добавить `gemma-4-12B` как третью (дешёвую) модель для массовых поворотов?

---

## 13. Связанные документы и история версий

- `architecture/specs/hermes-spec.md` — соседний агентский рантайм шага 4 (SSO, MCP, те же две модели) — прямые образцы узлов §6–§8.
- `architecture/specs/keycloak-spec.md` §5.3 — клиенты realm `dev`, скрипт `scripts/keycloak_seed.py`.
- `architecture/specs/llm-proxy-spec.md` — `llm-svc.` (статические ключи, `deepseek-flash`, DLP/страж), §3 — токены.
- `architecture/specs/gpustack-spec.md`, `gpustack-custom-backend-spec.md`, `cases/01-27b-one-card.md` — 27B: запуск/остановка, один слот, `bge-m3` на 780M.
- `architecture/specs/firecrawl-spec.md` — фаза C6 (MCP-обёртка) и потребители.
- `architecture/specs/doc-spec.md`, `ysearch-spec.md`, `monitoring-spec.md` — три MCP-сервера и их приёмки.
- `architecture/endpoints.md` — `qm.demo-ai-lab.ru` (план: шаг 4), правило TLS и публичности.
- `references/service-spec-authoring.md` — метод (живой замер → спека → регистрация без коммита).
- `cases/06-agents-sandbox.md` — кейс «агенты и песочницы» (сейчас: рантаймы `qm`/`her` не развёрнуты).

| Версия | Дата | Что |
|---|---|---|
| v1.0 | 2026-11-12 | первая спека: сверка исходников v0.1.17-ai-lab, пины по дигайлам, решение по SSO/org/моделям/MCP/эмбеддингу, разбор режима песочниц (4 варианта + рекомендация), фазы Q1–Q9, риски, открытые вопросы |
