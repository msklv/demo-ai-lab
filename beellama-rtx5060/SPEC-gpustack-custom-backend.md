# Спека: Qwen3.8-27B в BeeLlama как **custom backend** GPUStack (тестовый прогон)

> **Версия:** v1.1 (2026-10-29) · **Статус:** не выполнено — спека на исполнение (B0–B7); правила окна теста — §5, методика измерений — §6
> **Область:** тест. На итоговую архитектуру и на принятые решения **не влияет**:
> `architecture/specs/gpustack-spec.md` §1 (бэкенд — только раннер `cuda13.0-vllm0.25.1`) и
> ADR-0007 (резиденты 5060 Ti: `gemma-4-12B` + ASR) остаются в силе. Ничего в `gitops/`,
> `ansible/`, ADR и спеках GPUStack эта работа не меняет.
> **Режим:** целевые LLM **временно выгружаются** с 5060 Ti, после теста **возвращаются** на место;
> BeeLlama (бинарь + модель + либы) **остаётся на диске** и в GPUStack выключенной — для повторных тестов.

Стиль: `architecture/specs/gpustack-spec.md` (G-фазы). Своя буква — **B1–B7**.

## 1. Цель и критерии приёмки

Поднять тот же инстанс, что в `HANDOFF-BEELLLAMA-5060.md` §6 (BeeLlama v0.4.8, `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp`,
`kvarn4/kvarn4` + tail 2048, `--spec-type draft-mtp`, `-c 128000`), но **не хостовым процессом на 8081, а
моделью GPUStack** через механизм custom inference backend — с единым `/v1/*`, ключами и логами GPUStack.

Приёмка (всё обязательно):

- [ ] `Model Service → Deployments`: модель `Qwen3.8-27B-UD` в статусе `RUNNING`;
- [ ] `GET /v1/models` через `https://api.demo-ai-lab.ru` отдаёт `Qwen3.8-27B-UD`;
- [ ] chat completion `max_tokens: 800` → непустой `content`, `reasoning_tokens > 0`;
- [ ] в логах инстанса `draft acceptance` ≥ 0.55 (MTP работает; по эталону/стенду 0.56–0.66);
- [ ] `nvidia-smi` на k8s-04: **15.1–15.6 GiB** занято, `nvidia-smi --query-gpu=memory.free` < 0.5 GiB;
- [ ] needle 60K (`изумруд-7742-дельта`) найден — kvarn4 + tail не деградируют recall;
- [ ] измерения по **§6**: два прогона `bench_speed.py` с разными `run_salt`, `cached_tokens = 0`, на трёх
      длинах не хуже −10 % от `bench-results.json`;
- [ ] окно теста открыто и закрыто **явной командой владельца** (§5) — между командами на карте только BeeLlama;
- [ ] **после теста целевые LLM возвращены**: `gemma-4-12B` + `whisper-turbo` `RUNNING`, VRAM ≈ 14943 MiB.

## 2. Живые факты (замер 2026-10-29)

| Что | Факт |
|---|---|
| Нода | `k8s-04` (`192.168.10.252`), Ubuntu 24.04, драйвер `595.99.02`, CUDA 13.x |
| GPU | RTX 5060 Ti, **16311 MiB**, sm_120; PCIe Gen4 x4 |
| GPUStack | **v2.2.3** (`/version` → `1cfcbbf`), ns `gpustack`, UI/API `api.demo-ai-lab.ru` |
| Резиденты GPU сейчас | `gemma-4-12B` (vLLM 0.25.1, id 1) — **12632 MiB**; `whisper-turbo` (VoxBox 0.0.21, id 2) — **2296 MiB**; итого **14943 / 16311**, свободно **908** |
| Free-VRAM под BeeLlama | нужно **15096 MiB** (idle) / **15524** @122K → **карта только эксклюзивно**, оба резидента выгружаются |
| Бэкенды, зарегистрированные в GPUStack | `vLLM`, `SGLang`, `MindIE`, `VoxBox`, `llama.cpp` (built-in = stock llama.cpp), `TensorRT-LLM`, `Text-Embeddings-Inference`; **custom-бэкендов нет** |
| Каталог GPUStack на ноде | `/var/lib/gpustack` (hostPath воркера и в поды инстансов монтируется **по тому же пути**, проверено: под `whisper-turbo-cv1xl` → `gpustack-data-dir → /var/lib/gpustack`, `runtimeClassName: nvidia`) |
| BeeLlama на диске | `~/beellama-dist/v0.4.8/` (635 MB, `llama-server` + `libllama*/libggml*/libmtp*`, rpath `$ORIGIN`), `~/beellama-dist/cuda-libs/` (**1.1 GB**: `libcudart.so.13`, `libcublas.so.13`, `libcublasLt.so.13`) |
| Модель на диске | `~/models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`, **12 120 016 960 B**, sha256 `58fd8267…c12f` |
| Внешние зависимости бинаря | `libstdc++.so.6`, `libgomp.so.1` (нужны в образе/в каталоге), CUDA-либы — **не** в дистрибутиве (`ldd` без `LD_LIBRARY_PATH` даёт `libcudart.so.13 not found`) |
| ФС | `/` = `/home` = `/var/lib` — один LV (`st_dev 64512`), свободно **52 GB** → hardlink вместо копирования 12 ГБ |
| API custom backend в 2.2.3 | `POST /v2/inference-backends` (`backend_name`, `health_check_path`, `default_env`, `version_configs{image_name, run_command, entrypoint, custom_framework, env}`); у модели — `local_path`, `image_name`, `run_command`, `env` (проверено по `/openapi.json` живого сервера) |
| Образ-база | `nvidia/cuda:13.3.0-runtime-ubuntu24.04` есть на Docker Hub (1.79 GB compressed); `13.3.0-base-…` = 349 MB, но без cudart/cublas |
| Admin-ключ GPUStack | **нет** (R-G9) → регистрация бэкенда и деплой модели — **через UI**, не curl'ом |

