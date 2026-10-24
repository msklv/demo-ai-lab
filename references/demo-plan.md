# План и подготовка живого демо

## Сценарий (3 части)

1. Инфраструктура «во главе с GPUStack»: установка GPUStack helm-чартом + worker на GPU-ноде k8s-04
   (RTX 5060 Ti 16G), бекенд — **только раннер каталога** (`gpustack/runner:cuda13.0-vllm0.25.1`,
   драйвер 595 → CUDA 13.x; тег выбирает сам GPUStack по детекту). llama-box снят с v2.0.0, а GGUF и
   кастомный llama.cpp исключены решением владельца — модели берём safetensors/AWQ (Qwen3-14B/8B AWQ
   4-bit: 10.0 и 6.1 ГБ весов, обе в 16 ГБ VRAM; bge-m3 для эмбеддингов).
2. Простые сервисы: Open WebUI, RAGFlow, Docling, Speakr (+Superset для BI). Роуты Higress:
   `owu.`/`rag.`/`doc.`/`spk.`/`sup.` на `*.demo-ai-lab.ru` (полный список — `architecture/endpoints.md`).
3. Агентские: qm + Hermes-рантаймы + MCP-каталог (`mcp.` — MCP Registry, `architecture/mcp-registry-spec.md`);
   вызовы инструментов — через Higress (`mcp-server`); LLM — qwen3 через GPUStack (tool-calling).

## RAM-бюджет (ноды 02/03 — 14Gi, 04 — 28Gi)

- RAGFlow-стек одним официальным чартом (ES+MySQL+Redis+MinIO+server+worker) ≈ 10–12G → на 03 впритык;
  ES-heap урезать до 2G, replicas=0.
- Open WebUI ~1G (02), Docling ~3G (02), Speakr+whisper ~2G (03), PostgreSQL для qm ~1.5G (03).
- Langfuse (ClickHouse+PG), Keycloak, Qdrant одновременно НЕ влезают → демо «профилями»: часть 2 / часть 3;
  тяжёлые доп. сервисы — слайд или «если останется RAM».

## «Всё ли готово к демо этапа N» — проверка слоями

Кластерный health закрывает только первый слой; вопрос про готовность демо — это пять слоёв, и ответ идёт
по ним (красный внешний путь — это туннель, а не кластер).

1. **Кластер:** `python3 scripts/k8s_health.py` + `python3 scripts/env_health.py` (кластер и обвязка разделены).
2. **Образы:** `ctr -n k8s.io images ls -q | grep -i <имя>` на целевых нодах (через `sudo -S`, пароль —
   из локального приватного хранилища). Пусто = на сцене будет pull на гигабайты; при 4–6 МБ/с площадки это
   десятки минут тишины.
3. **Модели:** на инференс-ноде проверить каталоги моделей (`find / -maxdepth 4 -name '*.gguf' -o -name '*.safetensors'`) и сверить с README шага; под vLLM модель — директория с весами и конфигами, не один файл. Кэш на консоли (LM Studio и пр.) не считается — везти/качать на ноду заранее.
4. **Прерогативы фичи:** RuntimeClass, лейблы (свои NodeFeatureRule, NFD), StorageClass/квоты, CRD,
   версии helm/kubectl. Именно здесь всплывают «зелёный кластер, но фича не стартует».
5. **Маршруты и доки:** ingress + IngressClass, хост в конфиге туннеля (правило E6: хостнейм заводится
   вместе с Access-приложением), DNS с edge (`dig @1.1.1.1`, `curl --resolve`) и из LAN; непрожитые фазы
   спеки (metrics-server → `kubectl top` = `Metrics API not available`); актуальность борда ARCHITECTURE §7
   (он отстаёт от факта — сверять с `helm list -A`, `kubectl get ingressclass`, состоянием VIP).
6. **Репетиция с таймером** — обязательна для экспериментального пути (ADR-0001): часть 1 ≤ 10 мин,
   часть 2 ≤ 15, часть 3 ≤ 10. Без репетиции ответ «готово» не даётся.

Ответ владельцу: вердикт одной строкой → таблица «что зелёное» с живыми фактами замера → нумерованный
список блокеров (признак замера + что делать + сколько это стоит по времени) → предложение подготовки.
Не смешивать «кластер здоров» и «этап демо готов».

Остальное из прежнего чек-листа — пункты слоёв 4–5: cert-manager wildcard (DNS-01), split-DNS/hairpin для
LAN-аудитории, Longhorn SC + анти-аффинити (`references/storage-model.md`), индексация базы RAGFlow ДО
сцены (первый парсинг 5+ мин), warmup-запрос к модели до выхода.

