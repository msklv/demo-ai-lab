# rag-spec — RAGFlow v1.0.0 (Go-сборка) на стенде: SSO нет (OSS), MCP встроенный, три модели, один узел

> **Версия:** v1.0 (2026-11-17) · **Статус:** **спека, не развёрнуто** — записи каталога MCP
> опубликована (`ru.demo-ai-lab/ragflow@1.0.0`, 2026-11-17), ns `rag` в кластере отсутствует.
> **Цель:** шаг 2 демо — RAGFlow (`rag.demo-ai-lab.ru`) как база знаний стенда: индексация документов
> **внутри** контура (векторный поиск и объекты — внутри RAGFlow, отдельных Qdrant/S3 нет — решение
> владельца 2026-11-17), эмбеддинги и реранк — **только наши** модели на 780M, генерация — локальная
> `Qwen3.8-27B-UD` через `api.` и внешняя `deepseek-flash` через `llm-svc.` (DLP + страж fail-closed),
> инструменты агентам — встроенный MCP.
> **Внешнее имя:** `rag.demo-ai-lab.ru` — Ingress Higress, TLS `letsencrypt-http01` (как `hm.`/`spk.`);
> до приёмки входа — LAN-only (`lan-only-ui`).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/rag/` (plain-манифесты, как `her/`, `doc/`);
> Secret'ы создаются **до** первого синка и в git не попадают.
> Креды — `ragflow.local.md` (в `.gitignore`): пароли `admin` и `data`, MySQL/MinIO/ES, ключи моделей.
> Ничего секретного в этом документе нет.

## 0. Что уточнила сверка с исходниками (2026-11-17)

Сверялись: `github.com/infiniflow/ragflow` — `docker/docker-compose.yml`, `docker/docker-compose-base.yml`,
`docker/.env`, `docker/entrypoint.sh`, `internal/server/config/stub.go`; релиз `v1.0.0` (2026-11-06) и
Docker Hub (`infiniflow/ragflow:v1.0.0`, amd64-дигест `sha256:206e3cdf760d7482cc881964b500ddda1541550877117ef4d737221ddddb6eea`,
344 MB); доки `ragflow.io/docs/use_ragflow_as_mcp_server`.

| Что | Ожидание «по аналогии» | Факт (проверено 2026-11-17) |
|---|---|---|
| Сборка | «python-сервер + отдельный MCP» | **Go-сервер в том же образе**: `bin/ragflow_server` с режимами `--api` (web+API), `--admin` (порт 9381), `--syncer`, `--ingestor` (воркер) — раскладку задаёт `entrypoint.sh` |
| SSO | «есть OIDC, как у OWU» | **В OSS-сборке OAuth/OIDC нет.** `internal/server/config/stub.go` (build tag `!ee`): «The OSS build has no OAuth login», `ParseOAuthConfig` — no-op. Логин только по паролю; SSO — в EE-сборке, её не берём |
| MCP | «отдельный контейнер/образ» | **Встроен в Go API**: `POST /api/v1/mcp` на 9380 (Streamable HTTP, авторизация per-client `Authorization`); опциональный отдельный listener `:9382` (`RAGFLOW_MCP_*`, режимы `host`/`self-host`) — **не включаем** |
| Кэш/очередь | «Redis/Valkey, как везде» | **Go-режим использует Kvrocks** (Redis-протокол, RocksDB) и **NATS**; Valkey в Go-развёртывании отключён |
| Векторный поиск | «отдельный Qdrant» | Движок внутри RAGFlow: `DOC_ENGINE` = **`elasticsearch` (дефолт upstream, 8.11.3)**; альтернативы `infinity` (`infiniflow/infinity:v0.7.5-x64-v3`), `opensearch`, `oceanbase`, `seekdb`, `gaussdb`, `vastbase` |
| Объекты | «отдельный S3» | **MinIO в составе стека** RAGFlow (`pgsty/silo RELEASE.2026-08-06`), отдельного сервиса нет |
| Ручки батчей | «настраивается как угодно» | `EMBEDDING_BATCH_SIZE` (дефолт **16**), `DOC_BULK_SIZE` (дефолт **4**), `RAGFLOW_INGESTOR_CONCURRENT_WORKERS` (дефолт **1**), `MAX_TASKS_PER_WORKER` |
| Метаданные | «Postgres» | `DB_TYPE` = `mysql` (дефолт, 8.0.40); поддерживаются postgres/gaussdb/oceanbase/vastbase |

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ | `infiniflow/ragflow:v1.0.0` (индекс) → amd64-манифест `sha256:206e3cdf760d7482cc881964b500ddda1541550877117ef4d737221ddddb6eea` | релиз 2026-11-06, пин по digest: тег двигается, стенд — нет |
| Namespace | `rag` | паттерн «один ns на сервис» (`her`, `doc`, `spk`) |
| Топология | **один Deployment `ragflow`**: `entrypoint.sh` под supervisor поднимает `--api` (+nginx, 80) и `--ingestor` (+`--syncer`) в одном поде — **строго upstream-путь** (решение владельца 2026-11-17) | одна точка правды и один образ; цена — рестарт пода останавливает и UI, и индексацию; HA нет (демо) |
| Размещение | **приоритет — k8s-05** (`preferred`, вес 100), допустимо k8s-01 | решение владельца; 05 — 30,5 GiB allocatable, без инференса и шлюза; при выносе 05 из работы поды `Pending`, а не уезжают на 03 |
| Ресурсы | **`ragflow` `500m/3Gi` → `2/6Gi`** (api + nginx + ingestor + ONNX DeepDoc в одном поде); ES `500m/1,5Gi` → `2/3Gi` (heap `-Xms1g -Xmx1g`); MySQL `100m/512Mi` → `1/1Gi`; MinIO `100m/256Mi` → `1/512Mi`; Kvrocks `100m/256Mi` → `1/512Mi`; NATS `50m/128Mi` → `500m/256Mi` | **предварительно**: ориентир вендора «16 GB min / 32 GB recommended» на весь стек; замер — фаза R2. Σ requests ≈ 1,85 CPU / 5,9 GiB |
| Хранилище | PVC Longhorn (r=2): ES **10Gi**, MySQL **5Gi**, MinIO **10Gi**, Kvrocks **2Gi**; модели DeepDoc — в образе | бэкапов и HA нет (демо): потеря тома = переиндексация, а не потеря данных стенда |
| Движок документов | **`DOC_ENGINE=elasticsearch`** — `elasticsearch:8.11.3` (решение владельца 2026-11-17: идём дефолтным путём upstream) | `DOC_ENGINE=${DOC_ENGINE:-elasticsearch}` в `.env` v1.0.0 и Quickstart: это штатная связка, обкатанная апстримом. Цена: JVM-heap (`ES_JAVA_OPTS=-Xms1g -Xmx1g`) и **host-sysctl `vm.max_map_count=262144`** на k8s-05. Infinity (`infiniflow/infinity:v0.7.5-x64-v3`) остаётся запасным вариантом одной строкой `DOC_ENGINE` |
| TLS/Ingress | один `Ingress` класс `higress`, host `rag.demo-ai-lab.ru`, `/` → сервис web (80); `Certificate rag-demo-tls`, ClusterIssuer `letsencrypt-http01` | правило E-серии; DNS-01 на стенде не работает |
| Публичность | **сначала только LAN** (`lan-only-ui`), наружу — после появления входа помимо пароля | SSO нет (см. §6), публичный RAGFlow без IdP — открытая база знаний и открытый OCR для всех |
| Авторизация | **пароль**: `admin` (bootstrap, `--init-superuser`) + пользователь **`data`**; сложные пароли генерируются и кладутся в `ragflow.local.md` | решение владельца; SSO в OSS-сборке отсутствует |
| MCP | встроенный `POST /api/v1/mcp` на 9380, запись каталога `ru.demo-ai-lab/ragflow@1.0.0` | §8; отдельный listener `:9382` не включаем |

### 1.1 Где мы отходим от upstream-дефолтов (и чем платим)

Сверено с `docker/docker-compose.yml`, `docker/docker-compose-base.yml`, `docker/.env` тега **v1.0.0**.

| Что | Upstream по умолчанию | У нас | Почему / цена |
|---|---|---|---|
| Admin-сервер | в compose — **закомментированный пример** (`--enable-adminserver --init-superuser`) | включён (порт 9381, только внутри кластера) | нужен bootstrap `admin`; цена — лишняя поверхность, вопрос Q-R3 |
| MCP | встроенный `POST /api/v1/mcp` + опциональный listener `:9382` (`RAGFLOW_MCP_ENABLED`) | только `/api/v1/mcp`; listener выключен | per-client `Authorization` вместо общей учётки режима `self-host` |
| Батч эмбеддинга | `EMBEDDING_BATCH_SIZE=16` | **8** | паритет с OWU (`owu-spec` §7.4), 780M держит; цена — индекс дольше в 1,5–2 раза |
| Опциональные профили compose | доступны: `sandbox-executor-manager`, `jaeger`, `tei-cpu`, `tei-gpu`, `kibana` | не включаем | демо-скоуп; телеметрия и sandbox-исполнитель не нужны |
| Публичность | как настроишь (`SVR_WEB_*`) | **LAN-only** (`lan-only-ui`) | SSO нет (§6); цена — снаружи база знаний недоступна |
| Носитель состояния | docker-тома, `MEM_LIMIT` | StatefulSet + PVC Longhorn, лимиты — `resources` | модель стенда (Argo, Longhorn), не отклонение продукта |

Совпадает с upstream (не отклонения): **процессы** — один под, `entrypoint.sh` под supervisor (`--api` + `--ingestor` + `--syncer`), `DOC_ENGINE=elasticsearch`, `DB_TYPE=mysql` (MySQL 8.0.40),
MinIO `pgsty/silo`, **Kvrocks** 2.16.0 и NATS 2.14.2 (это Go-стек RAGFlow, а не наша замена Redis),
`DOC_BULK_SIZE=4`, `RAGFLOW_INGESTOR_CONCURRENT_WORKERS=1`.

## 2. Предпосылки (проверить до R1)

| Что | Состояние | Проверка |
|---|---|---|
| Модели эмбеддинга/реранка | `bge-m3` (dim 1024) и `bge-reranker-v2-m3` — модели GPUStack на 780M k8s-01, `running` с 2026-11-03 | `POST https://api.demo-ai-lab.ru/v1/embeddings` и `/v1/rerank` из пода → 200 |
| Ключ GPUStack `rag` | **не выдан** | UI GPUStack → `API Keys`, allowed-models: `bge-m3`, `bge-reranker-v2-m3`, `Qwen3.8-27B-UD` |
| Внешняя модель | `llm-svc.` работает (статический ключ, DLP + страж fail-closed) | `POST /v1/chat/completions` → 200; без стража → `503 guard unavailable` |
| Локальная LLM | `Qwen3.8-27B-UD` — модель GPUStack, **резидентно не стоит** (набор переключается по кейсам, ADR-0007) | в кейсе 05 карта занята стражем `Qwen3Guard-Gen-4B` ≈12,7 GiB → 27B одновременно не влезает |
| `vm.max_map_count` на k8s-05 | **не выставлено** (требование ES) | `ansible pb-k8s-prep` / sysctl-файл: `vm.max_map_count=262144`, переживает ребут; без этого ES-под падает на старте |
| Узел 05 | 30,5 GiB allocatable, Firecrawl ≈5 GiB + Kuvasz/Postgres мониторинга ≈1 GiB | `kubectl describe node k8s-05` → Allocatable/Requests; замер после R2 |
| Каталог MCP | запись `ragflow@1.0.0` опубликована | `GET /v0/servers` → 4 записи |
| Qdrant, S3 | **не ставим** (решение 2026-11-17) | в спеке нет ни одного манифеста под них |

