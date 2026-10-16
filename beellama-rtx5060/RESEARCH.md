# BeeLlama.cpp на RTX 5060 Ti — Research (2026-10-16)

## Что такое BeeLlama (Anbeeld)

- Репо: https://github.com/Anbeeld/beellama.cpp — форк ggml-org/llama.cpp,
  активно поддерживается (релиз v0.4.8 от 2026-10-14, пуш 2026-10-16, 78 форков).
- База: llama.cpp c06f84160, ggml 0.26.0.
- Автор: Anbeeld (anbeeld.com), статьи про KVarN и KV precision tail.

Ключевые фичи (из README + docs/beellama-args.md):
1. **KVarN** — variance-normalized KV-cache quantization: kvarn2..kvarn8,
   независимые ширина K и V (-ctk/-ctv). Приходит на смену TurboQuant: имена
   `turbo2/3/4` и `_tcq` принимаются и редиректятся на kvarnN (warn).
2. **KV precision tail** (`--kv-tail-tokens N`) — последние N токенов хранятся
   точно (f16/bf16) поверх квантованного тела; единый global softmax под
   FlashAttention. KVarN округляет вверх до групп по 128 токенов.
3. **MTP / DFlash / EAGLE3 спекулятивное декодирование**: `--spec-type draft-mtp`,
   отдельный KVarN для draft-кэша (-ctkd/-ctvd), `-ubd` микро-батч драфта,
   адаптивный draft-max (profit controller).
4. Reasoning-loop protection, переработанный prompt reuse / transactional restore.
5. Низкобитные стандартные кэши q2_0..q6_1.

Ladder (Qwen 27B, 64K, RTX 3090): kvarn4/kvarn4 + tail 1024 = 30.1% от bf16
при median KLD 0.000994 (чище q4_0 при меньшем размере).

## sm_120 (Blackwell)

Prebuilt `beellama-v0.4.8-bin-ubuntu-cuda-13.3-x64.tar.gz` содержит в
libggml-cuda.so нативные cubin для sm_120 и sm_121 (проверено strings).
RTX 5060 Ti = sm_120 — определяется: `CUDA0: NVIDIA GeForce RTX 5060 Ti (15941 MiB)`.

## Установка на эту машину

- Toolbox: `rtx-beellama` (fedora-toolbox:44; /dev монтируется rbind — nvidia-устройства видны).
- Бинарник: /home/evox2/beellama-dist/beellama-v0.4.8 (sha256 сверен с релизом).
- Pitfall: prebuilt НЕ бандлит CUDA runtime — `libcudart.so.13`, `libcublas.so.13`
  missing → `--list-devices` пустой. Фикс: скопированы из rtx-llama
  (cuda-toolkit-13-3) в /home/evox2/beellama-dist/cuda-libs + LD_LIBRARY_PATH.
- Драйверные стабы: в свежем toolbox libcuda.so.1 сразу настоящая (112MB),
  preflight на 0-byte stub всё равно в deploy-скрипте (на случай обновления драйвера).

## Модель

ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF → `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`
(12 120 016 960 B = 11.28 GiB), скачана в /home/evox2/models (ModelScope,
8-поточный range-download; HF direct ~1MB/s, hf-mirror 1.35, ModelScope 1.85+).

GGUF header (архитектура qwen35 — гибрид GDN/SSM + full attention):
- 65 слоёв, full_attention_interval=4 (~16 full-attn слоёв), 24 Q heads / 4 KV heads,
  head_dim 256 (K и V), trained ctx 262144, SSM: state 128, groups 16, inner 6144.
- KV только в full-слоях: bf16 ≈ 64 MiB на 1K токенов; kvarn4 ≈ 17.5 MiB/1K.

## Сравнение квантов (внешний источник, для контекста выбора)

- **[I benchmarked every Qwen 3.8 27B quant that fits in 16GB VRAM](https://www.reddit.com/r/LocalLLM/comments/1vr4iqj/i_benchmarked_every_qwen_38_27b_quant_that_fits/)**
  — r/LocalLLM, u/Sufficient_Monk6380 (~авг 2026). Метод: `llama-perplexity` по wikitext-2 (~280k токенов,
  `n_ctx=512`, fp16 KV, Q8_0 за 100%), железо — **та же RTX 5060 Ti 16 GB**. Результаты: Q4_K_M 17.1 GB →
  99.97% от Q8_0; IQ4_XS 14.6 GB → 99.2%; UD-Q3_K_XL 12.5 GB → 97.8%; NVFP4 (14.4 GB) — 96.6% (автор
  называет NVFP4 главным разочарованием: тот же размер, что IQ4_XS, но хуже). MTP-варианты в рейтинг
  сознательно не брались: спекулятивное декодирование lossless — влияет на скорость, не на качество.
- **Как относится к нам:** нашего кванта там нет — `IQ3_S-mtp` (ISTA-DASLab GSQ-RCO, 12.12 GB) по размеру
  ближе к UD-Q3_K_XL (12.5 GB) / UD-IQ3_XXS (11.1 GB), т.е. ожидаемый диапазон «97-98% от Q8».
  Мы выбираем его не по PPL, а по двум свойствам: MTP-heads (обязательны для `--spec-type draft-mtp`) и
  совместимость с KVarN-кэшем. Сам автор треда предупреждает: «quality %» — прокси на ощущение, не оценка
  по задачам; порядок величин надёжен, проценты — нет.

## VRAM-бюджет 16 GB (15941 MiB)

| Компонент | Оценка |
|---|---|
| Веса IQ3_S + MTP heads | 11.28 GiB |
| KV 128K kvarn4 + tail 2048 | ~2.3 GiB |
| Compute buffers + CUDA ctx + draft | ~1.5-2 GiB |
| **Итого** | **~15.1-15.6 GiB / 15.56 GiB** |

Впритык → при OOM снижать -c (128K → 96K → 64K). `-fit on` поджимает
неявные параметры, но явный -c не отменяет.

## Верификация флагов пользователя

Все флаги команды проверены в `llama-server --help` v0.4.8:
--spec-type draft-mtp ✓, --spec-draft-n-max ✓, -ngld ✓, -ctk/-ctv kvarn4 ✓,
--kv-tail-tokens ✓, -fa on ✓, --reasoning on ✓, --reasoning-preserve ✓,
--chat-template-kwargs ✓, -kvu ✓, -fit on ✓.

Deploy: ~/Documents/deploy_beellama_5060.sh (CONTEXT= env override, порт 8081).
