# RUNBOOK: BeeLlama.cpp + Qwen3.8-27B IQ3_S-mtp на RTX 50-й серии (sm_120, 16 GB VRAM)

> **Документ для ИИ-агента.** Ты — исполнитель. Выполни шаги по порядку, проходи
> verification-гейт перед каждым следующим шагом, не выдумывай пути/версии.
> Все checksums и URL проверены на эталонной машине (GMKtec NucBox EVO-X2, RTX 5060 Ti 16GB,
> Fedora 44, driver 615.71.09) 2026-10-16. Адаптируй пути под свою машину, но НЕ меняй
> флаги запуска без причины из раздела «Деградация».

## 0. Миссия и критерии приёмки

Поднять в контейнере llama-server из форка **BeeLlama v0.4.8** (github.com/Anbeeld/beellama.cpp)
с моделью **Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp** (12.12 GB) на порту **8081** (OpenAI-совместимый).

Приёмка (всё обязательно):
- [ ] `curl -s localhost:8081/health` → `{"status":"ok"}`
- [ ] `/v1/models` отдаёт alias `Qwen3.8-27B-UD`
- [ ] chat completion с `max_tokens: 800` возвращает непустой `content`
- [ ] в логе сервера `draft acceptance` ≥ 0.60 (MTP работает)
- [ ] `nvidia-smi`: ~15.1–15.6 GB VRAM занято, сервер не вылетает
- [ ] тест 60K-токенного контекста (шаг 8) найден «иголкой»

## 1. Предусловия (проверить ДО всего)

```bash
nvidia-smi   # GPU 16+ GB из RTX 50-й серии (sm_120: 5060/5060Ti/5070Ti/5080/5090), driver ≥ 570
df -h ~      # ≥ 40 GB свободно
free -h      # ≥ 16 GB RAM
```
- Драйвер должен поддерживать CUDA 13 (в выводе nvidia-smi строка "CUDA Version: 13.x"; практически — driver ≥ 580).
- Если GPU < 16 GB или не sm_120 → см. «Деградация» в конце, НЕ продолжай вслепую.
- Контейнер-рантайм: `podman` или `docker` (что есть; команды ниже для podman, docker — аналог).

## 2. Контейнер

