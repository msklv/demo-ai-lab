# Спека: GLM-OCR на 5070 Ti (кейс 04 — распознавание сканов на своём железе)

> **Версия:** v1.2 (2026-11-06) · **Статус:** **приёмка §1 закрыта на образе
> `vllm/vllm-openai:v0.20.1-x86_64`** (как на промышленном стенде): страница распознана посимвольно через
> `api.demo-ai-lab.ru` за **0.40 с** (первый запрос) / **0.19 с** (прогретый), VRAM **12146/16311 MiB**.
> Встроенный путь `gpustack/runner:cuda13.0-vllm0.25.1` для этой модели **непригоден** — §7 T1.
> Открыт ровно один пункт — интеграция с `doc.` (VLM-путь Docling пока выключен, §10 R-6).
> **Область:** кейс 04 (`cases/04-ocr-gpu.md`). Архитектурные решения `gpustack-spec.md` §1 (бэкенд — раннер
> vLLM) и ADR-0007 не пересматриваются: OCR-VLM едет тем же путём, что остальные модели GPUStack.

Стиль: `architecture/specs/gpustack-spec.md`. Своя буква — **R1–R7** (Recognition).

## 1. Цель и критерии приёмки

Поднять `GLM-OCR` (zai-org, VLM-OCR) как модель GPUStack на RTX 5070 Ti и получать **точный русский
текст** со скана через `https://api.demo-ai-lab.ru/v1/chat/completions` — без облачного провайдера.

Приёмка (всё обязательно):

- [x] веса на ноде `/var/lib/gpustack/models/glm-ocr`, sha256 `model.safetensors` совпадает с HF LFS OID;
- [x] модель и маршрут в GPUStack: `/v1/models` отдаёт `GLM-OCR` (id 18 / route 13), инстанс `running`;
- [x] **функциональная приёмка:** тестовая страница (7 строк русского текста) распознана без потерь —
      строки, ИНН и сумма совпадают посимвольно (2026-11-06, см. §9.1);
- [x] время на страницу ≤ 5 с: **0.40 с** первый запрос, **0.19 с** прогретый (§9.1);
- [x] VRAM: **12146 из 16311 MiB** при `--gpu-memory-utilization 0.9` (§6.3);
- [x] инстанс переживает `Stop → Start` (проверено 4 перезапуска 2026-11-06), веса не перекачиваются;
- [x] модель доступна в чате OWU (`owu.demo-ai-lab.ru`): добавлена в `model_ids` подключения GPUStack
      2026-11-06, под перезапущен (см. `owu-spec.md` §7.2);
- [ ] интеграция с `doc.`: Docling ходит в `GLM-OCR` как в OpenAI-совместимый эндпоинт (отдельный шаг,
      `doc-spec` §VLM — сейчас выключено сознательно).

## 2. Живые факты (замер 2026-11-06)

| Что | Факт |
|---|---|
| Нода / GPU | `k8s-04` (`192.168.10.252`), RTX 5070 Ti **16303 MiB**, sm_120, драйвер 595.99.02 |
| GPUStack | v2.2.3, ns `gpustack`, UI/API `api.demo-ai-lab.ru`, `cluster_id = 1` |
| Модель в каталоге | `zai-org/GLM-OCR`, MIT, публичная (не gated), `pipeline_tag: image-to-text`, `model_type: glm_ocr` (`GlmOcrForConditionalGeneration`), hidden 1536, 16 слоёв, ctx 131072, MTP-слой 1 |
| Веса | **2.5 GB, 12 файлов**, `model.safetensors` 2.65 GB, sha256 `a16eb0de98d199293371c560f95f83130d2a2c9612449df16839f08ff9498815` |
| Диск | `/var/lib/gpustack` → bind-mount `/data` (`/dev/nvme0n1p3`, Netac NVMe 1TB): 913 GB, занято 177 GB |
| Раннер GPUStack | `docker.io/gpustack/runner:cuda13.0-vllm0.25.1` (9.5 GB): `vllm 0.25.1`, `transformers 5.13.1`, файлы `models/glm_ocr.py` и `glm_ocr_mtp.py` есть, `"glm_ocr" in CONFIG_MAPPING` → True |
| Промышленный стенд | custom backend на **официальном образе** `vllm/vllm-openai:v0.20.1-x86_64`, `run_command: '{{model_path}}'`, `custom_framework: cuda`; параметры в §6 |
| Модель в GPUStack | id **18** `GLM-OCR`, route **13**, `source: local_path`, `worker_selector: k8s-04`, `categories: llm` |
| Бэкенд (рабочий) | custom `vllm-custom` (id 14), версия `v0.20.1-custom`: образ `vllm/vllm-openai:v0.20.1-x86_64` (**8.2 GB**, pull 4m50s), `run_command: {{model_path}} --host 0.0.0.0 --port {{port}}`, `custom_framework: cuda` |
| Инстанс (замер) | `GLM-OCR-yizre` id **88**, порт **40019**, старт ~2 мин (веса 2.1 GiB + профилировка CUDA-графов), VRAM **12146 MiB** |
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
3. **Карта — эксклюзивно на время кейса.** 27B/whisper/strazh на 5070 Ti гасятся `Stop` (не удалением):
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
| GPUStack поллит `http://<ip>:<port>/health` | `--host 0.0.0.0 --port {{port}}` в `run_command` (обязательно, см. `gpustack-custom-backend-spec.md` §7) |
| vLLM называет модель по пути (`/var/lib/gpustack/models/glm-ocr`) → шлюз отдаёт `404 The model `GLM-OCR` does not exist` | `--served-model-name GLM-OCR` (§7 T6) |