## 3. Решение

```
GPUStack (ns gpustack)                    нода k8s-04
──────────────────────                    ───────────────────────────────────────────
InferenceBackend beellama-custom   ──►   под инстанса (runtimeClassName nvidia, hostNetwork)
  image: nvidia/cuda:13.3.0-runtime-ubuntu24.04
  health_check_path: /health             /var/lib/gpustack/models/beellama-qwen38/
  default_env: LD_LIBRARY_PATH=…           ├── Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf  (hardlink)
Model Qwen3.8-27B-UD                       ├── v0.4.8/llama-server + libggml*/libllama* (hardlink)
  local_path: …/beellama-qwen38            ├── cuda-libs/  (cudart, cublas, cublasLt 13.x)
  run_command: exact RUNBOOK §6 flags      └── hostlibs/   (libgomp.so.1, libstdc++.so.6)
  --host 0.0.0.0 --port {{port}}
```

Почему так:

1. **Только custom backend.** Встроенный `llama.cpp` в 2.2.3 — это stock llama.cpp/llama-box: в нём нет
   `-ctk/-ctv kvarn4`, `--kv-tail-tokens`, `--spec-type draft-mtp`. Без 4-битного KV 128K в 16 GiB не
   собирается (f16-KV ≈ 8 ГиБ), а без MTP декод падает с 48.8 до ~37 ток/с. Смысл теста — воспроизвести
   конфиг RUNBOOK, а не «27B на llama.cpp».
2. **Один монтируемый каталог вместо собственного образа.** GPUStack монтирует в под инстанса
   `/var/lib/gpustack` целиком (проверено на живом поде), поэтому бинарь и либы кладём рядом с моделью и
   обходимся официальным образом CUDA без сборки/пуша в реестр. Всё, чего нет в образе, едет в каталоге.
   Fallback (если образ окажется без нужных libc/libstdc++): собрать свой образ
   `FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04` + `COPY v0.4.8 /opt/beellama` (§11).
3. **Флаги — ровно RUNBOOK §6.** Ни один флаг не меняется; меняется только способ запуска
   (`--port {{port}}` вместо 8081, лог в stdout вместо файла). Иначе тест не сравним с `bench-results.json`.
4. **Целевые LLM выгружаются, а не удаляются.** `Stop` в UI, параметры восстановления зафиксированы в §8
   из живого API — возврат детерминирован.
5. **BeeLlama остаётся на диске после теста**: каталог модели и `~/beellama-dist` не удаляются,
   бэкенд остаётся зарегистрированным, модель — в статусе `Stopped` (0 VRAM). Повторный прогон = `Start`.

## 4. Каталог модели (подготовка на ноде, B2)

```bash
export NODE04="<node-user>@192.168.10.252"     # см. B0: логин в доку не пишется
ssh "$NODE04"

D=/var/lib/gpustack/models/beellama-qwen38
mkdir -p "$D"/{cuda-libs,hostlibs}

# 1) модель — hardlink (та же ФС, 0 доп. места; копия была бы +12.1 ГБ)
ln "$HOME/models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf" "$D"/

# 2) дистрибутив v0.4.8 — hardlink-копия (rpath $ORIGIN подхватит libggml*/libllama* из своего каталога)
cp -al "$HOME/beellama-dist/v0.4.8" "$D"/

# 3) CUDA-рантайм, которого нет ни в образе, ни в дистрибутиве
cp -al "$HOME/beellama-dist/cuda-libs/." "$D"/cuda-libs/

# 4) хостовые libs (libgomp/libstdc++) — только для случая, когда в образе их нет.
#    Обязательное условие: образ инстанса — тоже ubuntu 24.04 (та же glibc/ABI), иначе этот слой
#    нельзя ставить в LD_LIBRARY_PATH; тогда оставляем пустым и берём либы из образа.
cp -L /lib/x86_64-linux-gnu/libgomp.so.1 /lib/x86_64-linux-gnu/libstdc++.so.6 "$D"/hostlibs/

chmod -R a+rX "$D"
du -sh "$D"; df -h "$D" | tail -1
```