## 3. Секреты (`ragflow.local.md`, gitignored)

| Ключ | Куда идёт |
|---|---|
| `admin-password` (bootstrap, `--init-superuser`) | первый вход `admin@ragflow.io` → смена пароля в UI, значение — здесь |
| `data-password` | пользователь `data` (роль `user`), пул демо-учёток — отдельная строка |
| `mysql-root-password`, `mysql-password` | Secret `rag-db` |
| `minio-user`, `minio-password` | Secret `rag-objects` |
| `elastic-password` (ES; при фолбэке на infinity — `infinity-password`) | Secret `rag-docengine` |
| `kvrocks-password` | Secret `rag-cache` |
| `gpustack-api-key` (ключ `rag`) | Secret `rag-models` |
| `llm-svc-api-key` (общий статический ключ стенда) | Secret `rag-models` |

Правило: значения генерируются `openssl rand -hex 32` (или `-base64 24` там, где нужен символ-класс),
в git попадают **только имена**. Скрипт `scripts/rag_secrets.sh` (по образцу `her_secrets.sh`) создаёт
Secret'ы до первого синка Argo.

## 4. Лимиты эмбеддингов и реранка (как в OWU)

Ориентир — `owu-spec` §7.4: эмбеддинг батчем **8**, реранк батчем **8** пар «запрос/чанк» (замер bge-m3
на 780M: батч 8 ≈ 2,3k tok/s). В RAGFlow дефолты выше, поэтому ужимаем явно:

| Параметр | Значение | Почему |
|---|---|---|
| `EMBEDDING_BATCH_SIZE` | **8** (дефолт 16) | та же нагрузка на 780M, что у OWU; 16 даёт вдвое больший пик очереди без выигрыша в пропускной способности |
| `DOC_BULK_SIZE` | **4** | дефолт upstream; больше — очередь задач забивает единственный воркер |
| `RAGFLOW_INGESTOR_CONCURRENT_WORKERS` | **1** | один ингестор в поде (решение владельца); параллельность даёт только очередь |
| `MAX_TASKS_PER_WORKER` | **0** (не перезапускать) | один индекс-прогон за раз; рецикл не нужен, воркер не держит GPU |
| Таймаут запроса к моделям | `60 c` (эмбеддинг), `30 c` (реранк) | как у OWU; при таймауте — деградация до векторного поиска без реранка |
| Ключ GPUStack `rag` | allowed-models: `bge-m3`, `bge-reranker-v2-m3`, `Qwen3.8-27B-UD` | ключ не открывает остальные модели стенда |
| Внешняя генерация | через `llm-svc.` → `ai-token-ratelimit` по конsumer'у + DLP + страж | лимиты и защита — на шлюзе, а не в RAGFlow |

Проверка в R6: один документ 20–30 страниц индексируется за предсказуемое время, в логах видно
батчи по 8, GPUStack показывает рост GTT на 780M, наружу уходит только выбранный контекст.

