# Спека: GLM-OCR на 5060 Ti (кейс 04 — распознавание сканов на своём железе)

> **Версия:** v1.0 (2026-11-06) · **Статус:** **в работе.** Веса выложены и проверены, модель `GLM-OCR`
> зарегистрирована в GPUStack (id 18, model route 13), инстанс стартует на 5060 Ti. **Качество через
> встроенный путь vLLM 0.25.1 не подтверждено** — текст деградирует (см. §7, трап T1). Идёт проверка на
> официальном образе `vllm/vllm-openai:v0.20.1-x86_64` (как на промышленном стенде). До зелёной приёмки §1
> кейс 04 остаётся на фолбэке «Docling на CPU + слайд».
> **Область:** кейс 04 (`cases/04-ocr-gpu.md`). Архитектурные решения `gpustack-spec.md` §1 (бэкенд — раннер
> vLLM) и ADR-0007 не пересматриваются: OCR-VLM едет тем же путём, что остальные модели GPUStack.

Стиль: `architecture/specs/gpustack-spec.md`. Своя буква — **R1–R7** (Recognition).

## 1. Цель и критерии приёмки

Поднять `GLM-OCR` (zai-org, VLM-OCR) как модель GPUStack на RTX 5060 Ti и получать **точный русский
текст** со скана через `https://api.demo-ai-lab.ru/v1/chat/completions` — без облачного провайдера.

Приёмка (всё обязательно):

- [x] веса на ноде `/var/lib/gpustack/models/glm-ocr`, sha256 `model.safetensors` совпадает с HF LFS OID;
- [x] модель и маршрут в GPUStack: `/v1/models` отдаёт `GLM-OCR` (id 18 / route 13), инстанс `running`;
- [ ] **функциональная приёмка:** тестовая страница (7 строк русского текста) распознана без потерь —
      строки, ИНН и сумма совпадают посимвольно;
- [ ] время на страницу ≤ 5 с на прогретом инстансе (первый запрос после старта — warmup, в зачёт не идёт);
- [ ] VRAM в бюджете кейса ≈3–6 GiB (замер при `--gpu-memory-utilization` из §6);
- [ ] инстанс переживает `Stop → Start` из UI без ручных правок и без повторного скачивания весов;
- [ ] интеграция с `doc.`: Docling ходит в `GLM-OCR` как в OpenAI-совместимый эндпоинт (отдельный шаг,
      `doc-spec` §VLM — сейчас выключено сознательно).

## 2. Живые факты (замер 2026-11-06)

| Что | Факт |
|---|---|
| Нода / GPU | `k8s-04` (`192.168.10.252`), RTX 5060 Ti **16311 MiB**, sm_120, драйвер 595.99.02 |
| GPUStack | v2.2.3, ns `gpustack`, UI/API `api.demo-ai-lab.ru`, `cluster_id = 1` |
| Модель в каталоге | `zai-org/GLM-OCR`, MIT, публичная (не gated), `pipeline_tag: image-to-text`, `model_type: glm_ocr` (`GlmOcrForConditionalGeneration`), hidden 1536, 16 слоёв, ctx 131072, MTP-слой 1 |
| Веса | **2.5 GB, 12 файлов**, `model.safetensors` 2.65 GB, sha256 `a16eb0de98d199293371c560f95f83130d2a2c9612449df16839f08ff9498815` |
| Диск | `/var/lib/gpustack` → bind-mount `/data` (`/dev/nvme0n1p3`, Netac NVMe 1TB): 913 GB, занято 177 GB |
| Раннер GPUStack | `docker.io/gpustack/runner:cuda13.0-vllm0.25.1` (9.5 GB): `vllm 0.25.1`, `transformers 5.13.1`, файлы `models/glm_ocr.py` и `glm_ocr_mtp.py` есть, `"glm_ocr" in CONFIG_MAPPING` → True |
| Промышленный стенд | custom backend на **официальном образе** `vllm/vllm-openai:v0.20.1-x86_64`, `run_command: '{{model_path}}'`, `custom_framework: cuda`; параметры в §6 |
| Модель в GPUStack | id **18** `GLM-OCR`, route **13**, `source: local_path`, `worker_selector: k8s-04`, `categories: llm` |
| Промпт | `Text Recognition:` (из карточки модели / vLLM-рецепта), изображение передаётся первым блоком `image_url` |
| Стоимость картинки | 1400×600 PNG → **1050** мультимодальных токенов (в transformers 1062 с шаблоном) |

## 3. Схема