Ожидание: `du` ≈ 14 ГБ при ≈2 ГБ фактического прироста (hardlinks), свободно на `/` ≥ 45 GB.
Каталог **не удалять после теста** — это и есть «BeeLlama остаётся на диске».

## 5. Окно теста — открывает и закрывает владелец

Жёсткое правило (решение владельца 2026-10-29): **начало и конец теста задаёт человек явной командой.**
Исполнитель не открывает окно сам — ни по факту готовности спеки, ни по «удобному моменту», ни по расписанию,
ни «раз карта свободна».

| Событие | Что должно быть сказано | Что делает исполнитель |
|---|---|---|
| Открытие окна | явная команда начать тест («начали», «поехали, выгружай») | B1 → B5 по порядку, ничего не пропуская |
| Закрытие окна | явная команда закончить («закончили», «возвращай модели») | B6: `Stop` beellama + `Start` gemma и whisper |
| Молчание, «посмотрим», «ну ладно», вопрос про спеку | — | **ничего не выгружать**, ждать команды |

- Между командами состояние «`gemma-4-12B` и `whisper-turbo` = `Stopped`, `Qwen3.8-27B-UD` = `RUNNING`» —
  **нормальное состояние окна**, а не авария: авто-отката по таймауту нет, «через час верну сам» нет.
  Целевые LLM возвращаются только по команде.
- Перед открытием окна подтвердить, что демо не показывают и чат `owu` / транскрибация `spk` не нужны
  (на время окна они недоступны). Нет подтверждения — окно не открывается.
- «Продолжай тестировать» = продление того же окна: B1 не повторяется, продолжаются B2–B5 / повторные
  прогоны по §6.
- Команда «закончили» пришла посреди прогона → прогон прерывается, недописанный JSON измерением не считается,
  дальше сразу B6.

### Журнал прогонов (заполняется по факту, не задним числом)

| № | Начало: команда владельца, дата-время МСК | Конец: команда, дата-время МСК | `run_salt` ×2 | decode 4K / 32K / max, ток/с | MTP accept | Вердикт |
|---|---|---|---|---|---|---|
| 1 | — | — | — | — | — | — |

## 6. Методика измерений (тот же алгоритм, что в `bench-results.json`)

Мерим **тем же инструментом и тем же способом**, что дал эталонные цифры: `bench_speed.py` из этого каталога,
`parallelism = 1` (последовательные запросы, без конкуренции). Свои бенчмарки, Playground и короткие `curl`
не считаются: с ними цифры не сравнить с `bench-results.json`.

Версию инструмента зафиксировать до прогона:

```bash
shasum -a 256 bench_speed.py     # значение — в отчёт прогона
```

### Точка замера

| Куда мерим | Зачем |
|---|---|
| `http://192.168.10.252:<port_инстанса>` — llama-server напрямую (под в host-network) | **основной замер, сравнимый с эталоном** (там был прямой `:8081`) |
| `https://api.demo-ai-lab.ru/v1` через ключ `beellama-test` | только маршрутизация и ключи (B5 п.2). В цифры **не** идёт: шлюз добавляет прокси-слой |

Порт инстанса — из свойств модели в UI (`RUNNING` → инстанс → порт) либо
`kubectl -n gpustack get pod <инстанс> -o jsonpath='{.spec.containers[*].ports[*].containerPort}'`.

### Алгоритм прогона (как устроен `bench_speed.py`)

1. **Warmup:** один запрос `max_tokens=8` — первый запрос после idle всегда медленный, в зачёт не идёт.
2. **Калибровка «символы/токен»:** отдельный запрос с инструкцией (`base_tokens`) + образец филлера 6000 символов
   (seed 777); `ratio` считается по фактическому `usage.prompt_tokens`, поэтому целевые размеры ложатся вплотную.
3. **Три размера контекста:** `4096`, `32768`, `max`, где `max = n_ctx − max_tokens − 256`; `n_ctx` берётся из
   `/v1/models` инстанса (128000) → `max = 127232`, фактически ≈126.5K токенов.
4. **Филлер** — детерминированная кириллица (`терраса`, `спутник`, …), seed на размер = `run_salt + i`:
   уникальный текст на каждый замер исключает попадание в prompt-cache, то есть prefill и TTFT — **холодные**.
   `run_salt` фиксируется `--seed` и пишется в JSON.
5. `max_tokens = 512` при `--reasoning on`: бюджет уходит в reasoning-токены (`visible_tokens = 0` — норма,
   не ошибка). Содержательный ответ проверяется отдельным запросом `max_tokens: 800` (B5 п.2).