## 5. Модели (провайдеры в RAGFlow)

| Роль | Модель | Куда | Как настраиваем |
|---|---|---|---|
| Embedding | `bge-m3` (dim 1024) | `https://api.demo-ai-lab.ru/v1` | провайдер «OpenAI-API-compatible», ключ GPUStack `rag` |
| Rerank | `bge-reranker-v2-m3` | `https://api.demo-ai-lab.ru/v1/rerank` | провайдер rerank того же семейства (схема vLLM: `results[].relevance_score`) |
| Chat локальный | `Qwen3.8-27B-UD` (128K) | `https://api.demo-ai-lab.ru/v1` | тот же провайдер; **включается только в кейсе 01** (карта свободна) |
| Chat внешний | `deepseek-flash` (128K) | `https://llm-svc.demo-ai-lab.ru/v1` | провайдер OpenAI-совместимый, ключ — статический ключ стенда; **обязательный страж** (иначе `503`) |

Ротация и правила — `llm-proxy-spec` (P1–P6) и `gpustack-spec` (G5). Ключи — только в Secret `rag-models`.

## 6. SSO: нет (обоснование)

Штатной реализации OIDC/Keycloak **в OSS-сборке нет** — `internal/server/config/stub.go` под тегом
`!ee` прямо говорит «The OSS build has no OAuth login», а `ParseOAuthConfig` возвращает `nil` без
чтения конфигурации. Поэтому:

- Keycloak-клиент `rag` **не заводим** (в `architecture/endpoints.md` строка помечена «SSO нет»);
- вход — логин/пароль (`admin`, `data`), пароли в `ragflow.local.md`;
- пока входа нет, сервис живёт в LAN-гейте (`lan-only-ui`), наружу не открывается;
- EE-сборку (где OAuth есть) не берём: закрытый артефакт вне контура.