```
GPUStack (ns gpustack)                             k8s-04
──────────────────────                             ──────────────────────────────────────
Model GLM-OCR (id 18, route 13)  ──►  под инстанса (host-network, порт {{port}})
  source: local_path                              /var/lib/gpustack/models/glm-ocr/
  local_path: …/models/glm-ocr                      ├── model.safetensors        2.65 GB
  worker_selector: k8s-04                           ├── config.json               glm_ocr
  backend: vLLM 0.25.1 | vllm-custom 0.20.1         ├── chat_template.jinja
  params: §6                                        ├── tokenizer/processor
                                                    └── README.md (промпт, языки)

Клиент ──► https://api.demo-ai-lab.ru/v1/chat/completions (ключ стенда)
             └── Higress → GPUStack → инстанс GLM-OCR
```

Почему так:

1. **Веса — `local_path`, а не `huggingface`.** С `source: huggingface` GPUStack ищет кэш по имени репо;
   при пред-выложенных весах это даёт `Error loading … config.json` (та же грабля, что была у `whisper-turbo`).
2. **Отдельный маршрут.** Без `POST /v2/model-routes` шлюз отвечает `404 Model not found` даже при `running`
   инстансе — API-путь маршрут не создаёт (B3a в `gpustack-custom-backend-spec.md` §7).
3. **Карта — эксклюзивно на время кейса.** 27B/whisper/strazh на 5060 Ti гасятся `Stop` (не удалением):
   util 0.9 + 27B на 16 GiB не уживаются.

## 4. Подготовка весов (R1, выполнено)

```bash
# на Mac — скачать
hf download zai-org/GLM-OCR --local-dir /tmp/glm-ocr          # 12 файлов, 2.5 GB, ~58 с

# на ноду и в каталог моделей
tar -cf - -C /tmp glm-ocr | ssh "$NODE04" 'tar -C /tmp -xf -'
ssh "$NODE04" 'sudo mv /tmp/glm-ocr /var/lib/gpustack/models/glm-ocr && sudo chown -R root:root /var/lib/gpustack/models/glm-ocr'
ssh "$NODE04" 'sudo find /var/lib/gpustack/models/glm-ocr -name "._*" -delete'   # macOS-мусор

# контроль
ssh "$NODE04" 'sha256sum /var/lib/gpustack/models/glm-ocr/model.safetensors'
# → a16eb0de98d199293371c560f95f83130d2a2c9612449df16839f08ff9498815 (совпадает с LFS OID на HF)
```

`GLM-OCR` — **не** gated-модель: токен HF нужен только для скорости, не для доступа.

## 5. Регистрация модели и маршрута (R2, выполнено)

Через API (admin-ключ из приватного хранилища; значения в доку не пишутся):

```bash
# 1) модель — cluster_id обязателен, иначе 500 NOT NULL cluster_id
curl -sS -X POST https://api.demo-ai-lab.ru/v2/models -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' -d '{
    "name":"GLM-OCR","source":"local_path",
    "local_path":"/var/lib/gpustack/models/glm-ocr",
    "backend":"vLLM","backend_version":"0.25.1","replicas":0,"cluster_id":1,
    "worker_selector":{"worker-name":"k8s-04"},
    "backend_parameters":["--gpu-memory-utilization 0.35","--max-model-len 8192","--max-num-seqs 2","--enforce-eager"],
    "meta":{"max_model_len":8192}}'
# → id 18

# 2) маршрут — иначе /v1/* даёт 404 при живом инстансе
curl -sS -X POST https://api.demo-ai-lab.ru/v2/model-routes -H "Authorization: Bearer $K" \
  -H 'Content-Type: application/json' -d '{"name":"GLM-OCR","description":"OCR VLM (кейс 04)",
    "targets":[{"model_id":18,"weight":1}]}'
# → id 13
```

`PUT /v2/models/{id}` — **полный объект**: брать `GET`, менять поле (`replicas`), отправлять обратно;
`Stop`/`Start` = `replicas 0/1` тем же способом.

## 6. Параметры запуска (R3–R4)

### 6.1 Промышленный конфиг (источник истины, подтверждён на продуктиве)

```yaml
backend: vllm-custom
version: v0.20.1-custom
image_name: vllm/vllm-openai:v0.20.1-x86_64
run_command: '{{model_path}}'          # + --host 0.0.0.0 --port {{port}} у нас
custom_framework: cuda
env: {}
```

```
--max-model-len 32768
--trust-remote-code
--max-num-batched-tokens 32768
--gpu-memory-utilization 0.9
--speculative-config.method mtp
--speculative-config.num_speculative_tokens 1
```