6. **Обязательный контроль: `cached_tokens = 0` в каждом замере.** Ненулевой → prefill/TTFT измерен по кэшу,
   прогон недействителен (`bench_speed.py` печатает `*** WARM CACHE ***` в stderr).
7. JSON на каждый прогон отдельно: `--json /tmp/bench-custom-run1.json`, `run2`.

### Метрики (определения — как в `bench-results.json`)

| Метрика | Как считается | Что показывает |
|---|---|---|
| TTFT | клиент: время до первого non-null `delta.content`/`reasoning_content` в SSE | включает prefill и сеть |
| prefill tok/s | клиент: `prompt_tokens / TTFT`; сервер: `timings.prompt_per_second` | обработка промпта; серверное — чистый GPU |
| decode tok/s | клиент: `(completion_tokens − 1) / время генерации`; сервер: `timings.predicted_per_second` | генерация |
| MTP accept | `timings.draft_n_accepted / timings.draft_n`, плюс `draft acceptance` в логе инстанса | работает ли спекулятивное декодирование |
| E2E | `total_s` | полное время запроса |

### Два прогона, а не один

Разброс по контенту заметный: acceptance плавает 46–65 %, наблюдавшиеся диапазоны decode — 4K ~42–49,
32K ~32–41, max ~19–23 ток/с. Поэтому:

- **два прогона** с разными `run_salt` (можно в разные дни в пределах §5), сохраняются оба JSON;
- вердикт — по лучшему, но **оба** числа идут в отчёт;
- разброс между прогонами > 15 % → сначала искать причину (недогашенный процесс на GPU, троттлинг, чужой
  prompt-cache), потом докладывать. «Взять удобное число» запрещено.

### Что фиксировать вокруг каждого прогона

```bash
ssh "$NODE04" 'nvidia-smi --query-gpu=driver_version,memory.used,memory.free,temperature.gpu,power.draw --format=csv,noheader'
ssh "$NODE04" 'lspci -vv | grep -A2 -i "vga.*nvidia" | grep -E "LnkCap:|LnkSta:"'   # ждём Gen4 x4, как на эталоне
ssh "$NODE04" 'sha256sum /var/lib/gpustack/models/beellama-qwen38/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf'
ssh "$NODE04" 'sudo dmesg | grep -i xid | tail -3'                                  # пусто = Xid нет
kubectl -n gpustack get pod | grep -i qwen                                          # рестарты за прогон = 0
```

В отчёт: `run_salt` (обоих прогонов), порт и id инстанса, дайджест образа инстанса, `shasum bench_speed.py`,
VRAM до/после, время начала/конца по журналу §5.

### Ожидаемые значения (эталон — bare-metal, те же флаги)

| Контекст (prompt_tokens) | TTFT | prefill tok/s (client / server) | decode tok/s (client / server) | MTP accept | E2E |
|---:|---:|---:|---:|---:|---:|
| 4 107 | 5.53 с | 742 / 782 | 48.8 / 48.8 | 63 % | 16.0 с |
| 32 538 | 46.86 с | 694 / 706 | 40.0 / 39.9 | 61 % | 59.6 с |
| 126 515 (max) | 256.78 с | 493 / 496 | 23.2 / 23.2 | 62 % | 278.8 с |

Допуск — **−10 %** по decode и prefill; TTFT масштабируется по контексту линейно (5.5 с → 257 с).
Оверхед контейнера в замер не входит (мерим сам llama-server), поэтому «как на bare-metal» — законное ожидание.

Хуже допуска — разбирать по списку, а не списывать на образ:

1. `cached_tokens ≠ 0` → замер по кэшу, прогон недействителен;
2. MTP acceptance < 0.5 → `--spec-type draft-mtp` не поднялся либо взят не `-mtp` GGUF;
3. на GPU остался чужой процесс: `nvidia-smi --query-compute-apps` (недогашенные gemma/ASR);
4. троттлинг: `power.draw`, `temperature.gpu`, NVRM Xid в `dmesg`;
5. либы: другой `libcudart`/`libcublas` (эталон — 13.3 из deb) → `ldd` внутри пода инстанса;
6. неполный дистрибутив после hardlink: `sha256sum` бинаря против релиза v0.4.8.

### Дополнительно (функциональное, не скорость)

Needle 60K по методике RUNBOOK §8 (затычка + строка-игла в середине, вопрос в конце) → ответ содержит
`изумруд-7742-дельта`; по желанию 120K. Фиксировать `prompt_tokens`, TTFT и сам ответ: это проверка recall
на kvarn4 + tail 2048, а не бенчмарк.

## 7. Фазы

### B0. Предпосылки — перепроверить фактом

```bash
# ssh-цель ноды: логин берётся из локального приватного хранилища, в доку не пишется
export NODE04="<node-user>@192.168.10.252"
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl -n gpustack get pods -o wide | grep -E 'worker-nvidia|server'
curl -s https://api.demo-ai-lab.ru/version            # v2.2.3
ssh "$NODE04" 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader; df -h / | tail -1'
```

