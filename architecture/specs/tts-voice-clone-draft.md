# Черновик: кейс «Озвучка с клоном голоса» (TTS)

> **Статус: ЧЕРНОВИК.** Не кейс, в `cases/` не добавлен, номер не закреплён. Дата 2026-11-22,
> владелец решения — владелец стенда. Проверки — буква **T**.

## 1. Границы

| | |
|---|---|
| Тезис | синтез и клон голоса живут на одной карте стенда, без внешних сервисов |
| Сценарий | гость диктует 3–10 с → один текст озвучивают **две модели подряд**, разница слышна сразу; второй ход — голос по описанию, без референса |
| Режим | **две модели по очереди** (`Stop`/`Start` из UI, ~2 мин на переключение): `Qwen3-TTS-1.7B-Base` + `CosyVoice3-0.5B`; рядом не живут — см. §3 |
| Не входит | дуплекс, диаризация, LoRA на голос, клоны третьих лиц без письменного согласия (§6) |

## 2. Модели

**Основной — `Qwen3-TTS-12Hz-1.7B-Base`** (Apache-2.0, 4.23 ГиБ, клон по 3 с, 10 языков вкл. русский).
Пруф: [статья Qwen](https://qwen.ai/blog?id=qwen3tts-0115) · [GitHub](https://github.com/QwenLM/Qwen3-TTS) ·
[HF](https://huggingface.co/collections/Qwen/qwen3-tts). Доп. веса того же стека — `1.7B-CustomVoice`,
`1.7B-VoiceDesign`, `0.6B-Base`, `0.6B-CustomVoice`; в сценарий показа отдельными ходами не идут.
Вендорские цифры (WER клона 1.835 %, SIM 0.789, стриминг 97 мс) — для слайда, не для приёмки.

| Модель | Лицензия | Размер | RU | Вердикт |
|---|---|---|---|---|
| **Qwen3-TTS-1.7B-Base** | apache-2.0 | 4.23 ГиБ | да | **основной** |
| Qwen3-TTS-1.7B-CustomVoice / -VoiceDesign | apache-2.0 | 4.21 ГиБ | да | доп. веса |
| Qwen3-TTS-0.6B-Base / -CustomVoice | apache-2.0 | 2.34 / ≈2.3 ГиБ | да | доп.: запас памяти |
| Fun-CosyVoice3-0.5B-2512 | apache-2.0 | ≈1–2 ГиБ | да | резерв |
| CosyVoice2-0.5B; CosyVoice-300M/-SFT/-Instruct | apache-2.0 | 4.52; 2.44/2.44/2.14 ГиБ | да | наследие 2024, качества не хватит |
| Voxtral-4B-TTS-2603 | **cc-by-nc-4.0** | 7.49 ГиБ | **нет** | **исключена**: non-commercial + нет русского |
| Dia-1.6B | apache-2.0 | 12.00 ГиБ | **нет** (en only) | **исключена** |
| VibeVoice-1.5B / -Realtime-0.5B | mit | 5.04 / 1.9 ГиБ | **нет** (`en`/`zh`; `en`) | **исключены для TTS**: лицензия лучшая, русского нет |
| Fish-Speech S2 Pro | research-only, gated | 12 ГиБ fp8 | да | **исключена** по лицензии |
| VibeVoice-7B | — | — | — | нет в открытом доступе (`401`) |

Лицензии и языки — HF API, 2026-11-22. Отдельно: `microsoft/VibeVoice-ASR` (MIT, 8.67B, 16.16 ГиБ, **ru**,
диаризация «кто/когда/что», 60 мин за проход) — кандидат на закрытие **R-S7** в `spk-spec.md`, но в карту
15.93 ГиБ в BF16 не влезает; в TTS-кейсе не участвует.

### 2.1 Русский: пруф

**Первичный пруф:** **Table 4** отчёта Qwen-Audio-3.0-TTS — [arXiv 2607.23938](https://arxiv.org/abs/2607.23938),
«CER(%) and WER(%) on the **CV3-Eval Multilingual Voice Cloning** subset», 16 языков
(`zh en ja ko de es fr it ru ar id pt th vi ms tl`), русский — девятая колонка, метрика **WER**.
Сам бенчмарк: [`QwenAudio/CV3-Eval`](https://github.com/QwenAudio/CV3-Eval) — Apache-2.0, 197 ★, описан в
статье CosyVoice 3 (arXiv 2505.17589); данные — Common Voice, FLEURS, EmoBox и веб-краулинг; метрики
CER/WER (Whisper-large-v3 / Paraformer), SIM (ERes2Net), DNSMOS.
Пересказ с таблицей — [Хабр, 15.09.2026](https://habr.com/ru/companies/yandex_praktikum/articles/1080414/),
раздел «Русский» (Иванов А., @ivnvalex).

| Система | WER на русском ↓ | Доступность |
|---|---|---|
| Qwen-Audio-3.0-TTS | **4,68** | закрыт: веса только по API (Flash / Plus) |
| ElevenLabs-v3 | 5,38 | облако |
| MiniMax-Speech-2.8-HD | 5,39 | облако |
| **VoxCPM2** (apache-2.0, 2B, 48 кГц, ru) | **5,97** | открыт, 4.62 ГиБ — **в каталоге GPUStack нет** (конфиг `voxcpm2.yaml` в раннере есть), поэтому на сцене его заменил `CosyVoice3-0.5B` |
| CosyVoice3-1.5B | 6,64 | карточки на HF нет |
| `CosyVoice3-0.5B` | 6,77 | открыт, в каталоге — **вторая модель** |
| **Qwen3-TTS-1.7B-Base** | **7,40** | наш основной |
| Dots.TTS-2B | 14,0 | отпадает |

Оговорка автора разбора: CER/WER — это ASR задом наперёд (человеческая речь в том же бенчмарке дала 1.26
против 0.84 у модели), поэтому читается только **разница** между системами на одной задаче. Плюс это одна
подвыборка (multilingual clone), а не весь бенчмарк. Вывод: основной на русском не лидер, победителя
определяет живое сравнение двух моделей на сцене, а не чужая таблица.

### 2.2 Упоминание: файнтюн с ударением

Базовая модель знака ударения не понимает (`за́мок`/`замо́к`); поверх 1.7B-Base есть apache-2.0 веса
`sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf` и `siriusfreak/…ru-stress-cf` — в кейсе не участвуют.

## 3. Бюджет VRAM — замер 2026-11-22 (по [ADR-0007](../../adr/adr-0007-model-roster-and-gpu-budget.md))

Замер, не расчёт: RTX 5070 Ti, vLLM видит 15.47 ГиБ. vllm-omni держит **пул на каждую стадию**
(дробь от карты), а не claim от весов:

| Модель | Пулы стадий (дефолт) | Факт в `nvidia-smi` |
|---|---|---|
| `Qwen3-TTS-1.7B-Base` | 0.3 talker + 0.3 code2wav | 7650 + 6015 MiB ≈ **13.3 ГиБ** |
| `CosyVoice3-0.5B` | 0.4 talker + 0.2 flow/code2wav | 6918 + 2474 MiB ≈ **9.2 ГиБ** |

Сумма ≈ 22.5 ГиБ > 15.47 → **две модели одновременно на одной карте не живут**. Расчёт из первой
редакции (12.7 ГиБ на пару) неверен: он считался от весов, а не от пулов. Урезание пулов через
`--stage-overrides` бьёт в пол: talker `Qwen3-TTS` весит 1.92 ГиБ, при пуле 0.16 остаётся
`Available KV cache memory: 0.0 GiB` → падение стадии.

## 4. Разворачивание — только каталог GPUStack

Кастомный бэкенд и свой образ исключены (решение владельца 2026-11-22): в каталоге есть
`qwen3-tts-12hz-1.7b-base`.

| Элемент | Решение |
|---|---|
| Источник | каталог GPUStack → `Catalog` → GPUStack-модель; **две**: `qwen3-tts-12hz-1.7b-base` (id 19) и `Fun-CosyVoice3-0.5B-2512` (id 20) | 
| Раннер | **`gpustack/runner:cuda13.0-vllm0.22.1`** — каталожный `vLLM 0.22.1` + `--omni`; 0.25.1 не нужен (`--omni` есть в 0.22.1), образ 9.85 ГБ тянется с docker.io ~6 мин |
| Веса | GPUStack сам качает с HF в `/var/lib/gpustack/cache/huggingface/<repo>/` (Qwen3-TTS 4.23 ГиБ, CosyVoice3 1.9 ГиБ); `local_path` и копирование по LAN не нужны |
| Claim VRAM | считать **не** от весов, а от пулов стадий — §3; фактический расход 13.3 и 9.2 ГиБ |
| Диск | 4.23 + 1.9 ГиБ весов + раннер 9.85 ГБ (сжатый); k8s-04: `/data` — **236 ГБ свободно** (замер 2026-11-22; образы containerd и веса GPUStack — bind-mount `/data`, root для них не критичен) |
| Публикация | обе — как ещё одна модель на `api.demo-ai-lab.ru`: по `ModelRoute` на каждую, никакого отдельного хоста и маршрута Higress; ключ API с доступом к обеим |
| Сцена | `Model Service → Deployments → Start/Stop`; ничего не ставится и не скачивается |
| Референсы, согласия | эталон `tts-voice-clone-ref-01.wav` — рядом со спекой (8.08 с, 16 кГц mono; решение владельца 2026-11-22, осознанное исключение из HYGIENE). В кластере — PVC 5Gi Longhorn RWO: `voices/<id>.wav` + `<id>.txt` + `consent.yaml`; без записи согласия голос не грузится |
| UI | своего нет: показ через `api.demo-ai-lab.ru` — модель доступна как ещё одна OpenAI-совместимая модель GPUStack (`curl`/скрипт зала) |
| Кэш | sha256(text+voice+params) → wav, LRU 2 ГБ |

## 5. Контракт (фактический, vllm-omni 0.22.1)

```
POST /v1/audio/speech
{ "model": "Qwen3-TTS-1.7B-Base" | "CosyVoice3-0.5B",
  "input": "текст", "language": "Russian", "response_format": "wav",
  "ref_audio": "data:audio/wav;base64,…" | "http(s)://…",
  "ref_text": "транскрипт референса",          // CosyVoice3 — обязателен
  "x_vector_only_mode": true }                  // Qwen3-TTS Base — вместо ref_text
→ 200 audio/wav (24 кГц, mono) · 400 при отсутствии ref_text/x_vector_only_mode
```

Реестра голосов (`voice: <id>`) в этой версии нет: голос задаётся референсом в каждом запросе,
предвычисленные голоса — через `POST /v1/audio/voices` (см. speech-api vllm-omni).

## 6. Чего не делаем

- Клонирование третьих лиц и публичных людей без письменного согласия — стенд публичный.
- Fish S2 Pro даже «для демо» — research-only.
- Диаризация и дуплекс — вне тезиса (R-S7 закрыт решением в `spk-spec.md`).
- LoRA на голос — отдельный бюджет VRAM.

## 7. Замер 2026-11-22: один текст, обе модели

Обе модели подняты из каталога на k8s-04 (`cuda:0`, RTX 5070 Ti), по очереди — одновременно не
влезают (§3). Один и тот же референс `tts-voice-clone-ref-01.wav` и один текст, **542 знака**:

> ASUS Dual GeForce RTX 5060 Ti White Edition сочетает в себе высокую эффективность охлаждения и
> широкую совместимость. Передовые решения охлаждения, характерные для флагманских видеокарт,
> включают два вентилятора Axial-tech для оптимизации воздушного потока к радиатору. Видеокарта
> выполнена в компактном 2,5-слотовом форм-факторе, обеспечивающем большую производительность в
> меньшем пространстве. Эти усовершенствования делают ASUS Dual идеальным выбором для геймеров,
> которым нужна мощная графическая производительность в компактном корпусе.

| | `Qwen3-TTS-1.7B-Base` | `CosyVoice3-0.5B` |
|---|---|---|
| Запрос | `task_type: Base`, `x_vector_only_mode: true` (без `ref_text`), `language: "Russian"` | `ref_audio` + `ref_text` (обязателен), `language: "Russian"` |
| Звук | **39.60 с**, 24 кГц mono | **29.76 с**, 24 кГц mono |
| Время ответа | **34.6 с** (≈0.9× реального времени) | **13.5 с** (≈0.45×) |
| Старт модели | ~2 мин после прогретых весов | ~2 мин |
| Файл | `tts-demo-qwen3-tts-1.7b-base.wav` (1.9 МБ) | `tts-demo-cosyvoice3-0.5b.wav` (1.4 МБ) |

`language` — поле запроса (для Qwen3-TTS: `Auto` по умолчанию + Chinese/English/Japanese/Korean/German/
French/**Russian**/Portuguese/Spanish/Italian из `talker_config.codec_language_id`); без него модель
угадывает язык сама. `language: "Russian"` проверили на обеих моделях в этом тексте — принято, 200.

`ref_text` для CosyVoice3 в этом прогоне — условный: настоящего транскрипта референса нет, поэтому
клон-качество Cosy в этих файлах **не показательное**; сравнение по звуку — после записи `ref_text`
(отдельный пункт ниже).

### 7.1 Что ускоряет прогон

- **Прогретые веса и `torch_compile_cache`** (`/var/lib/gpustack/cache/vllm/`) → старт модели ~2 мин;
  первый в жизни старт + скачивание весов и образа — ~9 мин (образ 9.85 ГБ, 6 мин только pull).
- **Первый запрос после старта в 3–10 раз дольше** тёплого (Qwen3-TTS: 45 с → 3 с на короткой фразе);
  на сцене — прогрев одной фразой до показа.
- **CosyVoice3 быстрее в скорости синтеза** (0.54× реального времени против 1.0× у 1.7B) — при равном
  тексте 17 против 36 с; 0.6B-варианты Qwen3-TTS на 542 знака не проверялись.
- Разовое ускорение — `--max-num-seqs`/`enforce_eager`: у Cosy eager уже включён дефолтом, у Qwen3-TTS
  stage 0 идёт с cudagraph; трогать не стали, замер сделан на дефолтах.

### 7.2 Что осталось

1. Настоящий транскрипт референса (`voices/<id>.txt`) → перегенерировать файл Cosy и сравнить на слух.
2. Согласие владельца: чей голос в референсе, как цитируется согласие.
3. Номер кейса и место в программе. **Сейчас не закреплён.**

## Источники (2026-11-22)

- `qwen.ai/blog?id=qwen3tts-0115` — анонс Qwen3-TTS (Base / CustomVoice / VoiceDesign, 0.6B/1.7B, 10 языков, стриминг 97 мс).
- `github.com/QwenLM/Qwen3-TTS` — Apache-2.0, 14.6k ★; веб-UI, путь через vLLM, FA2.
- `huggingface.co/collections/Qwen/qwen3-tts` — все карточки apache-2.0; загрузки: 1.7B-Base 4 160 912, CustomVoice 1 080 736, 0.6B-Base 857 867, VoiceDesign 675 739.
- Размеры — HF API: 1.7B-Base 4.23 ГиБ (3.59 + 0.64 tokenizer), 0.6B-Base 2.34 ГиБ.
- **Первичный пруф по русскому:** `arxiv.org/abs/2607.23938`, Table 4 — WER/CER на CV3-Eval Multilingual Voice Cloning, 16 языков, `ru` — девятая колонка: Qwen-Audio-3.0-TTS 4.68 · ElevenLabs-v3 5.38 · MiniMax 5.39 · VoxCPM2 5.97 · CosyVoice3-1.5B 6.64 · CosyVoice3-0.5B 6.77 · Qwen3-TTS-1.7B-Base 7.40 · Dots.TTS-2B 14.0 (сверено по HTML-версии статьи).
- `github.com/QwenAudio/CV3-Eval` — бенчмарк: Apache-2.0, 197 ★, push 2025-08-25; Common Voice + FLEURS + EmoBox + веб-краулинг; подмножества multilingual / cross-lingual / emotion clone; метрики CER/WER, SIM (ERes2Net), DNSMOS; код `run_infer_cv3_eval.sh`.
- `habr.com/ru/companies/yandex_praktikum/articles/1080414` — Иванов А. (@ivnvalex), 15.09.2026: пересказ Table 4 с разделом «Русский» и оговоркой про метрику.
- `arxiv.org/abs/2505.17589` — CosyVoice 3, где CV3-Eval и определён.
- `huggingface.co/openbmb/VoxCPM2` — apache-2.0, 2B, 30 языков, 48 кГц, 4.62 ГиБ.
- `huggingface.co/sknyazev/…ru-stress-gguf`, `…/siriusfreak/…ru-stress-cf` — apache-2.0, ударение.
- Шорт-лист: Voxtral `cc-by-nc-4.0` без ru · Dia `en only` · CosyVoice2/300M apache с ru.
- VibeVoice (MIT): 1.5B 5.04 ГиБ `en/zh` · Realtime-0.5B 1.9 ГиБ `en` · ASR 16.16 ГиБ, ru + диаризация · 7B `401`.
- `huggingface.co/fishaudio/s2-pro` — Fish Audio Research License, gated.