Открытый вопрос Q-R1: нужен ли Keycloak перед `rag.` на шлюзе (OIDC-гейт, как у `dsh.` в ADR-0012) —
это отдельная работа, в эту спеку не входит.

## 7. Состав каталога `gitops/apps/rag/`

| Файл | Что | sync-wave |
|---|---|---|
| `00-namespace.yaml` | Namespace `rag` | −1 |
| `10-db.yaml` | StatefulSet + Service `mysql` (8.0.40), PVC 5Gi; Secret `rag-db` — скриптом | 0 |
| `12-docengine.yaml` | StatefulSet + Service `es01` (`elasticsearch:8.11.3`), `ES_JAVA_OPTS=-Xms1g -Xmx1g`, PVC 10Gi, security off (внутренний ns), пробы по `/_cluster/health` | 0 |
| `14-objects.yaml` | StatefulSet + Service `minio` (`pgsty/silo`), PVC 10Gi | 0 |
| `16-cache.yaml` | StatefulSet + Service `kvrocks` (2.16.0), PVC 2Gi | 0 |
| `18-bus.yaml` | Deployment + Service `nats` (2.14.2) | 0 |
| `20-ragflow.yaml` | Deployment `ragflow` (штатный `entrypoint.sh`: `--api` + `--ingestor` + `--syncer`), `args: [--enable-adminserver, --init-superuser]`, Service 80/9380/9381, `envFrom` Secret'ов | 1 |
| `40-ingress.yaml` | `Certificate rag-demo-tls` + Ingress `/` → `ragflow:80` (+ `lan-only-ui`) | 2 |

Порядок: Secret'ы → БД/движок/объекты/кэш/шина → web → worker → Ingress. `--init-superuser` живёт в
web-поде; повторный запуск безопасен (идемпотент).

## 8. MCP

- **Эндпоинт:** `POST /api/v1/mcp` на Go-API (9380), Streamable HTTP, авторизация per-client через
  `Authorization` (каждый клиент приносит свой RAGFlow-ключ).
- **Отдельный listener `:9382` не включаем** (`RAGFLOW_MCP_ENABLED` не задаём): он в режиме `self-host`
  работает под одной учёткой на всех — для стенда это хуже, чем per-client.
- **Каталог:** запись `ru.demo-ai-lab/ragflow@1.0.0` опубликована 2026-11-17,
  `remotes[0].url = https://rag.demo-ai-lab.ru/api/v1/mcp`; ответит после R1–R8.
- **Правило ADR-0012:** MCP смотрит только внутрь — маршрут `/api/v1/mcp` держим за LAN-гейтом,
  прямые вызовы агентов — по in-cluster DNS (`ragflow.rag.svc:9380`).
- Приёмка R8: `initialize` → `result.serverInfo`, `tools/list` непустой, вызов инструмента из пода
  `her` (Hermes) и `dsh` по внутреннему адресу.

## 9. Фазы R1–R9 (каждая — приёмка командами)

| # | Что | Приёмка |
|---|---|---|
| **R1** | `scripts/rag_secrets.sh` → Secret'ы; каталог `gitops/apps/rag/` в git; Application в Argo | `kubectl -n rag get secret` — все на месте; Argo Synced |
| **R2** | MySQL, Elasticsearch 8.11.3 (heap 1g), MinIO, PVC + `vm.max_map_count=262144` на 05 | поды Ready; `/_cluster/health` → `green`/`yellow`; `mysqladmin ping`; бакет RAGFlow создан; замер `kubectl top` → бюджет §1 уточнён |
| **R3** | Kvrocks + NATS | поды Ready; `redis-cli -h kvrocks ping` → PONG; NATS-монитор 200 |
| **R4** | под `ragflow`: `--api` + `--ingestor` + `--syncer` + admin (9381) | `GET /` → 200/302 на логин; `GET /api/v1/system/version` → `v1.0.0`; в логах видны все процессы; админ-порт отвечает |
| **R5** | индексация тем же подом (`--ingestor`, concurrency 1) | загрузка тестового PDF → задача `DONE`, чанки в движке (счётчик в UI); рестарт пода не оставляет зависших задач |
| **R6** | модели (§5) + лимиты (§4) | `/v1/embeddings` dim 1024 из пода; `/v1/rerank` 200; чат через `llm-svc.` с поднятым стражем; батчи 8 в логах |
| **R7** | пользователи `admin` и `data` | вход `data` → видит только свою базу; пароли в `ragflow.local.md`; тест «сложный пароль принят» |
| **R8** | MCP | §8 |
| **R9** | Ingress/TLS + LAN-гейт | `curl` через туннель → `403`; из LAN → 200; `Certificate` Ready |