### 6.2 Что добавляем на своём стенде

| Причина | Добавка |
|---|---|
| на `gpustack/runner:cuda13.0-vllm0.25.1` инициализация падает на захвате CUDA-графов (`cudaErrorStreamCaptureUnsupported`) | `--enforce-eager` |
| GPUStack поллит `http://<ip>:<port>/health` | `--host 0.0.0.0 --port {{port}}` в `run_command` (обязательно, см. `gpustack-custom-backend-spec.md` §7) |

### 6.3 Бюджет памяти (замер при util 0.35)

| Что | MiB |
|---|---|
| веса в VRAM | 2140 (2.09 GiB) |
| KV-кэш при util 0.35 | ~3200 (51 328 токенов) |
| **итого на карте** | **5860 из 16311** |

При util 0.9 под KV уходит ~10 GiB — на 16 GiB это возможно только при погашенных 27B/whisper.

## 7. Грабли (проверено на живом стенде)

### T1. Встроенный путь vLLM 0.25.1 отдаёт мусор вместо текста

Симптом: инстанс `running`, HTTP 200, но текст деградирует — «СЧЁТ НА ОПЛАТ **НА ОПЛАТУ** № 42»,
«1 шт.» повтором до `max_tokens`, числа склеиваются («125006.1250701245701234567»).

Что проверено и **не помогло**: `temperature 0` (вывод стабильно тот же → не сэмплирование);
`--speculative-config.method mtp`; промышленные `--max-model-len 32768 --trust-remote-code
--max-num-batched-tokens 32768 --gpu-memory-utilization 0.9`.

Причина — реализация `glm_ocr` (mrope/позиции) в этой сборке, а не конфиг: те же веса и та же картинка
через `transformers` дают **идеальный** текст (§9). Лечение — другой образ/версия vLLM (промышленный
вариант §6.1), а не подбор флагов.

### T2. `--model-impl transformers` падает на старте

```
IndexError: too many indices for tensor of dimension 1
  transformers/models/glm_ocr/modeling_glm_ocr.py:916 in get_rope_index   (video_grid_thw[:, 0])
Run time: Engine core initialization failed
```

То есть HF-реализация внутри vLLM 0.25.1 для image-only входа тоже нерабочая. Обратный вывод: **чистый
`transformers` (без vLLM) работает** — это и есть основа для custom-бэкенда на HF-сервере, если
промышленный образ не подойдёт.

### T3. CUDA-графы не захватываются

Без `--enforce-eager` старт падает на `torch.AcceleratorError: operation not permitted when stream is
capturing` (`cudaErrorStreamCaptureUnsupported`). С `--enforce-eager` стартует за ~60–90 с.
Цена — нет CUDA graphs; для OCR-страницы это единицы процентов.

### T4. Синтетическая картинка — валидный тест

Проверено: та же страница, сгенерированная в PIL (Arial Unicode, 1400×600), распознаётся эталонным путём
без потерь. Значит «мусор» на тесте — не «плохая картинка», а дефект движка; отговорку «модель не любит
синтетику» использовать нельзя.

### T5. Маршрут не создаётся автоматически

`POST /v2/models` через API не заводит `model-route` → `404 Model not found` при `running` инстансе.
Лечится `POST /v2/model-routes` (§5).

## 8. Приёмка (R5)

Скрипт: `scripts/glm_ocr_smoke.py` (ключ и адрес — из окружения, в коде значений нет).

```bash
export GPUSTACK_API_KEY=<ключ стенда>
export GPUSTACK_API_BASE=https://api.demo-ai-lab.ru   # по умолчанию он же
export RESOLVE_IP=192.168.10.230                      # ходить в стенд по LAN, минуя внешний DNS
python3 scripts/glm_ocr_smoke.py --image /tmp/ocr-test2.png
```

Что печатает: `http`, время ответа, распознанный текст, `usage`. Годный результат — строки совпадают с
исходником, включая `ИНН 7701234567`, `1 250,00 руб.`, `НДС 20%: 208,33 руб.`, без повторов.

Через `curl` то же самое:

```bash
IMG=$(base64 -i /tmp/ocr-test2.png | tr -d '\n')
curl -s https://api.demo-ai-lab.ru/v1/chat/completions \
  --resolve api.demo-ai-lab.ru:443:$RESOLVE_IP \
  -H "Authorization: Bearer $GPUSTACK_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"model\":\"GLM-OCR\",\"temperature\":0,\"max_tokens\":512,\"messages\":[{\"role\":\"user\",
      \"content\":[{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/png;base64,$IMG\"}},
                   {\"type\":\"text\",\"text\":\"Text Recognition:\"}]}]}"
```

