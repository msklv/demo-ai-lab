# ADR-0007: Модели и бюджет видеопамяти на узле k8s-04

- Дата: 2026-10-24 · Статус: **Accepted** · Ревизии:
  **2026-10-25** — страж → 780M, ASR → 5060 Ti, 780M переведён на vLLM-only.
  **2026-10-27** — диск k8s-04 расширен 150 → 210 GB (`lvextend -r -L +60G`; ФС 207 GB, свободно 109 GB).
  **2026-10-28** — «резервной модели нет, переключение моделей на демо не показывается».
  **Ревизия 2026-11-02 (решение владельца): замена LLM на сцене — основное движущее звено демо.**
  Решение 2026-10-28 о «непоказе» переключений **отменено**: набор на 5060 Ti меняется под каждый кейс
  (человек в UI GPUStack, `Stop/Start`). Поэтому этот ADR держит **бюджет VRAM и правила сосуществования
  моделей**, а состав набора на конкретный кейс — программа показа (`cases/README.md`). Тем же решением:
  страж на 5060 Ti исполняет **`Qwen3Guard-Gen-4B`** (`util 0.80`, ≈12.7 GiB), в кейсе 03 (рядом с ASR) —
  **0.6B** под тем же внешним ID модели; на 780M страж не ставится. Пересмотр состава — новым ADR.
  **Ревизия 2026-11-03 — RAG-пара заведена в GPUStack кастомным бэкендом; UMA 3 → 8 GiB.** Планировщик
  GPUStack видит у APU только BIOS-карв-аут VRAM (оператор 0.5.4 читает `mem.Total` из amdsmi, GTT и
  `unified` не понимает), поэтому 3-ГиБ карта отвергала любую модель; UMA поднят до **8 GiB** (BIOS,
  `Frame Buffer Size`), ОС видит **23.26 GiB**, потолок GTT **11.63 GiB**. Пара `bge-m3` +
  `bge-reranker-v2-m3` теперь модели GPUStack (бэкенд `vllm-rocm-igpu-custom`, образ
  `runner:rocm7.2-vllm0.25.1` с `HSA_OVERRIDE_GFX_VERSION=11.0.0` — наш wheel не понадобился),
  замер: GTT **2.77 GiB** на обе, `/v1/embeddings` 200 (dim 1024), `/v1/rerank` 200. Позже в тот же день
  `--max-num-seqs` снижен **32 → 8**: ингест ~490 чанков дал `amdgpu: MES failed to response msg=3` →
  `GPU reset(3)` и пересоздание инстанса. Механика и грабли —
  `architecture/specs/gpustack-spec.md` §4.6. Пересмотр состава — новым ADR.

## Видеокарты узла k8s-04

| Ускоритель | Тип памяти | Объём | Архитектура |
|---|---|---|---|
| **RTX 5060 Ti** | VRAM (дискретная) | 16 GB = **15.93 GiB** | sm_120 (Blackwell), CUDA 13 |
| **Radeon 780M** (iGPU в Phoenix APU) | UMA: GTT из системной DDR5 | с 2026-11-03 BIOS UMA = **8 GiB** (карв-аут VRAM — именно его видит GPUStack), ОС видит **23.26 GiB**, потолок GTT **11.63 GiB** (авто = 50% RAM); под инференс планируем те же 8 GiB | gfx1103 (RDNA3) |

Софт: **vLLM 0.25.1** — на 5060 Ti сборка под CUDA 13 (драйвер 595.99.02), на 780M собственный
ROCm 10.0.0 wheel (`v0.25.1-rocm10.0.0-gfx1103-gfx1100-verified`). На k8s-01/02/03 iGPU того же типа
есть, но для инференса не используем: vLLM `gfx1103` официально не поддерживает.

## vLLM на AMD (gfx1103): что работает и где гвозди