## 10. Риски

| ID | Риск | Митигация |
|---|---|---|
| **R-R1** | Нет SSO (OSS): вход только паролем, аудита личности нет | LAN-гейт + пул учёток `data`; вопрос OIDC на шлюзе — Q-R1 |
| **R-R2** | Нет HA и бэкапов; **один под на все процессы** — рестарт/эвикция останавливает и UI, и индексацию | демо-скоуп; документы стенда лежат вне RAGFlow; задачи в очереди Kvrocks после рестарта добираются |
| **R-R3** | RAM на 05: Firecrawl + Kuvasz + RAGFlow-стек, ES держит JVM-heap | бюджет §1 предварительный, замер в R2; при нехватке — сначала heap `-Xmx1g`/лимиты, затем запасной `DOC_ENGINE=infinity` |
| **R-R7** | ES не стартует без `vm.max_map_count` | sysctl на 05 в R1 до первого синка; проверка `sysctl vm.max_map_count` |
| **R-R4** | 27B не влезает одновременно со стражем 12,7 GiB | в кейсе 05 основной — `deepseek-flash`; 27B — только когда карта свободна (кейс 01) |
| **R-R5** | Модели на 780M недоступны — эмбеддинг не считается | реранк отключается штатно (векторный поиск работает), эмбеддинг — блокер: проверка в §2 до R6 |
| **R-R6** | Запись каталога ссылается на `rag.`, а сервис LAN-only | по ADR-0012 так и надо: MCP только внутрь; снаружи запись не используется |

## 11. Связанные документы

- `architecture/specs/gpustack-spec.md` (G\*) — модели, ключи, 780M; `gpustack-custom-backend-spec.md` (B\*).
- `architecture/specs/llm-proxy-spec.md` (P\*) — `llm-svc.`, DLP, страж, лимиты; ADR-0008.
- `architecture/specs/keycloak-spec.md` (K\*) — IdP (RAGFlow вне SSO, §6).
- `architecture/specs/mcp-registry-spec.md` (M\*) — каталог и публикация; ADR-0005, ADR-0012.
- `architecture/specs/owu-spec.md` §7.4 — эталон настроек эмбеддинга/реранка на 780M.
- `architecture/endpoints.md` — адрес `rag.` и его статус; `cases/05-rag-embeddings-local.md`.

## 12. Открытые вопросы

| ID | Вопрос |
|---|---|
| **Q-R1** | Ставить ли OIDC-гейт перед `rag.` на шлюзе (как планируется для `dsh.`) — или остаётся пароль + LAN |
| **Q-R2** | Нужен ли второй пользователь пула (`data2`) для параллельного показа двум гостям |
| **Q-R3** | Оставляем ли `--enable-adminserver` (9381) на постоянной основе — он не публикуется, но расширяет поверхность |

## 13. История

| Версия | Дата | Что изменилось |
|---|---|---|
| v1.0 | 2026-11-17 | спека создана: RAGFlow v1.0.0 (Go), без SSO (OSS), встроенный MCP, **один под**: `--api` + `--ingestor` + `--syncer` под supervisor, **движок `elasticsearch` (дефолт upstream, 8.11.3)** — решения владельца 2026-11-17, MinIO внутри стека, модели `bge-m3`/`bge-reranker-v2-m3` (780M) + `Qwen3.8-27B-UD` + `deepseek-flash` через `llm-svc.`, пользователи `admin`/`data`, лимиты батчей как в OWU, размещение — k8s-05; §1.1 — перечень отклонений от upstream |