Дополнительно (в отчёт): `nvidia-smi` на k8s-04 до/после, имя и порт инстанса, версия бэкенда, время
первого (warmup) и второго запроса.

## 9. Эталонный результат (transformers, CPU — доказательство работоспособности весов)

`GlmOcrForConditionalGeneration`, `dtype float32`, `device_map cpu`, `do_sample=False`, промпт
`Text Recognition:`, 1062 prompt-токена:

```
СЧЁТ НА ОПЛАТУ № 42
от 06 ноября 2026 г.
Поставщик: ООО «Ромашка», ИНН 7701234567
Покупатель: ООО «Лютик», ИНН 7709876543
1. Услуги связи 1 шт. 1 250,00 руб.
Итого к оплате: 1 250,00 руб.
В том числе НДС 20%: 208,33 руб.
```

Загрузка весов 1.4 с, генерация **27.2 с на CPU** (в зачёт скорости не идёт — это только проверка
корректности). Отсюда: модель и веса годные, проблема — исключительно в пути vLLM 0.25.1 (T1/T2).

## 10. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-1** | Промышленный образ `vllm/vllm-openai:v0.20.1-x86_64` тоже не заведётся (иной драйвер/CUDA) | Тогда custom-бэкенд на `transformers` (FastAPI + HF, тот же образ раннера или `nvidia/cuda`) — путь уже доказан §9; это ~1–2 ч работы и отдельная версия бэкенда |
| **R-2** | OOM: util 0.9 + забытый резидент на карте | Перед `Start` — `Stop` 27B/whisper/стража; после кейса вернуть (`gpustack-custom-backend-spec.md` §8 — параметры возврата) |
| **R-3** | Образ 10+ ГБ тянется на сцене | Прогреть `ctr images pull` заранее; проверить `scripts/warm_images.py --check-only` |
| **R-4** | Веса вне git и вне бэкапа (2.5 ГБ) | Воспроизводятся за ~1 мин с HF (§4), данными не считаются |
| **R-5** | Кириллица/handwriting: у модели есть пределы (рукопись, поворот, смешанные языки) | На сцене — 2–3 подготовленных документа (`cases/04-ocr-gpu.md`), ограничения назвать голосом |
| **R-6** | Docling-VLM путь в `doc-spec` выключен (`DO_PICTURE_DESCRIPTION` off) | Включать только после зелёной приёмки §1 — отдельная правка `doc-spec`, не «попутно» |

## 11. Запрещено

- Подбирать флаги «пока не заработает» при известном T1: параметры зафиксированы §6, лечится версия/образ.
- `kubectl delete/scale` вместо UI `Stop`/`Start` (состояние в БД GPUStack разъедется).
- Удалять веса или «пересоздавать» модель вместо `replicas 0` — маршрут и ключи завязаны на id 18.
- Включать VLM-путь Docling, править `doc-spec`/ADR до приёмки §1.
- Печатать в доках, логах и коммитах ключи GPUStack/API (только имена секретов и `*.local.md`).

## 12. История версий

| Версия | Дата | Что |
|---|---|---|
| v1.0 | 2026-11-06 | Первая версия: живые факты (веса 2.5 GB, sha256, каталог на `/data`), регистрация модели id 18 / route 13, промышленный конфиг `vllm-openai:v0.20.1-x86_64` + параметры, наши добавки (`--enforce-eager`, `--host/--port`), бюджет VRAM 5860 MiB, грабли T1–T5 (mrope в 0.25.1, `--model-impl transformers` IndexError, CUDA-графы, синтетика как валидный тест, ручной маршрут), эталонный вывод transformers, риски R-1…R-6 |

## 13. Связанные документы

- `cases/04-ocr-gpu.md` — сценарий показа кейса 04 и фолбэк.
- `architecture/specs/gpustack-spec.md` §1 (бэкенды/раннер), §4.5 (модели и `local_path`), §7 (Stop вместо scale).
- `architecture/specs/gpustack-custom-backend-spec.md` §7 B3a — грабли API GPUStack (полный `PUT`, `cluster_id`, `env` только на модели, ручной model route).
- `architecture/specs/doc-spec.md` — Docling Serve / MCP, CPU-OCR с русским пресетом (VLM-путь выключен).
- `scripts/glm_ocr_smoke.py` — воспроизводимая приёмка OCR через шлюз.