**Статус апстрима:** `gfx1103` не в официальном списке GPU vLLM (там `gfx90a/942/950`, `gfx1100/1101/1102`,
`gfx1200/1201`, `gfx1150/1151`). Ядра под gfx1103 в коде есть с v0.20 (PR #40037, влит 2026-04-23),
но сборка и запуск — на свой риск.

**Проверенный артефакт** (использовать только его): git-тег `v0.25.1-rocm10.0.0-gfx1103-gfx1100-verified`
в `msklv/vllm-gfx1103`, релиз `build-v0.25.1-rocm10.0.0-gfx1103-gfx1100`, wheel 68.5 MB,
sha256 `cd53886a…` (сверять с `MANIFEST.txt`). Собран в CI из апстрима v0.25.1 на `rocm/vllm-dev:base`
→ ROCm 10.0.0 / torch 2.13.0+rocm10.0.0, `PYTORCH_ROCM_ARCH="gfx1103;gfx1100"`.

**Что умеет** (проверено на 780M): генерация (60 tok/s на 0.6B), эмбеддинги `/v1/embeddings`
(2841 tok/s), реранк `/rerank` (Cohere-совместимый, 4 пары за 515 мс), транскрипция
`/v1/audio/transcriptions` (`WhisperForConditionalGeneration`). **TTS нет.**

**Гвозди (каждый проверен на железе):**

1. **Две архитектуры в одном wheel.** У официального torch нет кодобъектов gfx1103 → без override
   падает уже `torch.randn` (`hipErrorInvalidKernelFile`); с `HSA_OVERRIDE_GFX_VERSION=11.0.0`
   устройство рапортует `gfx1100`, и тогда wheel «только gfx1103» даёт `hipErrorInvalidImage`.
   Итог: собирать `gfx1103;gfx1100`, запускать с override.
2. **`HSA_OVERRIDE_GFX_VERSION=11.0.0` обязателен** — иначе torch не работает.
3. **Под в k8s:** `privileged: true` + `hostPath` `/dev/kfd` и `/dev/dri`. Одного `runAsUser: 0` мало:
   device-cgroup не пускает, HIP молча не инициализируется (`torch.cuda.is_available() == False` без ошибки).
4. **GPU Hang на щедрых флагах:** `--max-model-len 2048 --gpu-memory-utilization 0.35` + prefix-caching
   по умолчанию → после загрузки весов `HW Exception … GPU Hang` и `amdgpu: GPU reset`.
   Рабочая комбинация: `--enforce-eager --max-model-len 1024 --gpu-memory-utilization 0.25
   --no-enable-prefix-caching`.
5. **`VLLM_ATTENTION_BACKEND` игнорируется** (0.25.1): в логе всё равно `Overriding with ROCM_ATTN`.
6. **Стабильных ROCm-wheels для 0.20+ нет** (только 0.14–0.18 и nightly) → сборка из исходников,
   32–48 мин на 4 vCPU.
7. **Память — GTT, не VRAM:** профилировка идёт от UMA, поэтому `gpu-memory-utilization` держим ≤0.25,
   а планируемую границу задаём `memory.max` на поды.
8. Страж с 2026-11-02 на этой карте не живёт, а на внешнем маршруте он **fail-closed** (`failOpen: false`,
   `ai-qwen-guard`): недоступный страж — `503 guard unavailable`, а не пропуск без проверки
   (`architecture/specs/llm-proxy-spec.md` §P5). Прежняя формулировка «fail-open на 780M» отменена ревизией 2026-11-02.

## Наборы на RTX 5060 Ti (15.93 GiB) — переключаются по кейсам

Переключение делает человек в web-интерфейсе GPUStack (`Model Service → Deployments → Stop/Start`);
скриптов и `kubectl scale` нет намеренно (состояние живёт в БД GPUStack). Сетка переходов и время —
`cases/README.md`; здесь — бюджет и правила.

| Кейс | Что включено на 5060 Ti | Σ VRAM | Правило |
|---|---|---|---|
| 01 | `Qwen3.8-27B-UD` (BeeLlama custom backend, IQ3_S + kvarn4, ctx 128000) | 15.1–15.6 GiB | **только эксклюзивно**: custom backend не заявляет VRAM планировщику, любой сосед = CUDA OOM (R-B1) |
| 02 / 05 / 06 | страж `Qwen3Guard-Gen-4B` (внешний ID модели) | ≈12.7 GiB | страж и локальная модель на одной карте не живут вместе |
| 03 | страж `Qwen3Guard-Gen-0.6B` (тот же внешний ID) + `whisper-turbo` (`faster-whisper` int8) | ≈3.7 GiB | `4B` рядом с ASR не оставляет VRAM: проверено 02.11 — `whisper-turbo` уходит в `replicas=0`, транскрибация `404` |
| 04 | `GLM-OCR` (VLM) | 3–6 GiB (уточнить по карточке) | **модели в каталоге GPUStack ещё нет** — кейс 04 не готов |
| вне сцены | `gemma-4-12B` (util 0.68) + ASR (util 0.15) | 14 943 из 16 311 MiB | резерв/фолбэк; в программе показа не участвует |

Замер 02.11.2026 (gemma + ASR): чат 12 668 MiB + ASR 2 294 MiB; всего на карте 14 943 MiB (замер-оф-рекорд, `architecture/specs/gpustack-spec.md` — слагаемые не дают сумму, учтён оверхед раннеров). `whisper-large-v3` f16 (3.75 GiB)
вместо turbo не берём: запас падает до 0.58 GiB → OOM на пиках.

### Почему `util 0.80` у стража и `0.68` у чата

vLLM резервирует память по util-фракции, и `--max-model-len` её не освобождает: при 0.75 рядом с ASR
`vox-box` падал `CUDA failed with error out of memory` (28.10.2026), поэтому чат идёт на 0.68.
Стражу ASR не нужен — он забирает карту целиком (0.80); отсюда правило «либо страж, либо локальная модель».

## Модели на Radeon 780M (GTT 8 GiB) — только RAG

Страж с 2026-11-02 на 780M **не ставится** (решение владельца): на карте живут эмбеддинги и реранк.

| Роль | Модель | Задача vLLM | Веса на диске | GTT факт (замер 2026-11-03) |
|---|---|---|---|---|
| **Эмбеддинги** | `BAAI/bge-m3` | `--runner pooling --convert embed` | `bge-m3-fp16` 1.08 GiB | 1.37 GiB (один инстанс) |
| **Реранк** | `BAAI/bge-reranker-v2-m3` | `--runner pooling --convert classify` | `bge-reranker-v2-m3-fp16` 1.08 GiB | ~1.4 GiB; пара вместе — **2.77 GiB** |

Обе — модели GPUStack через **кастомный бэкенд** `vllm-rocm-igpu-custom` (имя обязано кончаться на
`-custom`), образ `gpustack/runner:rocm7.2-vllm0.25.1` + `HSA_OVERRIDE_GFX_VERSION=11.0.0`; наш
`msklv/vllm-gfx1103` **не понадобился** (в образе есть gfx1100-ядра, карта под override рапортует gfx1100).
Флаги — только через `backend_parameters` (per-model `run_command` GPUStack игнорирует):
`--served-model-name <имя> --convert embed|classify --enforce-eager --max-model-len 4096 --max-num-seqs 8
--gpu-memory-utilization 0.12 --no-enable-prefix-caching`. Веса fp16 — не косметика: claim VRAM у GPUStack
считается от размера файлов (fp32-каталог = 3.04 GiB и не влезает, fp16 = 1.77 GiB).
`--max-num-seqs` снижен 32 → 8 после инцидента 2026-11-03: при ингесте ~490 чанков ядро дало
`amdgpu: MES failed to response msg=3` → `GPU reset(3)`, инстанс пересоздан, клиент получил
`Server disconnected` (механика и следующий шаг `HSA_ENABLE_SDMA=0` — `gpustack-spec.md` §4.6, гвоздь 5).
llama.cpp/whisper.cpp на узле не остаются.

## Бюджет видеопамяти: наборы не складываются

| Карта | Набор | Занято | Лимит | Запас |
|---|---|---|---|---|
| RTX 5060 Ti | кейс 02/05/06 (страж `4B`) | 12.74 GiB | 15.93 GiB | +3.19 |
| RTX 5060 Ti | кейс 03 (страж `0.6B` + ASR) | ≈3.7 GiB | 15.93 GiB | +12.2 |
| RTX 5060 Ti | кейс 01 (27B) | 15.1–15.6 GiB | 15.93 GiB | +0.3…+0.8 |
| RTX 5060 Ti | вне сцены (`gemma` + ASR) | 14 943 MiB | 16 311 MiB | +1.34 |
| Radeon 780M | кейс 05 (`bge-m3` + реранк) | **2.77 GiB** (замер 03.11.2026) | 8 GiB VRAM / 11.63 GiB GTT | +5.2 (по VRAM: 8 − 1.77 × 2 = 4.46) |

Наборы **взаимоисключающие**: сумма по карте не считается, считается худший набор.

Диск 04: root-LV расширен 27.10.2026 до 210 GB, затем **03.11.2026 ещё `+100%FREE` → 223.89 GiB**
(ФС 220 GB), **свободного места в VG больше нет (0)** — следующий прирост только освобождением.
Живой замер 03.11.2026 (вечер, после запуска пары): занято 130 GB, **свободно 81 GB**. Куда уходит занятое:
`/var/lib/containerd` 68 GB (17 блобов + **51 GB overlayfs-снапшотов**; было 90 — GC собрал снапшоты
снятых образов после пулла раннера), `/var/lib/gpustack` 44 GB (модели 31 + HF-кэш 9.9 + fp16-копии 2.2),
`/home/msklv03` 15 GB (окно теста BeeLlama: `.gguf` 11.3 ГиБ — **файл с двумя хардлинками**, второй в
`/var/lib/gpustack/models/beellama-qwen38`, в сумме занятого считать один раз), `/var/tmp/gfx1103-work` 1.5 GB.
Перед добавлением образа — `df -h /` и порог эвикции считать как 15% от текущего размера ФС
(при 220 GB ≈ 33 GB): `ctr -n k8s.io images rm` место **не возвращает** (запись уходит, блобы и
снапшоты остаются), `content prune references` на живой ноде запрещён.