Вариант A (рекомендую, если стоит nvidia-container-toolkit):
```bash
podman run -d --name beellama --gpus all -v "$HOME/models:/models" docker.io/ubuntu:24.04 sleep infinity
```
Вариант B (без toolkit'а, сырые устройства — как на эталонной машине):
```bash
podman run -d --name beellama \
  --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm --device /dev/nvidia-modeset \
  --security-opt seccomp=unconfined --security-opt label=disable \
  -v "$HOME/models:/models" docker.io/ubuntu:24.04 sleep infinity
```
Гейт: `podman exec beellama ls /dev/nvidia0` — файл есть. Если нет — остановись, почини доступ к GPU.

Ставь утилиты: `podman exec beellama bash -c "apt-get update && apt-get -y install curl ca-certificates"`.

**Pitfall (0-байтные стабы драйвера):** если внутри контейнера
`stat -c %s /usr/lib/x86_64-linux-gnu/libcuda.so.1` (или `/usr/lib64/...`) = 0 — это заглушки.
Реальные библиотеки хоста смонтируй или скопируй (в эталонной машине Fedora драйверные либы
примонтированы toolbox'ом целиком). Диагностика: размер должен быть ~112 MB, не 0.

## 3. BeeLlama v0.4.8 (prebuilt CUDA 13.3)

```bash
mkdir -p ~/beellama-dist && cd ~/beellama-dist
curl -fL --retry 3 -o bee.tar.gz \
  https://github.com/Anbeeld/beellama.cpp/releases/download/v0.4.8/beellama-v0.4.8-bin-ubuntu-cuda-13.3-x64.tar.gz
echo "ecb72ac00ac94997176919e62c73d38bce06f16e4cad5f88ac7c5e98b4178373  bee.tar.gz" | sha256sum -c -
mkdir -p v0.4.8 && tar xzf bee.tar.gz -C v0.4.8 --strip-components=1
```
Гейт: `sha256sum -c` → OK. Если нет — остановись (битая загрузка/другая версия).
Если нужна более свежая версия: `https://api.github.com/repos/Anbeeld/beellama.cpp/releases/latest`,
хелпер обновления с авто-откатом — в конце документа.

## 4. CUDA runtime (prebuilt его НЕ включает!)

Симптом отсутствия: `./llama-cli --list-devices` печатает `Available devices: (none)`,
а `ldd libggml-cuda.so | grep "not found"` показывает `libcudart.so.13`, `libcublas.so.13`.

Поставь из NVIDIA-репозитория (Ubuntu 24.04 внутри контейнера):
```bash
podman exec beellama bash -c '
  wget -qO /usr/share/keyrings/nvidia-cuda.keyring https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb 2>/dev/null || true
  apt-get -y install wget && wget -qO /tmp/nv.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb \
  && dpkg -i /tmp/nv.deb && apt-get update \
  && apt-get -y install cuda-cudart-13-3 libcublas-13-3'
```
На Fedora-хосте/контейнере: `dnf install cuda-cudart-13-3 cuda-cublas-13-3` из nvidia-репо,
или скопируй `cp -L` файлы `libcudart.so.13 libcublas.so.13 libcublasLt.so.13`
из `/usr/local/cuda-13.3/lib64` любой машины с CUDA 13.3 в `~/beellama-dist/cuda-libs/`.
Используй `LD_LIBRARY_PATH=/home/<user>/beellama-dist/cuda-libs` при запуске.

Гейт (внутри контейнера, из каталога v0.4.8, с LD_LIBRARY_PATH):
```bash
podman exec -e LD_LIBRARY_PATH=/root/cuda-libs beellama bash -c "cd /root/beellama-dist/v0.4.8 && ./llama-cli --list-devices"
# ОЖИДАНИЕ: CUDA0: NVIDIA GeForce RTX 50xx (~15xxx MiB free). Пусто = шаг 4 не сделан.
```
Замени пути на фактические (если контейнер без -v, скопируй dist внутрь: `podman cp`).

## 5. Модель (12 120 016 960 байт)

```bash
mkdir -p ~/models && cd ~/models
curl -fL --retry 3 -o Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf \
  "https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf"
```
Зеркала (если HF медленный/недоступен; проверено: ModelScope быстрее всех):
- `https://hf-mirror.com/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`
- `https://modelscope.cn/models/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/master/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`
- Ускорение: разбей на 8 range-частей (`curl -r start-end` параллельно, `cat` склейка).

Гейт (ОБЯЗАТЕЛЕН):
```bash
echo "58fd826723939933dc86f45b7fe04545cbc2de1c70f6fe2cdd3858c87a98c12f  Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf" | sha256sum -c -
stat -c %s Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf   # = 12120016960
```

## 6. Запуск (эталонные флаги — не «улучшай» их)

```bash
podman exec -d beellama bash -c '
export LD_LIBRARY_PATH=/root/beellama-dist/cuda-libs
cd /root/beellama-dist/v0.4.8
./llama-server \
  -m /models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf \
  --alias "Qwen3.8-27B-UD" \
  --spec-type draft-mtp \
  --spec-draft-n-max 3 \
  -ngl 99 \
  -ngld 99 \
  -c 128000 \
  -ctk kvarn4 \
  -ctv kvarn4 \
  --kv-tail-tokens 2048 \
  -fa on \
  --jinja \
  --temp 1.0 \
  --top-k 20 \
  --top-p 0.95 \
  --min-p 0.0 \
  --reasoning on \
  --reasoning-preserve \
  --chat-template-kwargs "{\"reasoning_effort\":\"xhigh\"}" \
  -kvu \
  -np 1 \
  -fit on \
  --host 0.0.0.0 --port 8081 --metrics \
  > /root/server.log 2>&1'
```
Замечания:
- `-fit on` НЕ трогает явный `-c` (он поджимает только неявные параметры) — не жди авто-подбора.
- Никогда не `pkill llama-server` по имени, если на машине есть другие llama-server
  (общий PID namespace у toolbox'ов) — убивай только по совпадению `--port 8081` в cmdline.
- Загрузка модели ~40 с (первый запрос после старта всегда медленный — warmup, не вешайся).

## 7. Верификация

```bash
# 1. health (поллить до 180 с)
curl -s localhost:8081/health
# 2. alias
curl -s localhost:8081/v1/models | grep -o '"Qwen3.8-27B-UD"'
# 3. completion (max_tokens НЕ меньше 300 — reasoning съедает короткий бюджет целиком)
curl -s localhost:8081/v1/chat/completions -H "Content-Type: application/json" -d '{
 "model":"Qwen3.8-27B-UD","max_tokens":800,
 "messages":[{"role":"user","content":"Сколько будет 17*23? В финале только число."}]}'
# ожидаем 403 в content; usage.completion_tokens_details.reasoning_tokens > 0
# 4. MTP
grep "draft acceptance" /root/server.log | tail -2   # ожидаем 0.60–0.75
# 5. VRAM
nvidia-smi --query-gpu=memory.used --format=csv,noheader   # ~15.1–15.6 GB
```

## 8. Стресс-тест контекста (60K токенов)

Сгенерируй файл-затычку ~60K токенов (повтор нумерованных абзацев на 300–400 KB кириллицы),
вставь ровно в середину строку-иглу `СЕКРЕТНЫЙ КОД СИНЕЙ КИТЫ: изумруд-7742-дельта.`
и спроси в конце: «какой СЕКРЕТНЫЙ КОД СИНЕЙ КИТЫ в тексте? Ответь только кодом».
Гейт: ответ содержит `изумруд-7742-дельта`. Это доказывает, что kvarn4 KV + tail 2048
не деградируют recall на большой дистанции.

## 9. Ожидаемые метрики эталонной машины (RTX 5060 Ti 16GB)

| Метрика | Значение |
|---|---|
| VRAM idle-load | 15 388 MiB; при 120K промпте 15 538 MiB |
| Decode | ~52 t/s (MTP accept 64–73%, mean draft ~3.1) |
| Prefill | ~400 t/s (с prompt-cache по префиксу — до 2000 t/s) |
| Качество | 6/6: математика, логика, код (исполнен), извлечение фактов, needle 60K |

## 10. Деградация (если не влезает)

- OOM при загрузке / `cudaMalloc failed` / segfault на init → снижай `-c`: 128000 → 96000 → 64000.
  KV ≈ 17.5 MiB/1K токенов при kvarn4 (архитектура qwen35: full attention каждые 4 слоя).
- 12 GB VRAM → возьми `Qwen3.8-27B-GSQ-RCO-IQ2_XS-mtp.gguf` (8.77 GB, тот же репо) и `-c 64000`.
- GPU не sm_120 → возми другой asset из релиза (cuda-12.4 / vulkan / rocm) и повтори шаг 4
  с соответствующим runtime.
- `--spec-type draft-mtp` без MTP-файла (без суффикса `-mtp`) не работает — MTP-вариант модели обязателен.

## 11. Обновление BeeLlama (опционально, есть авто-откат)

Идемпотентный скрипт-эталон (GitHub latest → sha256 → pre-flight новой версии ДО переключения
симлинка → health-гейт → авто-rollback): см. `~/Documents/update_beellama_deploy.sh` эталонной
машины; логика: `VERSION=$(curl -s https://api.github.com/repos/Anbeeld/beellama.cpp/releases/latest | ...tag_name)`,
скачать asset `bin-ubuntu-cuda-13.3-x64.tar.gz`, сверить по `SHA256SUMS.txt` релиза (строки
имеют префикс `release/` — грепать по имени файла), распаковать в `beellama-v<VER>/`,
пред-проверить `./llama-cli --list-devices`, переключить симлинк `current`, рестарт, health 180 с.

## 12. Что запрещено

- Менять флаги секции 6 «на своё усмотрение» (особенно `-ctk/-ctv`, `--kv-tail-tokens`, `-fa on` —
  tail работает только под FlashAttention; `-kvu` — обязательное условие стабильности 128K).
- Ставить `--no-mmap` (это настройка unified-memory Strix Halo, на дискретной GPU хуже).
- Доверять «файл скачался — значит ок»: без sha256-гейтов (шаги 3, 5) дальше не идти.