**Приёмка:** сервер и GPU-воркер `Running`; версия `v2.2.3`; диск `/` ≥ 20 GB свободно. Расхождение — стоп,
обновить §2 (цифры устарели).

### B1. Выгрузка целевых LLM с 5060 Ti

UI → `Model Service → Deployments` → `gemma-4-12B` → **Stop**, затем `whisper-turbo` → **Stop**.
Не `kubectl scale` и не удаление моделей — состояние в БД GPUStack должно остаться `Stopped`, чтобы
`Start` вернул ту же конфигурацию.

Фаза открывается **только по явной команде владельца** (§5). До неё исполнитель не выгружает ничего:
готовность спеки, свободная карта или «удобный момент» командой не являются.

**Приёмка:**
```bash
ssh "$NODE04" 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader; nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv'
```
→ занято < 300 MiB, процессов `VLLM::EngineCore`/`python` нет. Остаток — чужие поды без CUDA, это норма.

> Внимание: пока идёт тест, чат `owu` (gemma) и транскрибация `spk` (whisper) **не работают**. Тест — в
> окно, когда демо не показывают; ключи `owu`/`spk` при этом не трогаем.

### B2. Каталог-модель и прогрев образа на ноде

Команды §4 на ноде + прогрев базового образа (иначе первый старт висит в `ImagePullBackOff`):

```bash
ssh "$NODE04" \
  'sudo ctr -n k8s.io images pull docker.io/nvidia/cuda:13.3.0-runtime-ubuntu24.04'
```

**Гейт (до регистрации бэкенда) — бинарь и GPU видны с теми же либами, что будут в поде инстанса:**
```bash
kubectl -n gpustack exec ds/gpustack-worker-nvidia -- \
  env LD_LIBRARY_PATH=/var/lib/gpustack/models/beellama-qwen38/cuda-libs:/var/lib/gpustack/models/beellama-qwen38/hostlibs \
  /var/lib/gpustack/models/beellama-qwen38/v0.4.8/llama-cli --list-devices
```
→ ожидание: `CUDA0: NVIDIA GeForce RTX 5060 Ti (15xxx MiB free)`. Пусто / `not found` — стоп, чинить либы
(hardlink мог не сработать, если каталог оказался на другой ФС).

### B3. Регистрация custom backend (UI)

`Model Service → Inference Backends → Add Backend → Custom` (есть импорт YAML). Имя обязано оканчиваться
на `-custom`.

```yaml
backend_name: beellama-custom
description: "BeeLlama.cpp v0.4.8 (форк llama.cpp, sm_120): kvarn4 KV + MTP. Тестовый путь, не архитектура"
health_check_path: /health
default_env:
  LD_LIBRARY_PATH: /var/lib/gpustack/models/beellama-qwen38/cuda-libs:/var/lib/gpustack/models/beellama-qwen38/hostlibs:/usr/local/cuda/targets/x86_64-linux/lib
default_version: "0.4.8"
version_configs:
  "0.4.8":
    image_name: nvidia/cuda:13.3.0-runtime-ubuntu24.04
    custom_framework: cuda
    run_command: >-
      /var/lib/gpustack/models/beellama-qwen38/v0.4.8/llama-server
      -m {{model_path}}/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf
      --alias Qwen3.8-27B-UD
      --spec-type draft-mtp
      --spec-draft-n-max 3
      -ngl 99
      -ngld 99
      -c 128000
      -ctk kvarn4
      -ctv kvarn4
      --kv-tail-tokens 2048
      -fa on
      --jinja
      --temp 1.0
      --top-k 20
      --top-p 0.95
      --min-p 0.0
      --reasoning on
      --reasoning-preserve
      --chat-template-kwargs '{"reasoning_effort":"xhigh"}'
      -kvu
      -np 1
      -fit on
      --host 0.0.0.0 --port {{port}} --metrics
```

Правила, без которых не взлетит:

- `--port {{port}}` **обязателен**: контейнер инстанса идёт с `host_network`, GPUStack выбирает свободный
  порт воркера и поллит `http://<worker_ip>:<port>/health` (таймаут 1 с). Фиксированный 8081 — нельзя.
- GPUStack режет `run_command` **shlex'ом, без shell**: конвейеров, `&&`, `$VAR`, редиректов нет. JSON
  для `--chat-template-kwargs` обёрнут **одинарными кавычками внутри строки** — shlex их снимает и отдаёт
  бинарю валидный JSON. Без кавычек получится `{reasoning_effort:xhigh}` и сервер упадёт на старте.
- `backend_parameters` у модели **не используем** (для custom backend порядок вставки не документирован);
  все флаги — в `run_command`.
- `custom_framework: cuda` — фильтр планировщика на GPU-воркеры; multi-worker для custom backends не
  поддерживается в принципе (нам и не нужно: одна карта).
