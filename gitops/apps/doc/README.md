# Docling Serve + Docling MCP (`doc.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/specs/doc-spec.md` (фазы D1–D7). Раскатывает ApplicationSet `apps` в ns `doc`
как plain-манифесты. Своей авторизации ни у REST, ни у MCP нет; один Secret — `docling-ocr` (ключ
GPUStack для распознавания через `GLM-OCR`, в запросы клиентов не попадает).

| Файл | Sync-wave | Что |
|---|---|---|
| `10-pvc.yaml` | -2 | PVC `docling-models` 10Gi `longhorn` → `/modelcache` |
| `20-prefetch-job.yaml` | **-1** | Job-хук `docling-model-cache-load`: `docling-tools models download … --rapidocr-backend-lang onnxruntime:eslav` + tessdata с `rus.traineddata` (тег образа = тег Deployment) |
| `25-configmap.yaml` | **-1** | `ConfigMap docling-vlm-default`: `sitecustomize.py` ставит дефолт `vlm_pipeline_preset = glm-ocr` |
| `30-deployment.yaml` | 0 | Deployment `docling`: `docling-serve` (5001) + `docling-mcp` (8000); VLM-дефолт → `GLM-OCR`, CPU — явным `pipeline=standard` |
| `40-service.yaml` | 1 | ClusterIP `docling`: 5001 (`http`) и 8000 (`mcp`) |
| `50-ingress.yaml` | 2 | `Certificate doc-demo-tls` + `Ingress doc`: `/`→5001; `/mcp` наружу **снят 24.11** (ADR-0012), MCP только in-cluster |

## Решения, важные для работоспособности

- **Свой путь кэша `/modelcache`**, а не baked-путь образа
  (`/opt/app-root/src/.cache/docling/models`): пустой PVC поверх baked-каталога затирает модели,
  сервис падает. В рантайме модели не докачиваются — Job обязателен (D1).
- **VLM — дефолт сервиса** (`DEFAULT_PIPELINE=vlm`, спека §5.1). Сам по себе этот ключ подставляет
  только pipeline: запрос без `vlm_pipeline_preset` уходил в legacy-ветку с зашитым
  `granite-docling-258M` и докачкой весов с HF (таймаут и `504`). Поэтому ConfigMap `docling-vlm-default`
  ставит `glm-ocr` дефолтом поля — патч виден в логе строкой `vlm_pipeline_preset default -> glm-ocr`.
  Ключ GPUStack — `Secret docling-ocr` (`scripts/docling_secrets.sh`); в манифесте только `secretKeyRef`
  и подстановка `$(GLM_OCR_API_KEY)`, причём переменную объявлять **выше** JSON-пресета.
- **Русский CPU-путь**: в образе нет ни `eslav`-моделей RapidOCR, ни `rus.traineddata`. Job кладёт
  `eslav` (`--rapidocr-backend-lang onnxruntime:eslav`) **и дефолтный `ch`** (warm-up моделей на
  старте инициализирует auto-OCR раньше пресетов — без `ch`-чекпоинтов сервис падает в
  CrashLoopBackOff) и копирует весь системный tessdata в
  `/modelcache/tessdata` + скачивает `rus.traineddata` (`tessdata_best`).
- **CPU-пресеты действуют только в `pipeline=standard`** (в VLM-пути `ocr_preset` не участвует):
  `ru-en` = `tesserocr` `[rus,eng]` с `path: /modelcache/tessdata` (`path` задан явно вместо env
  `TESSDATA_PREFIX` — системный каталог образа не трогается, английский и русский в одном прогоне),
  `rapid-ru` = `rapidocr` `iso:ru` → PP-OCRv5 `eslav`.
  Примечание: `lang` у Tesseract — **стемы файлов traineddata** (`rus`, `eng`), не BCP-47 (`ru`, `en`);
  у RapidOCR наоборот — BCP-47 с префиксом `iso:`.
  Клиенты CPU-пути передают пресет обязательно: без `ocr_preset` запрос идёт `auto` (RapidOCR `ch`),
  а `ocr_preset=default` отвергается 422.
- **MCP в режиме `remote`**: `docling-mcp` конвертирует через REST этого же пода по loopback,
  `FALLBACK_TO_LOCAL=false` (иначе MCP подтянет второй комплект моделей и свои OCR-настройки).
  Параметра `pipeline` у адаптера нет: агент идёт путём, заданным дефолтом сервера (сейчас VLM),
  выбрать CPU через MCP нельзя — открытый пункт `doc-spec` §9.
- **fsGroup 1001**: образ UBI-based (uid 1001), PVC Longhorn создаётся `root:root` — без `fsGroup`
  Job и под не смогут писать в `/modelcache`.
- `MAX_DOCUMENT_TIMEOUT=1800`, `MAX_FILE_SIZE=50 MiB`, `MAX_NUM_PAGES=200` — дефолты в коде
  (7 дней / `sys.maxsize`) для публичного сервиса неприемлемы.

**Предзагрузка — Argo-хук (`Sync`, wave -1), а не обычный ресурс.** Job иммутабелен, а контроллер
Job'а дописывает в `spec.template` метки `batch.kubernetes.io/controller-uid`: ArgoCD видит
расхождение и падает на патче шаблона (`spec.template: ... field is immutable`), при этом Deployment
и Ingress остаются OutOfSync. Как hook объект в diff'е не участвует. Скрипт идемпотентен — маркер
`/modelcache/.prefetch-complete`, повторный синк выходит за секунды и качает только недостающее.
Обратная сторона: при смене тега образа модели **не пересеиваются** — маркер надо снимать вручную.
Политика удаления — `HookSucceeded`: завершённый под Job'а в ns не остаётся, иначе health-gate
`scripts/k8s_health.py` считает его не-readiness (`0/1 ready`) и красит весь стенд в FAIL.
PVC — RWO, и пока сервис работает, том занят подом `docling`: кросс-нодовый attach даёт
`Multi-Attach error`. Поэтому у хука `podAffinity.preferred` к поду `docling` по hostname — он
встаёт на ту же ноду (там RWO монтируется обоим подам), а при первой установке, когда сервиса ещё
нет, планируется свободно.
Волны: PVC `-2` → hook и ConfigMap `-1` → Deployment/Service `0`/`1` → Ingress `2`.