## Фолбэк

- GPUStack не поднялся → хостовый llama.cpp/BeeLlama на 04 (`start_beellama_5060.sh`, OpenAI-совместимый
  API на :8081) + Ingress Higress к нему. **Не** ставить docker на 04 ради этого: `docker.io` тянет
  containerd 1.x и ломает рабочую связку containerd 2.2.1 + nvidia-runtime + CDI.
- Longhorn-снапшоты перед демо; стейт сервисов некритичен.

## GPUStack 2.2 helm — сверено по чарту 2.2.3

- Требует: helm ≥ 3.18.4 (на консоли может стоять helm 4.x — совместимость чарта с ним не заявлена, это
  проверяется репетицией, а не предположением), K8s ≥ 1.30, default StorageClass (на стенде `longhorn`),
  NFD для GPU-нод. Чарт OCI `oci://registry-1.docker.io/gpustack/gpustack-chart`, версия чарта = версия
  GPUStack; `helm show chart` / `helm pull` с консоли проходят (egress к docker.io рабочий).
- Bundled-зависимость чарта — `higress-core` 2.1.9, т.е. ровно наш пин standalone-Higress (ADR-0001 рев. 3):
  ставить с `--set higress-core.enabled=false --set gateway.ingressClassname=higress`.
- Server — StatefulSet 1 реплика, PVC `gpustack-data-dir-gpustack-server-0` (`server.dataVolume.size`,
  дефолт 100Gi; альтернатива — `server.dataVolume.hostPath`). Роут UI/API — `server.ingress.hostname`
  (для шага 1 — `api.demo-ai-lab.ru`); на Longhorn r=2 тома 100Gi хватает, если на 3 узлах пула свободно ≥200Gi.
- `worker.enabled=false` по умолчанию. При `true` рендерятся CPU-DaemonSet `<release>-worker` (nodeSelector
  `feature.gpustack.ai/acceleratable: "false"`) и по DaemonSet на вендора из `worker.gpuVendors`
  (nvidia → `feature.node.kubernetes.io/pci-10de.present: "true"` + `runtimeClassName: nvidia`).
- **Чарт не создаёт ни NodeFeatureRule, ни RuntimeClass.** До install руками: RuntimeClass `nvidia`
  (handler `nvidia`) и лейбл `feature.gpustack.ai/acceleratable=false` на CPU-нодах. Иначе GPU-воркер
  падает на отсутствующем runtimeclass, а CPU-DaemonSet висит Pending (CPU-инференса поддерживаемым
  бэкендом сейчас нет — CPU-воркер нужен только под служебные задачи).
- Образы для прогрева на k8s-04: `gpustack/gpustack:v2.2.3` (~3.1 ГБ), `gpustack/gpustack-operator:v0.5.4` (~0.6 ГБ),
  `gpustack/higress-plugins:0.3.0` (~0.2 ГБ), `gpustack/ssh-server:v1.1.0` (~18 МБ),
  раннер `gpustack/runner:cuda13.0-vllm0.25.1` (~20.5 ГБ; 12.9-вариант 26 ГБ — только фолбэк).
  Inference-движок (раннер) сервер тянет сам при деплое модели — образ обязан лежать на ноде заранее;
  именно он определяет смету шага 1, а не модели.
  **Склада предзагрузки нет (снято 2026-10-24):** образы и веса прогреваются прямым pull с самой ноды
  на подготовке — ≈39 ГБ для набора 14B + bge-m3 (образы 24.4 + веса 14.6; со 8B ≈45 ГБ) при 4–6 МБ/с,
  т.е. часы. На сцене качать нечего.
- Настоящее доказательство GPU-пути — не драйвер и не CDI-файл, а контейнер с `runtimeClassName: nvidia`,
  внутри которого `nvidia-smi` видит карту. Это первый smoke после install, до деплоя моделей.
- Wasm-плагины gateway (guard-маршрут) качаются с Deployment `gpustack/higress-plugins`; без него старт
  gateway блокируется. Guard и промпт-фаервол ставятся **плагинами Higress** (решение 2026-10-24):
  `ai-security-guard` + штатные `WAF`/`request-block`/`ip-restriction`/`ai-data-masking`. Практическое
  ограничение: `ai-security-guard` работает только с Aliyun Content Security (endpoint, AK/SK, egress) и
  проверяет легальность контента, а не инъекции; штатного плагина-классификатора prompt-injection нет —
  для промпт-фаервола нужен кастомный Wasm-плагин или внешний сервис модерации (решение отдельно).