- `LD_LIBRARY_PATH` собирается из трёх слоёв: `cuda-libs/` (cudart/cublas/cublasLt 13.x — в дистрибутиве
  их нет), `hostlibs/` (libgomp/libstdc++ — нужны, если их нет в образе; брать **только** из 24.04) и
  `/usr/local/cuda/...` (на случай, если образ всё же несёт свой рантайм). Симптом «слой лишний» —
  `error while loading shared libraries` или падение на `GLIBC_2.xx not found`; лечится выбрасыванием
  `hostlibs` из строки.
- Образ инстанса — **тот же**, что прогрет в B2; тег фиксировать полностью, `latest` не использовать.

**Приёмка:** в `Inference Backends` появился `beellama-custom` версии `0.4.8` (`enabled`), в логе сервера
GPUStack нет ошибок парсинга YAML.

### B4. Деплой модели

`Deployments → Deploy Model`:

| Поле | Значение |
|---|---|
| Name | `Qwen3.8-27B-UD` (равно `--alias`) |
| Source | `Local Path` → `/var/lib/gpustack/models/beellama-qwen38` |
| Backend / Version | `beellama-custom` / `0.4.8` |
| Categories | `llm` |
| Replicas | `1` |
| Worker / GPU | `worker-name: k8s-04`; GPU — авто (при отказе валидации выбрать `k8s-04:cuda:0` руками) |
| Restart on error | включено |

Эквивалент через API (когда/если появится admin-ключ; сейчас путь — UI):

```bash
curl -sS -X POST https://api.demo-ai-lab.ru/v2/models -H "Authorization: Bearer $ADMIN_KEY" \
  -H 'Content-Type: application/json' -d '{
    "name":"Qwen3.8-27B-UD","source":"local_path",
    "local_path":"/var/lib/gpustack/models/beellama-qwen38",
    "backend":"beellama-custom","backend_version":"0.4.8",
    "categories":["llm"],"replicas":1,
    "worker_selector":{"worker-name":"k8s-04"},
    "restart_on_error":true,"meta":{"max_model_len":128000}}'
```

**Ожидаемый старт:** под `Running` через ~40–90 с после pull образа (загрузка весов ~40 с; первый запрос
после старта медленный — warmup, не считать зависанием).

**Приёмка:**
```bash
kubectl -n gpustack get pods | grep -i qwen        # Running, 0 рестартов
ssh "$NODE04" 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader'
# → 15096–15600 MiB занято
```
В логе инстанса: `kv cache type = kvarn4`, `n_ctx = 128000`, нет `no kernel image`, нет `cudaMalloc failed`.

### B5. Приёмка функционала и скорости

1. Ключ: `API Keys → Create` — **новый ключ** `beellama-test`, Access Control → только
   `Qwen3.8-27B-UD`. Существующие ключи (`owu`, `spk`, `rag`, `qm`, `her`) **не трогать** — иначе
   после возврата gemma/whisper они окажутся без своих моделей (403 `Not allowed to access model`).
2. Через шлюз (ключ `beellama-test` держим в переменной `K`; значение — из UI или приватного
   хранилища, в доку не печатается):
   ```bash
   curl -s https://api.demo-ai-lab.ru/v1/models -H "Authorization: Bearer $K" | grep -o '"Qwen3.8-27B-UD"'
   curl -s https://api.demo-ai-lab.ru/v1/chat/completions -H "Authorization: Bearer $K" \
     -H 'Content-Type: application/json' -d '{"model":"Qwen3.8-27B-UD","max_tokens":800,
     "messages":[{"role":"user","content":"Сколько будет 17*23? В финале только число."}]}'
   # ожидание: content содержит 391, reasoning_tokens > 0
   ```
3. MTP: в логах инстанса (UI → Deployments → модель → Logs) `draft acceptance` ≥ 0.55.
4. Скорость — по методике **§6**: тот же `bench_speed.py`, **два прогона** с разными `run_salt`, `cached_tokens = 0`,
   замер против порта инстанса (ключ не нужен, под в host-network). Команды, метрики, таблица ожидаемых
   значений и разбор отклонений — там же. В B5 фиксируется результат: оба JSON сохранены, decode/prefill
   в допуске −10 % от `bench-results.json`.
5. Needle 60K по методике RUNBOOK §8 (затычка + строка-игла в середине, вопрос в конце) → ответ содержит
   `изумруд-7742-дельта`.

### B6. Возврат целевых LLM (обязательный шаг, не опция)

Выполняется **только по явной команде владельца** «закончили» (§5). Без команды BeeLlama остаётся `RUNNING`,
а `gemma-4-12B` / `whisper-turbo` — `Stopped`: это штатное состояние окна, а не забытая уборка; вернуть модели
самостоятельно исполнитель не может.

