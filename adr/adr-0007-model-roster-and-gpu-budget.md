# ADR-0007: Модели и бюджет видеопамяти на узле k8s-04

- Дата: 2026-10-24 · Статус: **Accepted** · Ревизии 2026-10-25: страж → 780M, ASR → 5060 Ti,
  780M переведён на vLLM-only. Пересмотр — новым ADR.

## Видеокарты узла k8s-04

| Ускоритель | Тип памяти | Объём | Архитектура |
|---|---|---|---|
| **RTX 5060 Ti** | VRAM (дискретная) | 16 GB = **15.93 GiB** | sm_120 (Blackwell), CUDA 13 |
| **Radeon 780M** (iGPU в Phoenix APU) | UMA: GTT из системной DDR5 | потолок GTT **15.13 GiB** при 32 GB DDR5 (ОС видит 28 GiB); под инференс планируем **8 GiB** | gfx1103 (RDNA3) |

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
8. Fail-open для стража (ADR-0006): если 780M недоступна, Higress пропускает запрос без проверки —
   guardrail мягкий контроль, метрика `guard_bypass_total` + запись в трейс обязательны.

## Модели на RTX 5060 Ti (15.93 GiB)

| Роль | Модель | Квант | Веса | ctx | util | На карте |
|---|---|---|---|---|---|---|
| **Чат-LLM** | `google/gemma-4-12B-it-qat-w4a16-ct` | QAT W4A16 | 9.59 GiB | 8192 | 0.75 | резидентно |
| **ASR** | `openai/whisper-large-v3-turbo` | BF16 | 1.51 GiB | 448 | 0.15 | резидентно |
| Запасная чат-LLM | `cyankiwi/Qwen3.5-9B-AWQ-4bit` | W4A16 ct | 8.47 GiB | 16384 | 0.65 | **не запущена** — веса на диске |

Замена чата на сцене: `Stop` основной → `Start` запасной (11.73 GiB, запас +4.20).
`whisper-large-v3` f16 (3.75 GiB) вместо turbo не берём: запас падает до 0.58 GiB → OOM на пиках.

## Модели на Radeon 780M (GTT 8 GiB)

Все три — в vLLM с wheel из тега выше; llama.cpp/whisper.cpp на узле не остаются.

| Роль | Модель | Задача vLLM | Веса | GTT факт |
|---|---|---|---|---|
| **Страж guardrail** | `Qwen/Qwen3Guard-Gen-0.6B` | generate | 1.41 GiB | 2.13 GiB |
| **Эмбеддинги** | `BAAI/bge-m3` (fp16) | `--runner pooling --convert embed` | 1.14 GiB | ~1.55 GiB |
| **Реранк** | `BAAI/bge-reranker-v2-m3` (fp16) | `--runner pooling --convert classify` | 1.14 GiB | ~1.55 GiB |

## Общий бюджет видеопамяти

| Карта | Занято резидентно | Лимит | Запас |
|---|---|---|---|
| RTX 5060 Ti | **13.91 GiB** (чат 11.60 + ASR 2.31) | 15.93 GiB | **+2.02** |
| Radeon 780M | **5.23 GiB** (страж 2.13 + эмбеддинги 1.55 + реранк 1.55) | 8 GiB (физ. GTT 15.13) | **+2.77** |
| **Итого узел** | **19.14 GiB** | 23.93 GiB заявленных | **+4.79** |

Диск 04 (150 GB, из них 100 GB были исходно): веса 24.80 GB при fp16-конвертации эмбеддингов/реранка
(+ образы 24.40 GB) = 49.20 GB занято, **6.80 GB свободно**; при fp32-весах эмбеддингов/реранка
занято 51.46 GB, свободно 4.54 GB — правило G8 «≥5 ГБ» тогда не держится, поэтому fp16 предпочтителен.
