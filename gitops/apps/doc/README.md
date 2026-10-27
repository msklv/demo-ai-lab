# Docling Serve + Docling MCP (`doc.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/doc-spec.md` (фазы D1–D6). Раскатывает ApplicationSet `apps` в ns `doc`
как plain-манифесты. Секретов нет: авторизации ни у REST, ни у MCP.

| Файл | Sync-wave | Что |
|---|---|---|
| `10-pvc.yaml` | 0 | PVC `docling-models` 10Gi `longhorn` → `/modelcache` |
| `20-prefetch-job.yaml` | **-1** | Job `docling-model-cache-load`: `docling-tools models download … --rapidocr-backend-lang onnxruntime:eslav` + tessdata с `rus.traineddata` |
| `30-deployment.yaml` | 0 | Deployment `docling`: `docling-serve` (5001) + `docling-mcp` (8000), CPU-OCR |
| `40-service.yaml` | 1 | ClusterIP `docling`: 5001 (`http`) и 8000 (`mcp`) |
| `50-ingress.yaml` | 2 | `Certificate doc-demo-tls` + `Ingress doc`: `/mcp`→8000, `/`→5001 |

## Решения, важные для работоспособности

- **Свой путь кэша `/modelcache`**, а не baked-путь образа
  (`/opt/app-root/src/.cache/docling/models`): пустой PVC поверх baked-каталога затирает модели,
  сервис падает. В рантайме модели не докачиваются — Job обязателен (D1).
- **Русский OCR**: в образе нет ни `eslav`-моделей RapidOCR, ни `rus.traineddata`. Job кладёт
  `eslav` (`--rapidocr-backend-lang onnxruntime:eslav`) и копирует весь системный tessdata в
  `/modelcache/tessdata` + скачивает `rus.traineddata` (`tessdata_best`).
- **Дефолт-пресет OCR — `ru-en`** (`tesserocr`, `lang: [rus, eng]`, `path: /modelcache/tessdata`).
  `path` задан явно вместо env `TESSDATA_PREFIX`: так системный каталог образа не трогается,
  а английский и русский живут в одном прогоне. Второй пресет `rapid-ru` (`rapidocr`, `iso:ru`
  → PP-OCRv5 `eslav`) — для замера D3.
  Примечание: `lang` у Tesseract — **стемы файлов traineddata** (`rus`, `eng`), не BCP-47 (`ru`, `en`);
  у RapidOCR, наоборот, BCP-47 с префиксом `iso:` (`iso:ru` → `eslav`).
- **MCP в режиме `remote`**: `docling-mcp` конвертирует через REST этого же пода по loopback,
  `FALLBACK_TO_LOCAL=false` (иначе MCP подтянет второй комплект моделей и свои OCR-настройки).
- **fsGroup 1001**: образ UBI-based (uid 1001), PVC Longhorn создаётся `root:root` — без `fsGroup`
  Job и под не смогут писать в `/modelcache`.
- `MAX_DOCUMENT_TIMEOUT=1800`, `MAX_FILE_SIZE=50 MiB`, `MAX_NUM_PAGES=200` — дефолты в коде
  (7 дней / `sys.maxsize`) для публичного сервиса неприемлемы.

Job неизменяем после создания: при правке скрипта удалить `job/docling-model-cache-load` и дать
Argo создать его заново (`kubectl -n doc delete job docling-model-cache-load`, затем refresh).