1. UI → Deployments → `Qwen3.8-27B-UD` → **Stop** (не удалять!).
2. Дождаться `nvidia-smi` < 300 MiB.
3. `gemma-4-12B` → **Start**; дождаться `RUNNING` (~1.5–2 мин на загрузку весов).
4. `whisper-turbo` → **Start**.
5. Приёмка возврата (ключ с доступом к `gemma-4-12B` — `$K_OWU`; это ключ демо, не `beellama-test`):

```bash
K_OWU=<ключ демо с доступом к gemma-4-12B>   # значение из UI/приватного хранилища, в доку не пишется
ssh "$NODE04" 'nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader'
# → 14900–15100 MiB занято (gemma 12632 + whisper 2296 + оверхед)
curl -s https://api.demo-ai-lab.ru/v1/models -H "Authorization: Bearer $K_OWU" | grep -o '"gemma-4-12B"'
curl -s https://api.demo-ai-lab.ru/v1/chat/completions -H "Authorization: Bearer $K_OWU" \
  -H 'Content-Type: application/json' -d '{"model":"gemma-4-12B","max_tokens":200,"messages":[{"role":"user","content":"тест"}]}'
```

Плюс `python3 scripts/k8s_health.py --brief` (код 0) — стенд после теста не деградировал.

### B7. Состояние «оставить как есть»

- `beellama-custom` — зарегистрирован, `enabled`.
- `Qwen3.8-27B-UD` — существует, `replicas: 0` / `Stopped` (0 VRAM).
- `/var/lib/gpustack/models/beellama-qwen38/` — на месте; `~/beellama-dist`, `~/models/*.gguf` — на месте.
- Ключ `beellama-test` — остаётся (нужен для повторного `Start` и приёмки).
- Повторный прогон = новая **явная команда владельца** (§5) → B1 → `Start Qwen3.8-27B-UD` → B5 (два прогона §6) → B6.

## 8. Что именно возвращать (снято с живого API 2026-10-29)

| Поле | `gemma-4-12B` (id 1) | `whisper-turbo` (id 2) |
|---|---|---|
| backend / version | `vLLM` / `0.25.1` | `VoxBox` / `0.0.21` |
| source / local_path | `local_path` / `/var/lib/gpustack/models/gemma-4-12B-it-qat-w4a16-ct` | `local_path` / `/var/lib/gpustack/models/faster-whisper-large-v3-turbo-int8` |
| backend_parameters | `--gpu-memory-utilization 0.68`, `--enable-auto-tool-choice`, `--tool-call-parser gemma4`, `--max-model-len 8192` | — (пусто) |
| worker_selector | — | `{"worker-name":"k8s-04"}` |
| gpu_selector | `{"gpu_ids":["k8s-04:cuda:0"],"gpus_per_replica":1}` | — |
| categories / replicas | `llm` / 1 | `speech_to_text` / 1 |
| access_policy | `authed` | `authed` |

`Stop`/`Start` не меняет эти поля — при возврате через UI ничего вводить не нужно. **Не** «пересоздавать»
модели (правка конфига через API подхватывается только пересозданием инстанса — не наш случай).

## 9. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-B1** | Оба инстанса на одной карте → CUDA OOM: custom backend не заявляет VRAM планировщику (синтетические 0.5 GiB) | Строгая последовательность B1 → B4 → B6, `replicas ≤ 1` у любого «тяжёлого» инстанса; при OOM — `Stop` beellama, потом `Start` целевых |
| **R-B2** | libstdc++/libgomp/libcudart отсутствуют в образе инстанса | Всё нужное едет в каталоге (`cuda-libs/`, `hostlibs/`) + `LD_LIBRARY_PATH`; гейт B2 ловит до GPUStack; fallback — свой образ (§11). Ошибка проявится как `error while loading shared libraries` в логе инстанса |
| **R-B3** | shlex-разбор `run_command` портит JSON-флаг | Кавычки как в §7.B3; симптом — `invalid chat template kwargs` / мгновенный `Exited` |
| **R-B4** | Health-check timeout 1 с при загрузке 40–90 с | GPUStack поллит до готовности; если инстанс всё же рестартится по health — увеличить стартовое окно негде, тогда временно снять `health_check_path` (custom backend без него считается всегда готовым) и проверять `/health` руками |
| **R-B5** | Выгруженные gemma/whisper не вернулись (забыли B6) | B6 — обязательная фаза с гейтом по `nvidia-smi`; после теста `k8s_health.py --brief` |
| **R-B6** | Ключи демо сломались из-за Access Control | Новый ключ `beellama-test`; ключи `owu/spk/rag/qm/her` не трогаем |
| **R-B7** | Демо-шаг 1 показывается во время теста | Тест только в окно без демо; чат/транскрибация на время теста недоступны |
| **R-B8** | Hardlink-копия дистрибутива «поедет» при будущем обновлении BeeLlama | Обновление `~/beellama-dist` меняет и каталог модели (hardlink). Это удобно для тестов, но после апгрейда — повторить B2-гейт (`llama-cli --list-devices`) |
| **R-B9** | Модель оставлена `replicas: 1` → 15.5 GiB занято, демо-модели не стартуют | B7 фиксирует `Stopped`; проверка — `nvidia-smi` после каждого теста |
| **R-B10** | Каталог `/var/lib/gpustack/models` — вне git и вне бэкапа (веса не бэкапим) | Каталог воспроизводится B2 за ~2 минуты (hardlink + cp), модель — с HF; страшного нет, но не считать это данными |

