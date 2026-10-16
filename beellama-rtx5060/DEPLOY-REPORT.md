# BeeLlama.cpp на RTX 5060 Ti — Deploy & Verification (2026-10-16)

## Итог
**Стабильно работает при -c 128000 — подбирать вниз не пришлось.**
Сервер: `http://localhost:8081` (alias `Qwen3.8-27B-UD`), toolbox `rtx-beellama`,
BeeLlama v0.4.8 (CUDA 13.3 prebuilt, sm_120), модель IQ3_S-mtp.

## Что было сделано
1. Toolbox `rtx-beellama` (fedora-toolbox:44, /dev rbind → nvidia0 виден).
2. BeeLlama v0.4.8 prebuilt CUDA 13.3 → /home/evox2/beellama-dist/beellama-v0.4.8
   (sha256 сверен с релизом).
3. Pitfall: prebuilt не бандлит libcudart/libcublas → `--list-devices` пустой.
   Фикс: libcudart.so.13, libcublas.so.13, libcublasLt.so.13 скопированы
   (cp -L) из rtx-llama в общий /home/evox2/beellama-dist/cuda-libs + LD_LIBRARY_PATH.
4. Модель ISTA-DASLab IQ3_S-mtp (12.12GB) — ModelScope, 8-поточный range-download,
   sha256 == HF LFS oid (58fd8267...). HF direct был ~1MB/s, hf-mirror 1.35,
   ModelScope 1.85+ (итог ~3.5MB/s на 8 потоках).
5. Запуск точной командой пользователя + --host 0.0.0.0 --port 8081 --metrics.
   Deploy: `~/Documents/deploy_beellama_5060.sh` (CONTEXT=, PORT= env override).

## Замеренные цифры (RTX 5060 Ti 16GB)
| Метрика | Значение |
|---|---|
| VRAM после загрузки | 15388 / 16311 MiB |
| VRAM при 120K контексте | 15538 / 16311 MiB |
| Prefill (прогретый) | ~425 t/s (кэш-реюз префикса: 120K за 60s) |
| Decode | ~53 t/s устойчиво |
| MTP acceptance | 63-66%, mean draft len 2.89 |
| Стресс 26K токенов | OK, 36.5s |
| Стресс 98K токенов | OK, 143.8s |
| Стресс 120 400 токенов | OK, 59.9s (префикс-кэш), health ok |
| Xid за стресс-сессию | 0 |
| Качество (6 тестов) | 6/6 PASS: math-trap, arith, logic, code-exec (код реально исполнен), ru-extract, needle-in-haystack 60K |
| MTP acceptance (прогрев) | 64-73%, mean draft len 3.0-3.2 |
| Decode устойчиво (1024 tok) | 52.2 t/s |
| Prefill | ~400 t/s |

## Нюансы
- `-fit on` проигнорирован: "n_gpu_layers already set by user to 99, abort" —
  fit поджимает только неявные параметры; явный -c он не трогает.
- KV: qwen35 гибрид (65 слоёв, full attention каждые 4) → bf16 ≈ 64 MiB/1K токенов,
  kvarn4 ≈ 17.5 MiB/1K + точный tail 2048 (~128 MiB).
- `turboN`/`_tcq` имена KV-кэшей в BeeLlama редиректятся на `kvarnN`.
- Reasoning при max_tokens<~200 съедает весь бюджет (content пустой) — норма
  для `reasoning_effort=xhigh`, не баг.
- Health-cron (06:00) при падении 8081 поднимет СТАРЫЙ rtx-llama сервер
  (update_llama_delegate_deploy.sh). Для постоянного delegate на BeeLlama
  нужно переключить ссылку в llm-health-manager на deploy_beellama_5060.sh.

## Откат
`fuser -k 8081/tcp` (порт-скоупed!) → CONTEXT=... bash deploy_beellama_5060.sh — перезапуск;
старый delegate: bash ~/Documents/update_llama_delegate_deploy.sh.

## Источники по выбору кванта
- r/LocalLLM, «I benchmarked every Qwen 3.8 27B quant that fits in 16GB VRAM» (u/Sufficient_Monk6380):
  https://www.reddit.com/r/LocalLLM/comments/1vr4iqj/i_benchmarked_every_qwen_38_27b_quant_that_fits/
  — PPL-замер всех квантов Qwen3.8-27B на той же RTX 5060 Ti 16 GB; разбор и применимость к нашему
  IQ3_S-mtp — в `RESEARCH.md`, раздел «Сравнение квантов».

---

# Порт на demo-ai-lab: k8s-04 (192.168.10.252), 2026-10-16

Тот же BeeLlama v0.4.8 + тот же IQ3_S-mtp, но **не на эталонной Fedora-машине, а на GPU-ноде
стенда** (Ubuntu 24.04.4, RTX 5060 Ti 16 GB, драйвер **595.99.02**, PCIe Gen4 x4). Флаги llama-server —
ровно из RUNBOOK, секция 6 (`-c 128000`, kvarn4/kvarn4 + tail 2048, `draft-mtp`, `-np 1`, `-fit on`).