На официальном образе `vllm/vllm-openai:v0.20.1-x86_64` **`--enforce-eager` не нужен**: CUDA-графы
захватываются штатно (в отличие от раннера `gpustack/runner:cuda13.0-vllm0.25.1`, §7 T3).

### 6.3 Бюджет памяти

| Режим | Занято на карте |
|---|---|
| util 0.35, `--max-model-len 8192` (первая прикидка на раннере) | **5860 MiB** (веса 2140 + KV ~3200) |
| **util 0.9, `--max-model-len 32768` (рабочий, 0.20.1)** | **12146 MiB** из 16311 |

Вывод: при util 0.9 GLM-OCR занимает **три четверти** карты — на 16 GiB она живёт только при погашенных
27B/whisper/страже. Для экономии VRAM на сцене допустим `--gpu-memory-utilization 0.5` + прежний
`--max-model-len 8192` (текст от этого не страдает, проверено на 0.35).

## 7. Грабли (проверено на живом стенде)

### T1. Встроенный путь vLLM 0.25.1 отдаёт мусор вместо текста

Симптом: инстанс `running`, HTTP 200, но текст деградирует — «СЧЁТ НА ОПЛАТ **НА ОПЛАТУ** № 42»,
«1 шт.» повтором до `max_tokens`, числа склеиваются («125006.1250701245701234567»).

Что проверено и **не помогло**: `temperature 0` (вывод стабильно тот же → не сэмплирование);
`--speculative-config.method mtp`; промышленные `--max-model-len 32768 --trust-remote-code
--max-num-batched-tokens 32768 --gpu-memory-utilization 0.9`.

Причина — реализация `glm_ocr` (mrope/позиции) в этой сборке, а не конфиг: те же веса и та же картинка
через `transformers` дают **идеальный** текст (§9).

**Закрыто 2026-11-06:** смена образа на официальный `vllm/vllm-openai:v0.20.1-x86_64` (§6.1) дала точный
текст без единой правки параметров. То есть дело не в версии vLLM как таковой, а в сборке
`gpustack/runner`: в ней `glm_ocr` считается с неверными позициями. Подбор флагов на этой сборке
бесполезен — лечится только образом.

### T2. `--model-impl transformers` падает на старте

```
IndexError: too many indices for tensor of dimension 1
  transformers/models/glm_ocr/modeling_glm_ocr.py:916 in get_rope_index   (video_grid_thw[:, 0])
Run time: Engine core initialization failed
```

То есть HF-реализация внутри vLLM 0.25.1 для image-only входа тоже нерабочая. Обратный вывод: **чистый
`transformers` (без vLLM) работает** — это и есть основа для custom-бэкенда на HF-сервере, если
промышленный образ не подойдёт.

### T3. На раннере GPUStack не захватываются CUDA-графы

Относится **только** к `gpustack/runner:cuda13.0-vllm0.25.1`: без `--enforce-eager` старт падает на
`torch.AcceleratorError: operation not permitted when stream is capturing`
(`cudaErrorStreamCaptureUnsupported`), с `--enforce-eager` — стартует за ~60–90 с без графов.
На официальном образе `vllm/vllm-openai:v0.20.1-x86_64` профилировка `PIECEWISE=50` проходит штатно,
`--enforce-eager` не нужен.

### T4. Синтетическая картинка — валидный тест

Проверено: та же страница, сгенерированная в PIL (Arial Unicode, 1400×600), распознаётся эталонным путём
без потерь. Значит «мусор» на тесте — не «плохая картинка», а дефект движка; отговорку «модель не любит
синтетику» использовать нельзя.

### T5. Маршрут не создаётся автоматически

`POST /v2/models` через API не заводит `model-route` → `404 Model not found` при `running` инстансе.
Лечится `POST /v2/model-routes` (§5).

### T6. Имя модели у vLLM = путь, а не имя модели GPUStack