## 10. Запрещено

- Менять флаги RUNBOOK §6 «на своё усмотрение» (особенно `-ctk/-ctv`, `--kv-tail-tokens`, `-fa on`,
  `-kvu`, `--spec-depth`/`--spec-draft-n-max`): тест существует, чтобы сравнить с `bench-results.json`.
- Удалять или «пересоздавать» `gemma-4-12B` / `whisper-turbo` вместо `Stop`/`Start`; править их
  `backend_parameters`; трогать ключи демо.
- Удалять `~/beellama-dist`, `~/models/*.gguf`, `/var/lib/gpustack/models/beellama-qwen38` после теста.
- Править `ansible/values-gpustack.yaml`, `gpustack-spec.md`, ADR — этот путь тестовый, в архитектуру
  не входит. Если тест окажется удачным и владелец решит сделать его постоянным, это **отдельная** спека
  и отдельное решение (тогда и `gpustack-spec` §1, и ADR-0007 пересматриваются осознанно).
- `kubectl delete pod`/`scale` вместо UI `Stop` (состояние в БД GPUStack разъедется).

## 11. Fallback: собственный образ (если базовый не годится)

```dockerfile
FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY v0.4.8/ /opt/beellama/
ENV LD_LIBRARY_PATH=/opt/beellama/cuda-libs:/usr/local/cuda/targets/x86_64-linux/lib
```

Сборка/пуш — только amd64 (`docker buildx build --platform linux/amd64`), тег вида
`ghcr.io/msklv/beellama:0.4.8-cuda13.3`; каталог `cuda-libs/` кладётся в образ (или остаётся в модели).
В `version_configs` меняется только `image_name`; `run_command` и `default_env` — те же. Нода тянет
образ напрямую из `ghcr` (локального реестра на стенде нет).

## 12. Открытые вопросы

1. **Ключ доступа для приёмки через шлюз**: заводить отдельный `beellama-test` (рекомендация) или
   расширять Access Control существующего ключа? *(Отдельный: чужие ключи не ломаются при возврате моделей.)*
2. **Нужен ли `llama.cpp`-уровневый `meta.max_model_len`** в карточке модели? Для custom backend GPUStack
   контекст не режет и валидацию пропускает; поле заполняем только как документацию (128000).
3. **Место под второй такой тест** — если понадобится вторая 27B-конфигурация (другой квант/контекст):
   отдельный `local_path` + отдельная версия бэкенда, без переиспользования каталога (иначе hardlink-дрифт).

## 13. История версий

| Версия | Дата | Что |
|---|---|---|
| v1.0 | 2026-10-29 | Первая версия: живые факты (GPUStack v2.2.3, текущие резиденты 14943/16311 MiB, монтирование `/var/lib/gpustack` в поды инстансов, одна ФС для hardlink, схема custom backend по `/openapi.json`), фазы B0–B7, точные параметры возврата моделей, риски R-B1…R-B10 |
| v1.1 | 2026-10-29 | **§5 «Окно теста»:** начало и конец теста задаёт владелец явной командой; между командами состояние «beellama `RUNNING` / gemma+ASR `Stopped`» — штатное, авто-отката нет; журнал прогонов (начало/конец, `run_salt`, результат). **§6 «Методика измерений»** — тот же алгоритм, что дал `bench-results.json`: warmup, калибровка симв/токен, три размера (`4096`/`32768`/`max = n_ctx−max_tokens−256`), seed филлера `run_salt+i` → холодный prefill (`cached_tokens = 0` обязателен), метрики TTFT/prefill/decode/MTP/E2E, **два прогона** и допуск −10 %, список причин при отклонении. Сквозная нумерация разделов (1–14) |

## 14. Связанные документы

- `HANDOFF-BEELLLAMA-5060.md` §6 — эталонные флаги `llama-server` (источник `run_command`), §7 приёмка, §8 needle.
- `DEPLOY-REPORT.md` — замеры на k8s-04 (15096 MiB idle / 15524 @122K, decode 43 tok/s, needle 60K/122K PASS).
- `README.md` — сводные замеры и `bench_speed.py`.
- `architecture/specs/gpustack-spec.md` §1 (бэкенд — vLLM), §4.5 (модели/local_path), §7 (Stop вместо scale), R-G9 (нет admin-ключа).
- `architecture/adr/adr-0007` — модельный набор 5060 Ti (в силе, не пересматривается этим тестом).