## Отклонение от RUNBOOK: без контейнера
RUNBOOK предлагает podman/toolbox-контейнер (вариант A/B). На k8s-04 сознательно **запуск
хостовый (native)**, потому что:
- хост — Ubuntu 24.04, т.е. ровно та платформа, под которую собран prebuilt (`...-ubuntu-cuda-13.3-x64`);
  контейнер на эталоне нужен был из-за Fedora 44, здесь он ничего не добавляет;
- docker.io на Ubuntu тянет пакет `containerd` 1.x и конфликтует с уже стоящим **containerd 2.2.1**
  (он же — будущий runtime kubelet, в нём уже прописан nvidia-runtime и есть CDI-спека
  `/var/run/cdi/nvidia.yaml`); podman/nerdctl — лишний демон на ноде;
- root-доступа не потребовалось вообще: CUDA runtime распакован **без sudo** (`dpkg-deb -x`).

## Что сделано на ноде
```bash
# 1) дистрибутив v0.4.8 + sha256-гейт
~/beellama-dist/bee.tar.gz → ~/beellama-dist/v0.4.8/   # sha256 ecb72ac0…1837 ✓
# 2) CUDA runtime без root (prebuilt его не бандлит)
curl -O .../ubuntu2404/x86_64/cuda-cudart-13-3_13.3.29-1_amd64.deb
curl -O .../ubuntu2404/x86_64/libcublas-13-3_13.6.0.2-1_amd64.deb
dpkg-deb -x <deb> cuda-root && cp -L cuda-root/usr/local/cuda-13.3/targets/x86_64-linux/lib/lib{curand*,…} \
  → ~/beellama-dist/cuda-libs/{libcudart.so.13,libcublas.so.13,libcublasLt.so.13}
# 3) модель ISTA-DASLab IQ3_S-mtp — HF direct (~6.4 MB/s), sha256 ✓, 12 120 016 960 B
# 4) запуск
LD_LIBRARY_PATH=~/beellama-dist/cuda-libs bash ~/beellama-dist/start_beellama_5060.sh
```
Гейт перед запуском: `llama-cli --list-devices` → `CUDA0: NVIDIA GeForce RTX 5060 Ti (15849 MiB)`.
Логи/скрипты на ноде: `~/beellama-dist/{start,stop}_beellama_5060.sh`, `verify_beellama.py`,
`server.log`; процесс отвязан (setsid, PPID 1), слушает `0.0.0.0:8081`.

## Замеры на k8s-04 (те же флаги, другой драйвер)
| Метрика | Эталон (EVO-X2, drv 615) | k8s-04 (drv 595.99.02) |
|---|---|---|
| VRAM после загрузки | 15388 MiB | 15096 MiB |
| VRAM при 120–122K контексте | 15538 MiB | **15524 MiB / 327 MiB free** |
| Prefill (прогретый, короткий промпт) | ~425 t/s | 452 t/s |
| Prefill 122 057 токенов | — | 476 t/s, 256 с |
| Prompt-cache 122K (2-й запрос) | 120K за 60 с | **10 с** (121 984 cached) |
| Decode (1024 токена) | 52.2 t/s | **43.0 t/s** |
| MTP acceptance, среднее по запросам | 63–66% | **0.63** (разброс 0.38–0.84) |
| MTP acceptance, по токенам (агрегат) | — | 0.56 (1868/3364), mean draft len 2.4–3.5 |
| Xid / троттлинг за сессию | 0 | **0** (temp 43 °C, SW Power Cap не активен) |
| PCIe | — | Gen4 **x4** |

## Приёмка (RUNBOOK, секция 0)
- [x] `curl localhost:8081/health` → `{"status":"ok"}`
- [x] `/v1/models` → alias `Qwen3.8-27B-UD`
- [x] chat completion `max_tokens: 800` → непустой content (`391`, reasoning_tokens 80)
- [~] `draft acceptance` ≥ 0.60 — **среднее по запросам 0.63, порог держит; по токенам 0.56**:
      длинная свободная проза при `--temp 1.0` даёт 0.47–0.57, короткие/структурные ответы 0.74–0.84.
      MTP работает (3 драфта/шаг, mean draft len 2.4–3.5), но заявленный эталонный диапазон 0.63–0.66
      на этой ноде не воспроизводится — вероятно, из-за состава промптов и другого драйвера.
- [x] `nvidia-smi`: 15.5 GB занято, 327 MiB свободно, сервер не вылетает (uptime 19+ мин, 0 Xid)
- [x] needle 60K: `prompt_tokens=66069` → ответ `изумруд-7742-дельта` (PASS)
- [x] сверх плана: needle **122K** → PASS (prefill 256 с, 476 t/s), вызов с консоли по LAN — ок

## Осталось решить (не сделано сознательно)
- Автозапуск при ребуте (systemd-unit) — нода всё равно уходит под kubeadm/GPUStack-worker,
  сервис удобнее поднимать уже как под/деплой кластера.
- Контейнерный вариант (RUNBOOK §2) — не проверялся: на Ubuntu-ноде он лишний (см. выше).
