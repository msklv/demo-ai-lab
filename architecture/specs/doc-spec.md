# Спецификация установки Docling Serve + Docling MCP (разбор документов, OCR)

> **Версия:** v1.2 (2026-10-28) · **Статус:** **развёрнуто 2026-10-28 (Argo CD, ns `doc`); D1, D2, D5
> сняты, русский OCR (D3) проверен с явным пресетом, MCP (D4) — только `initialize`; без пресета
> сервер идёт `auto` (RapidOCR `ch`) и кириллицу распознаёт плохо**
> **Цель:** шаг 2 демо — PDF/сканы → markdown/JSON с таблицами и текстом, **OCR на CPU** (GPU занят
> инференсом), и **MCP-сервер** над тем же движком: агенты шага 3 получают инструменты разбора
> документов нативно. Без авторизации (решение 2026-10-24), кириллица обязательна.
> **Внешнее имя:** `doc.demo-ai-lab.ru` — REST/UI на `/`, MCP на `/mcp` (LAN — split-DNS на `.230`,
> снаружи — Cloudflare Tunnel).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/doc` с plain-манифестами (официального
> Helm-чарта нет) + Job предзагрузки моделей в PVC.

Стиль-образцы: `architecture/specs/k8s-install-spec.md` (F\*), `architecture/specs/external-access-spec.md` (E\*),
`architecture/specs/keycloak-spec.md` (K\*), `architecture/specs/gpustack-spec.md` (G\*). Эта спека занимает букву **D**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ | `quay.io/docling-project/docling-serve-cpu:v1.38.2` — индекс `sha256:7a480a1604fa3b42efeddc7db9527690d9f9bc903226136013e2bfe6b1a4dfb0`, amd64-манифест `sha256:7b31b3c2efa17534dfcffb61665b71bbc959ad309b5b7ed82c3bbdcc63cc3d58`, pull **2218 MiB** compressed | `skopeo inspect --raw` (2026-10-28); `-cpu` без CUDA-библиотек (torch CPU-индекс), вдвое меньше качать, чем base 5043 MiB. Тег строго с префиксом `v` — `1.38.2` не существует |
| Namespace | `doc` (создаёт ApplicationSet `apps`) | изоляция, TLS-секрет в своём ns |
| Контейнеры | **2 в одном поде**, оба из этого образа: `docling-serve` (REST + UI + движок, порт **5001**) и `docling-mcp` (**MCP**, порт **8000**) | с v1.1.0 в образе лежит исполняемый `docling-mcp-server` (`docs/mcp.md`, extra `docling-mcp>=1.0.0` в `pyproject.toml`) — второй образ не нужен, MCP включается сменой entrypoint |
| MCP-режим | `DOCLING_MCP_CONVERSION_MODE=remote` → MCP конвертирует **через наш же REST** (`DOCLING_MCP_SERVICE_URL=http://127.0.0.1:5001`, loopback внутри пода) | в `local`-режиме MCP-процесс грузит **свои** модели docling: второй комплект в RAM и вторые OCR-настройки; в `remote` он тонкий адаптер, модель и русский OCR живут в одном месте |
| MCP транспорт | `docling-mcp-server --transport streamable-http --port 8000 --host 0.0.0.0`, эндпоинт `POST /mcp` | «containers setup» — штатный вариант из README `docling-mcp`; `stdio`/`sse` для кластерного сервиса не годятся |
| MCP инструменты | категории conversion (PDF/URL → `DoclingDocument`) + generation/manipulation (создать/дополнить документ, экспорт в md/json/html/doctags); точные имена — `tools/list` в D4 | README `docling-mcp`; VLM-инструменты (`DO_PICTURE_DESCRIPTION`) **выключены** — VLM-модели в бюджете GPU нет |
| MCP память/таймауты | `DOCLING_MCP_CACHE_MAX_DOCUMENTS=10` (дефолт), `DOCLING_MCP_SERVICE_TIMEOUT=1800`, `DOCLING_MCP_FALLBACK_TO_LOCAL=false` | дефолтные 300 с малы для скана на CPU; fallback в локальный режим подтянул бы второй комплект моделей — запрещён |
| MCP-вывод | `DOCLING_MCP_IMAGE_EXPORT_MODE=placeholder`, `DOCLING_MCP_KEEP_IMAGES=false` | `embedded` (base64) раздувает ответ в разы; картинки в демо не нужны |
| Реплики | **1** (под с двумя контейнерами) | движок `local`: реестр задач в памяти процесса → `poll`/`result` обязаны попадать в тот же под; >1 реплика требует `ENG_KIND=rq` + Redis |
| Состояние | PVC **10Gi** `longhorn` RWX/RWO → `/modelcache`, `DOCLING_SERVE_ARTIFACTS_PATH=/modelcache`; предзагрузка Job'ом | в образе модели **запечены** (`layout tableformer picture_classifier rapidocr easyocr`), но русского OCR в них нет; **пустой PVC поверх baked-пути затирает модели** — поэтому свой путь + Job |
| Модели (prefetch) | `layout`, `tableformer`, `picture_classifier`, `rapidocr` (backend-lang `onnxruntime:eslav` — кириллица), `easyocr`, плюс `rus.traineddata` в tessdata | RapidOCR мапит `ru-Cyrl→eslav` (PP-OCRv5 East Slavic), модели `eslav` в образ не входят; в образе только `tesseract-langpack-eng` |
| OCR по умолчанию | `DOCLING_SERVE_DEFAULT_OCR_KIND=tesserocr`, `DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG=true` + `CUSTOM_OCR_PRESETS` c `lang:["ru","en"]`; `rapidocr` остаётся вторым пресетом | Tesseract умеет `rus+eng` в одном прогоне, RapidOCR — только один язык за прогон; для смешанных бумаг нужен Tesseract. MCP-путь использует те же дефолты сервиса |
| GPU | `DOCLING_DEVICE=cpu`, `DOCLING_NUM_THREADS=4`, `nvidia.com/gpu` не запрашиваем | VRAM 5060 Ti занята (14 979 из 16 311 MiB), 780M — под страж/эмбеддинги (ADR-0007) |
| Воркеры | `DOCLING_SERVE_ENG_LOC_NUM_WORKERS=1`, `DOCLING_SERVE_OPTIONS_CACHE_SIZE=1`, `SHARE_MODELS=false` | модели дублируются на каждый воркер-поток → RAM ×N; на 02 свободно ≈8,6 GiB |
| Лимиты задач | `MAX_SYNC_WAIT=120` (дефолт) — длинный разбор только через `/async`; `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT=1800`; `MAX_FILE_SIZE=50MB`, `MAX_NUM_PAGES=200` | дефолты `MAX_FILE_SIZE`/`MAX_NUM_PAGES` = `sys.maxsize` (без лимита), `MAX_DOCUMENT_TIMEOUT` = 7 дней (задача-зомби) |
| Результаты | `SINGLE_USE_RESULTS=true`, `RESULT_REMOVAL_DELAY=300` оставляем дефолтом | результат одноразовый: клиенту сохранять сразу; у MCP свой LRU-кэш на 10 документов |
| Авторизация | **нет** ни у REST, ни у MCP (`DOCLING_SERVE_API_KEY` не задаём; у `docling-mcp-server` своей авторизации нет) | решение 2026-10-24: `doc.*` публичный; закрытие — плагинами Higress (`key-auth`, `limit-count`), не Keycloak. Риски R-D5/R-D11 |
| Ingress | один `Ingress` класс `higress` + `Certificate doc-demo-tls`; **`/mcp` → порт 8000**, `/` → порт 5001; таймауты на разбор | MCP-клиенты ходят на `/mcp`, REST и UI — на корень; правило E-серии (TLS в ns ингресса) |
| UI | `DOCLING_SERVE_ENABLE_UI=true` (`/ui`) | playground = «загрузил PDF — увидел markdown» |
| Пробы | REST: `startupProbe` `/health` (30×10 c), `readinessProbe` `/ready`, `livenessProbe` `/livez`; MCP: `tcpSocket: 8000` (HTTP-health у сервера нет) | семантика `/ready` — 503 пока модели не загружены (`app.py`) |
| Ресурсы | под целиком: requests `1/2Gi`, limits `4/8Gi` (REST — основная доля, MCP в `remote`-режиме — сотни МБ) | официальный манифест даёт 250m/1Gi + 1/4Gi для GPU-варианта; для CPU-OCR цифр в доках нет — ориентир, уточняется замером в D2 |
| Размещение | `nodeAffinity.preferred` → `demo-ai-lab/role=ingress` (02/03) | k8s-04 занят инференсом; k8s-01 — резерв под спайки |
| Секреты | нет: MCP↔REST по loopback, `DOCLING_MCP_SERVICE_API_KEY` не нужен, т.к. у REST нет ключа | сервис без авторизации и без внешних кредов |