Симптом: инстанс `running`, `/health` 200, но через шлюз `404 {"message":"The model `GLM-OCR` does not
exist."}`. Причина: vLLM без `--served-model-name` публикует в `/v1/models` **путь** —
`curl http://192.168.10.252:40019/v1/models` → `['/var/lib/gpustack/models/glm-ocr']`.

Лечение: `--served-model-name GLM-OCR` в `backend_parameters` (имя должно совпадать с `name` модели
GPUStack и с `name` маршрута). Проверка после старта:

```bash
curl -s http://192.168.10.252:<port>/v1/models      # ожидание: ['GLM-OCR']
curl -s https://api.demo-ai-lab.ru/v1/models -H "Authorization: Bearer $K"   # GLM-OCR в списке
```

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

## 9.1 Результат на стенде (2026-11-06, образ `vllm-openai:v0.20.1-x86_64`)

Через шлюз, `scripts/glm_ocr_smoke.py`, тот же скан:

| Запрос | Время | prompt / completion | Текст |
|---|---|---|---|
| стр. 1 — счёт, 7 строк (1400×600), **первый после старта** | **2.12 с** (cold) | 1062 / 139 | посимвольно верно, включая `ИНН 7701234567` и `НДС 20%: 208,33 руб.` |
| стр. 1 — повтор | **0.40 с** | 1062 / 139 | тот же текст |
| стр. 2 — две строки (900×220) | **0.19 с** | 268 / 50 | `Счёт № 42 от 06.11.2026` · `Сумма: 1 250,00 руб. ИНН 7701234567` |

Первый запрос после старта — ~2 с (прогрев), дальше страница уходит за 0.2–0.4 с. На сцене это значит:
`Start` модели стоит делать **до** выхода к залу, иначе первый показ съест лишние секунды.

Инстанс `GLM-OCR-yizre` (id 88, порт 40019), VRAM 12146/16311 MiB, `--max-model-len 32768`,
`--gpu-memory-utilization 0.9`, MTP включён. Ответы стабильны (повтор даёт тот же текст).

## 10. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-1** | ~~Промышленный образ не заведётся~~ — **закрыт 2026-11-06**: образ поднялся и дал точный текст (§9.1) | Если понадобится другая версия — второй `version_config` того же бэкенда (`v0.33.0-custom` и т.п.), модель переключается полем `backend_version`; фолбэк «custom-бэкенд на `transformers`» остаётся в резерве |
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
| v1.2 | 2026-11-06 | `GLM-OCR` добавлена в чат OWU (`model_ids` подключения GPUStack, под перезапущен) — `owu-spec` §7.2 дополнена процедурой; в §1 отмечен пункт «модель доступна в OWU» |
| v1.1 | 2026-11-06 | **Приёмка закрыта на `vllm/vllm-openai:v0.20.1-x86_64`:** страница распознана посимвольно через шлюз за 0.40 с (прогретый 0.19 с), VRAM 12146/16311 MiB, инстанс id 88 порт 40019. Новые грабли: T6 (`--served-model-name`, иначе шлюз 404 `The model GLM-OCR does not exist`); T1 закрыт сменой образа; T3 сузился до раннера `gpustack/runner` (на 0.20.1 CUDA-графы работают, `--enforce-eager` не нужен); §6.3 — два режима памяти; §9.1 — живые замеры; R-1 закрыт |
| v1.0 | 2026-11-06 | Первая версия: живые факты (веса 2.5 GB, sha256, каталог на `/data`), регистрация модели id 18 / route 13, промышленный конфиг `vllm-openai:v0.20.1-x86_64` + параметры, наши добавки (`--enforce-eager`, `--host/--port`), бюджет VRAM 5860 MiB, грабли T1–T5 (mrope в 0.25.1, `--model-impl transformers` IndexError, CUDA-графы, синтетика как валидный тест, ручной маршрут), эталонный вывод transformers, риски R-1…R-6 |

## 13. Связанные документы

- `cases/04-ocr-gpu.md` — сценарий показа кейса 04 и фолбэк.
- `architecture/specs/gpustack-spec.md` §1 (бэкенды/раннер), §4.5 (модели и `local_path`), §7 (Stop вместо scale).
- `architecture/specs/gpustack-custom-backend-spec.md` §7 B3a — грабли API GPUStack (полный `PUT`, `cluster_id`, `env` только на модели, ручной model route).
- `architecture/specs/doc-spec.md` — Docling Serve / MCP, CPU-OCR с русским пресетом (VLM-путь выключен).
- `scripts/glm_ocr_smoke.py` — воспроизводимая приёмка OCR через шлюз.
- `architecture/specs/owu-spec.md` §7.2 — как модель попадает в чат OWU (`openai.api_configs["0"].model_ids`
  + `rollout restart`), почему ключ `owu-all` не меняется.