## 2. Предпосылки — проверено 2026-10-28

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass; kubectl top nodes
dig +short @192.168.10.1 doc.demo-ai-lab.ru
skopeo inspect --raw docker://quay.io/docling-project/docling-serve-cpu:v1.38.2 | head -20
```

| Факт | Значение (замер) |
|---|---|
| StorageClass / Ingress | `longhorn` default (Longhorn 02/03 ≈ 244 GiB свободно); `higress`, VIP `.230` |
| Ноды | 02 — 14,8 GiB RAM / 12 CPU, занято 6287 Mi → **свободно ≈8,6 GiB**; метка `demo-ai-lab/role=ingress` |
| DNS | `doc.demo-ai-lab.ru`: LAN → `192.168.10.230`, снаружи → anycast Cloudflare (отдельная запись не нужна) |
| Образ | `-cpu` 2218 MiB pull (amd64), uid `1001`, `TESSDATA_PREFIX=/usr/share/tesseract/tessdata/`; `latest` == `v1.38.2` на 2026-10-28 |
| Модели в образе | `layout tableformer picture_classifier rapidocr easyocr` (скачаны на сборке) — **`eslav`/`rus` отсутствуют** |
| MCP в образе | `docs/mcp.md`: MCP с v1.1.0, исполняемый `docling-mcp-server`, флаги `--transport streamable-http --port <p> --host <h>`, эндпоинт `/mcp`; зависимость — extra `docling-mcp>=1.0.0`. **Наличие бинаря именно в `-cpu`-варианте проверяется в D2** (`which docling-mcp-server`) |
| MCP-режимы | `DOCLING_MCP_CONVERSION_MODE=remote` + `DOCLING_MCP_SERVICE_URL` (тонкий адаптер) либо `local` (свои модели); `DOCLING_MCP_FALLBACK_TO_LOCAL=false` по умолчанию |
| Чарт | официального нет (`docling-project/docling-serve-chart` → 404), есть `docs/deploy-examples/*.yaml`; сторонний `upstreamyard/docling-serve` — только референс |
| GPU | 5060 Ti: 14 979 из 16 311 MiB занято (чат + ASR) — GPU этому сервису не выделяем |

## 3. Секреты

Своих секретов нет: ни REST, ни MCP не имеют авторизации, внешних кредов не требуется (модели — из
образа/PVC, LLM не вызывается). В `gitops/apps/doc` паролей, токенов и ключей не появляется.

Если позже решим закрыть доступ: `DOCLING_SERVE_API_KEY` → `Secret doc-api-key` (вне git) + `X-Api-Key`
у клиентов и `DOCLING_MCP_SERVICE_API_KEY` для связки MCP→REST; либо `key-auth` в Higress на `/` и
`/mcp`. Оба варианта — отдельной правкой.

## 4. Развёртывание

Состав `gitops/apps/doc/`:

| Файл | Что | Sync-wave |
|---|---|---|
| `10-pvc.yaml` | `PersistentVolumeClaim modelcache` 10Gi `longhorn` | 0 |
| `20-prefetch-job.yaml` | `Job docling-model-cache-load`: `docling-tools models download -o /modelcache layout tableformer picture_classifier rapidocr easyocr` + `--rapidocr-backend-lang onnxruntime:eslav` + `rus.traineddata` | **-1** (до деплоя) |
| `30-deployment.yaml` | `Deployment docling` (replicas 1) с двумя контейнерами, пробы, ресурсы, том `/modelcache` | 0 |
| `40-service.yaml` | `Service docling` → 5001 (`http`) и 8000 (`mcp`) | 0 |
| `50-ingress.yaml` | `Certificate doc-demo-tls` + `Ingress`: `/mcp` → 8000, `/` → 5001 | 0 |

Ключевые фрагменты:

```yaml
spec:
  containers:
    - name: docling-serve                       # REST + UI + движок конвертации
      image: quay.io/docling-project/docling-serve-cpu:v1.38.2
      ports: [{ containerPort: 5001, name: http }]
      env:
        - { name: DOCLING_SERVE_ARTIFACTS_PATH,          value: /modelcache }
        - { name: DOCLING_DEVICE,                        value: cpu }
        - { name: DOCLING_NUM_THREADS,                   value: "4" }
        - { name: DOCLING_SERVE_ENG_KIND,                value: local }
        - { name: DOCLING_SERVE_ENG_LOC_NUM_WORKERS,     value: "1" }
        - { name: DOCLING_SERVE_OPTIONS_CACHE_SIZE,      value: "1" }
        - { name: DOCLING_SERVE_LOAD_MODELS_AT_BOOT,     value: "true" }
        - { name: DOCLING_SERVE_ENABLE_UI,               value: "true" }
        - { name: DOCLING_SERVE_DEFAULT_OCR_KIND,        value: tesserocr }
        - { name: DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG, value: "true" }
        - { name: DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT,    value: "1800" }
        - { name: DOCLING_SERVE_MAX_FILE_SIZE,           value: "52428800" }
        - { name: DOCLING_SERVE_MAX_NUM_PAGES,           value: "200" }
      volumeMounts: [{ name: modelcache, mountPath: /modelcache }]
      startupProbe:   { httpGet: { path: /health, port: http }, periodSeconds: 10, failureThreshold: 30 }
      readinessProbe: { httpGet: { path: /ready,  port: http }, periodSeconds: 10 }
      livenessProbe:  { httpGet: { path: /livez,  port: http }, periodSeconds: 20, failureThreshold: 5 }
    - name: docling-mcp                          # MCP-сервер, тонкий адаптер над REST
      image: quay.io/docling-project/docling-serve-cpu:v1.38.2
      command: ["docling-mcp-server"]
      args: ["--transport", "streamable-http", "--port", "8000", "--host", "0.0.0.0"]
      ports: [{ containerPort: 8000, name: mcp }]
      env:
        - { name: DOCLING_MCP_CONVERSION_MODE,        value: remote }
        - { name: DOCLING_MCP_SERVICE_URL,            value: "http://127.0.0.1:5001" }
        - { name: DOCLING_MCP_SERVICE_TIMEOUT,        value: "1800" }
        - { name: DOCLING_MCP_FALLBACK_TO_LOCAL,      value: "false" }
        - { name: DOCLING_MCP_CACHE_MAX_DOCUMENTS,    value: "10" }
        - { name: DOCLING_MCP_DO_OCR,                 value: "true" }
        - { name: DOCLING_MCP_DO_TABLE_STRUCTURE,     value: "true" }
        - { name: DOCLING_MCP_DO_PICTURE_DESCRIPTION, value: "false" }
        - { name: DOCLING_MCP_IMAGE_EXPORT_MODE,      value: placeholder }
        - { name: DOCLING_MCP_KEEP_IMAGES,            value: "false" }
      livenessProbe:  { tcpSocket: { port: mcp }, initialDelaySeconds: 20, periodSeconds: 20 }
      readinessProbe: { tcpSocket: { port: mcp }, initialDelaySeconds: 5,  periodSeconds: 10 }
```

- **Почему MCP-контейнер из того же образа**: `docling-mcp-server` уже внутри; отдельный pull не нужен,
  а оба контейнера в одном поде видят друг друга по `127.0.0.1` — трафик MCP→REST не выходит из пода.
- **Почему `remote`**: в `local`-режиме MCP грузит собственные модели docling и имеет собственные
  OCR-настройки — модель, CPU-OCR и русский язык должны быть в одном месте (REST-контейнер).
- **Кэш моделей**: пустой PVC, смонтированный на baked-путь (`/opt/app-root/src/.cache/docling/models`),
  затирает встроенные модели — поэтому путь `/modelcache` и обязательный Job; автодокачки в рантайме нет
  («missing models → runtime error»), кроме случая `ARTIFACTS_PATH=""` (тогда качает всё при старте — на
  канале 2–5 МБ/с это недопустимо).
- **Языки OCR**: дефолт RapidOCR — `ch`, Tesseract — `eng/spa/fra/deu`; русский появится только с
  `eslav`-моделями и/или `rus.traineddata` (`tessdata_best`). Пресет задаётся на запрос
  (`ocr_preset`, `ocr_lang`, `ocr_custom_config`) либо админ-дефолтом; MCP-путь наследует дефолты.
- **Stateless нет**: при `ENG_KIND=local` `GET /v1/result/{id}` живёт в памяти пода; при рестарте
  незабранный результат теряется (он и так одноразовый).

## 5. Конфигурация домена и контракты

Домен/auth не нужны: авторизации нет, Keycloak-клиента нет, ролей нет. Контракты — два на одном хосте:

| Что | Как |
|---|---|
| REST синхронно | `POST /v1/convert/file` (multipart) или `/v1/convert/source` (JSON) → `md_content` |
| REST длинный разбор | `POST /v1/convert/file/async` → `task_id` → `GET /v1/status/poll/{id}` → `GET /v1/result/{id}` |
| Возможности | `GET /v1/capabilities` (без ключа) — какие пресеты/лимиты доступны |
| Playground | `https://doc.demo-ai-lab.ru/ui` |
| **MCP** | `POST https://doc.demo-ai-lab.ru/mcp` — JSON-RPC (`initialize`, `tools/list`, `tools/call`), транспорт `streamable-http` |
| MCP-инструменты | конвертация PDF/URL → `DoclingDocument`; генерация/правка документа; экспорт в md/json/html/doctags. Точный состав — `tools/list` (фаза D4) |

Клиентская конфигурация для агентов шага 3:

```json
{ "mcpServers": { "docling": { "url": "https://doc.demo-ai-lab.ru/mcp" } } }
```

## 6. Фазы и приёмка

### D1. Кэш моделей (PVC + Job)

```bash
kubectl -n doc get pvc,job
kubectl -n doc logs job/docling-model-cache-load | tail -5
kubectl -n doc exec deploy/docling -c docling-serve -- du -sh /modelcache
```
Приёмка: Job `Complete`, в `/modelcache` есть каталоги layout/tableformer/figure-classifier/rapidocr
(`eslav`) и `tessdata/rus.traineddata`; размер каталога фиксируется в §10.

### D2. Установка, MCP-бинарь и ресурсы

```bash
kubectl -n doc get pods,pvc,svc
kubectl -n doc rollout status deploy/docling --timeout=600s
kubectl -n doc exec deploy/docling -c docling-mcp -- which docling-mcp-server
kubectl -n doc logs deploy/docling -c docling-mcp | tail -5
kubectl -n doc top pod --containers
```
Приёмка: под `2/2`, REST `/health` 200 и `/ready` 200 (`503` до загрузки моделей — норма), MCP слушает
8000 и в логе `streamable-http`; фактический RSS по контейнерам — в §10. **Если `docling-mcp-server` в
`-cpu`-варианте отсутствует** — MCP берём из base-образа или из образа `docling-mcp` (плюс pull),
факт и выбор пишем в §10 (риск R-D10).

### D3. Русский OCR (ядро приёмки)

Разбор русского скана (договор/справка, 2–5 страниц) и смешанного рус+англ:
`ocr_preset: tesserocr`, `ocr_lang: ["ru","en"]`; повторно — `rapidocr` с `eslav`.
Приёмка: в `md_content` распознан кириллический текст (не «кракозябры»/латиница), таблицы не рассыпались;
для двух пресетов фиксируется качество и время — выбирается дефолт в `CUSTOM_OCR_PRESETS`.

### D4. MCP-режим

```bash
# 1) initialize
curl -s -X POST --resolve doc.demo-ai-lab.ru:443:192.168.10.230 \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  https://doc.demo-ai-lab.ru/mcp
# 2) tools/list, затем tools/call с тем же русским PDF
```
Приёмка: `initialize` → 200 и `serverInfo`; `tools/list` содержит инструменты конвертации/генерации;
`tools/call` на русском PDF возвращает markdown (или целевой формат) с кириллицей; в логе MCP-контейнера
виден запрос к `127.0.0.1:5001`; повторная конвертация того же файла переиспользует кэш документов (замер).

### D5. REST и публикация

```bash
curl -s -o /dev/null -w '%{http_code}\n' --resolve doc.demo-ai-lab.ru:443:192.168.10.230 https://doc.demo-ai-lab.ru/health
curl -s --resolve doc.demo-ai-lab.ru:443:192.168.10.230 https://doc.demo-ai-lab.ru/v1/capabilities | head -c 300
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 https://doc.demo-ai-lab.ru/health    # снаружи
```
Приёмка: LAN и edge `200`; async-путь на 20-страничном PDF доходит до `success`; синхронный вызов на
большом файле корректно упирается в `MAX_SYNC_WAIT` (не в таймаут ингресса); серт `CN=doc.demo-ai-lab.ru`;
`/mcp` снаружи отвечает на `initialize` (edge не режет стриминг — проверять с `accept: text/event-stream`).

### D6. Ограничения публичного доступа

Два параллельных разбора + вызов MCP-инструмента одновременно: под не падает в OOM, отказы идут как
`503/429`. Проверить лимит размера тела на ингрессе и (если включаем) `limit-count` на `/mcp`.

## 7. Операции

| Задача | Как |
|---|---|
| Health | REST `/health`, `/ready`, `/livez`; MCP — TCP 8000 и `tools/list`; `scripts/k8s_health.py --brief` |
| Бэкап | данные не хранятся: бэкапить нечего, кроме `/modelcache` (восстанавливается Job'ом) |
| Апгрейд | новый тег `-cpu` в манифесте → `Sync`; прогреть образ (2,2 GiB), перепроверить Job (модели могли измениться) и наличие `docling-mcp-server` |
| Очистка результатов | REST — автоматически (300 с, single-use); MCP — LRU-кэш 10 документов; при «зависших» задачах — рестарт пода |
| Деградация памяти | `ENG_LOC_NUM_WORKERS=1`, `PAGE_BATCH_SIZE=2`, `MAX_NUM_PAGES=50`; при нужде — убрать REST-контейнер, оставив только MCP |
| Закрытие доступа | `Secret doc-api-key` + `X-Api-Key` у клиентов, `DOCLING_MCP_SERVICE_API_KEY` для MCP→REST, либо `key-auth` в Higress |

## 8. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-D1** | Русский OCR «молча» не работает: дефолты `ch` (RapidOCR) и `eng` (Tesseract) | Job тянет `eslav` + `rus.traineddata`, дефолт-пресет Tesseract с `["ru","en"]`, приёмка D3 на реальном скане |
| **R-D2** | Память: модели ×число воркеров, пики OCR на больших PDF, плюс второй контейнер в поде | `ENG_LOC_NUM_WORKERS=1`, `MAX_NUM_PAGES=200`, limits 8Gi на под, замер по контейнерам в D2 |
| **R-D3** | Результат одноразовый и живёт 300 с | клиенту сохранять сразу; в демо — сразу скачивать markdown |
| **R-D4** | `ENG_KIND=local`: `poll`/`result` в памяти пода | 1 реплика; при рестарте задача теряется — повторный разбор |
| **R-D5** | Публичный CPU-разбор без авторизации = бесплатная нагрузка из интернета | решение принято; `MAX_FILE_SIZE`/`MAX_NUM_PAGES` ограничены; при злоупотреблении — `limit-count`/`key-auth` |
| **R-D6** | Образ 2,2 GiB + pull на канале 2–5 МБ/с | предтяжка пробным подом до сцены (фаза прогрева), на демо не качаем; оба контейнера из одного образа = одна копия слоёв |
| **R-D7** | Пустой PVC на baked-путь затирает модели → сервис не поднимается | `ARTIFACTS_PATH=/modelcache` + Job с wave -1; в приёмке D1 проверяется наличие каталогов |
| **R-D8** | CPU-burst на старте (загрузка layout/tableformer) | `startupProbe` 30×10 c; при медленном узле — увеличить `failureThreshold` |
| **R-D9** | `MAX_DOCUMENT_TIMEOUT` 7 дней по умолчанию | явно 1800 с |
| **R-D10** | `docling-mcp-server` может отсутствовать именно в `-cpu`-варианте образа (в доках пример на `docling-serve`) | D2 проверяет `which docling-mcp-server`; если нет — MCP из base-образа/`docling-mcp` (плюс pull), факт в §10 |
| **R-D11** | Публичный MCP без авторизации: любой может вызывать инструменты, включая загрузку по URL (SSRF и нагрузка) | `limit-count` на `/mcp`, лимиты размера/страниц, при инциденте — `key-auth`; риск принят владельцем |
| **R-D12** | `DOCLING_MCP_SERVICE_TIMEOUT` по умолчанию 300 с — скан на CPU не успевает | явно 1800 с; `FALLBACK_TO_LOCAL=false`, чтобы не подтянуть второй комплект моделей |

## 9. Что забывают в таких спеках (и что решено здесь)

| Пункт | Решение |
|---|---|
| Язык OCR | `eslav`/`rus` отдельной предзагрузкой, дефолт-пресет проверен на русском скане |
| Кэш моделей поверх baked-пути | свой путь `/modelcache` + Job, иначе затёрли модели |
| Лимиты размера | `MAX_FILE_SIZE`/`MAX_NUM_PAGES` заданы явно (дефолт = без лимита) |
| Длинные документы | только async-путь, `MAX_SYNC_WAIT=120` |
| Stateless | не stateless: poll/result в памяти пода |
| MCP и модели | MCP в `remote`-режиме, чтобы не грузить второй комплект моделей и не расходиться с REST в настройках OCR |

Открытые вопросы:

1. **Нужен ли REST, если агенты ходят по MCP.** Сейчас держим оба контейнера: REST — для UI/RAGFlow и
   curl-приёмки, MCP — для агентов. Если REST не нужен — минус контейнер и ~0,5–1 GiB RAM.
   *(Рекомендация: оставить оба до появления `rag`.)*
2. **Дефолтный OCR-пресет** — Tesseract (`rus+eng`, лучше для смешанных бумаг) или RapidOCR (`eslav`,
   быстрее на CPU). *(Решается замером D3.)*
3. **Закрывать ли `doc.*` и `/mcp`** — `key-auth`/`limit-count` в Higress или оставить публичным.
   *(Сейчас: публичный, риски R-D5/R-D11 приняты.)*
4. **Набор MCP-инструментов** — базовый (конвертация/генерация) или добавить `llama-index-rag` /
   `llama-stack-rag` (`--tools`); добавление тянет LLM-эндпоинт и векторную БД — вне демо.

## 10. Связанные документы и история версий

- `architecture/endpoints.md` — адрес `doc` (без авторизации).
- `adr/adr-0006-guardrail-higress-qwen3guard.md` — политика публичных сервисов и guardrail-слой.
- `references/demo-plan.md` — RAM-бюджет шага 2 (`Docling ≈3G` на 02).
- `architecture/specs/gpustack-spec.md` — почему GPU этому сервису не выделяется.
- `docling-mcp` (`github.com/docling-project/docling-mcp`) — инструменты и переменные `DOCLING_MCP_*`.

| Версия | Дата | Что |
|---|---|---|
| v1.2 | 2026-10-28 | **Развёрнуто через Argo CD** (`gitops/apps/doc`, Application `doc` — Synced/Healthy). Факты и правки, найденные живьём: (1) **предзагрузка — Argo-hook `Sync` wave -1**, а не обычный Job: `spec.template` Job'а иммутабелен после того, как контроллер дописал `batch.kubernetes.io/controller-uid`, ArgoCD падал на патче (`field is immutable`), Deployment/Ingress оставались OutOfSync; скрипт идемпотентен по маркеру `/modelcache/.prefetch-complete`; PVC → wave **-2**; (2) `load_models_at_boot` инициализирует **auto-OCR до пресетов** — нужны чекпоинты RapidOCR `ch` (`PP-OCRv6_det/rec_small`), иначе `CrashLoopBackOff: RapidOCR artifacts not found`; Job качает `eslav` + `ch` (851 MiB в PVC); (3) `custom_ocr_presets` задаются JSON'ом, `lang` у tesserocr — **стемы traineddata** (`rus`,`eng`), у RapidOCR — `iso:ru`; tessdata берётся из PVC через `path` пресета (без env `TESSDATA_PREFIX`); (4) `default_ocr_preset=ru-en` виден в `/v1/capabilities`, **но запрос без `ocr_preset` идёт `auto`**, а `ocr_preset=default` отвергается 422 — клиенты передают `ru-en`/`rapid-ru`; MCP-адаптер (`docling-mcp`) пресет не передаёт вообще (env для него нет) → MCP-путь разбирает кириллицу плохо (открытый пункт D4). Замеры: `/health` `/ready` `/livez` 200, MCP `initialize` 200, русский скан → кириллица в `md_content` за ~4 с (`ru-en` и `rapid-ru`) |
| v1.1 | 2026-10-28 | **Добавлен MCP-режим** (решение владельца): второй контейнер `docling-mcp` из того же образа, `--transport streamable-http --port 8000`, `CONVERSION_MODE=remote` → наш REST по loopback, `FALLBACK_TO_LOCAL=false`, таймаут 1800 с, VLM-инструменты выключены; Ingress разведён `/mcp`→8000, `/`→5001; фазы: D2 дополнена проверкой наличия бинаря в `-cpu`, новая D4 (initialize/tools/list/tools/call), публикация → D5, ограничения → D6; риски R-D10…R-D12 |
| v1.0 | 2026-10-28 | Первая версия. Живой замер: digest и размер `-cpu` (2218 MiB), состав запечённых моделей, отсутствие `eslav`/`rus` в образе, дефолты лимитов (`sys.maxsize`, `MAX_SYNC_WAIT=120`, `MAX_DOCUMENT_TIMEOUT` 7 дней), отсутствие Helm-чарта, семантика `/ready` и `/livez`, свободная RAM 02. Не установлено; размер каталога моделей и RAM/CPU под нагрузкой — замер в D1/D2 |
