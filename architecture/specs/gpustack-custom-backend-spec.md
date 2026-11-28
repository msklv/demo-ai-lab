# Спека: Qwen3.8-27B в BeeLlama как **custom backend** GPUStack (тестовый прогон)

> **Версия:** v1.6 (2026-11-28) · **Статус:** **окно теста открыто** (команда владельца 2026-11-02 22:13 МСК;
> 2026-11-09 — продление тем же окном): B0–B5 выполнены, приёмка §1 сошлась; **B6 (возврат резидентов) —
> по команде «закончили»**. Правила окна — §5, методика — §6, возврат — §8.
> **Область:** тест. На архитектуру и решения **не влияет**: `gpustack-spec.md` §1 (бэкенд — только раннер
> `cuda13.0-vllm0.25.1`) и ADR-0007 остаются в силе; `gitops/`, `ansible/`, ADR и спеки GPUStack эта работа
> не меняет. Целевые LLM временно выгружены, BeeLlama остаётся на диске и в GPUStack выключенной.

## 1. Цель и критерии приёмки

Тот же инстанс, что в `host-beellama/runbook-host-run.md` §6 (BeeLlama v0.4.8,
`Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp`, `kvarn4/kvarn4` + tail 2048, `--spec-type draft-mtp`, `-c 128000`), но **не
хостовым процессом на 8081, а моделью GPUStack** через custom inference backend — с единым `/v1/*`, ключами
и логами GPUStack. Своя буква фаз — **B0–B7**.

Приёмка (всё обязательно):

- [x] модель `Qwen3.8-27B-UD` `RUNNING` (2026-11-02, инстанс `-wxqeh`, порт 40017); `GET /v1/models` через
      `https://api.demo-ai-lab.ru` её отдаёт (ключ `beellama-test`, маршрут заводится руками — B3a);
- [x] chat completion `max_tokens: 800` → `content` `391`, `reasoning_tokens` 70;
- [x] в логах инстанса `draft acceptance` ≥ 0.55 (0.54–0.75, mean draft len 2.96–3.24);
- [x] `nvidia-smi` на k8s-04: **15096 MiB** idle / **15526 MiB** @122K (free 325 MiB);
- [x] needle найден на **97 424** prompt-токенах (дальше гейта 60K) — ответ ровно `изумруд-7742-дельта`;
- [x] замеры по §6: `run_salt=77101/77102`, `cached_tokens = 0` во всех, decode/prefill в допуске −10 %
      (decode 4K 44.7/44.1 · 32K 38.6/37.8 · max 21.7/22.3; MTP 54–58 %; разброс ≤ 2.8 %);
- [ ] окно открыто и закрыто **явной командой владельца** (§5);
- [ ] **состояние возвращено** (§8): набор — `Qwen3Guard-Gen-4B` `RUNNING`, `gemma-4-12B` + `whisper-turbo`
      `Stopped` (как до окна; со стражем на карте они не уживаются — 0.80 + 0.63 > 1).

## 2. Живые факты (замер 2026-10-29, сверки 11-02 и 11-09)

| Что | Факт |
|---|---|
| Нода / GPU | `k8s-04` (`192.168.10.252`), Ubuntu 24.04, драйвер `595.99.02`, CUDA 13.x; карта — **RTX 5070 Ti, 16 303 MiB, sm_120, VBIOS `98.03.58.40.34`**, 300 W, PCIe Gen4 x4 (сверка 11-09; в снимке 10-17 значилась 5060 Ti — хронология в `architecture/hardware-inventory.md`) |
| GPUStack | **v2.2.3** (`/version` → `1cfcbbf`), ns `gpustack`, UI/API `api.demo-ai-lab.ru` |
| Резиденты, 11-02 | `Qwen3Guard-Gen-4B` (vLLM 0.25.1, id 5, `util 0.80`, `--max-model-len 32768`, `--enforce-eager`) **RUNNING ~12940 MiB**, порт 40024; `gemma-4-12B` и `whisper-turbo` — `replicas: 0` (чат `owu` и транскрибация `spk` не работают); свободно 2901 |
| Нужно под BeeLlama | **15096 MiB** idle / **15524** @122K → **карта только эксклюзивно**: под окно гасится страж (gemma/whisper уже `Stopped`) |
| Custom-бэкенды | зарегистрированы только built-in (`vLLM`, `SGLang`, `MindIE`, `VoxBox`, `llama.cpp` = stock, `TensorRT-LLM`, `Text-Embeddings-Inference`) — своих нет |
| Каталог GPUStack | `/var/lib/gpustack` — hostPath воркера, в под инстанса монтируется **тем же путём** (проверено на поде `whisper-turbo-cv1xl`; `runtimeClassName: nvidia`) |
| BeeLlama на диске | `~/beellama-dist/v0.4.8/` (635 MB: `llama-server` + `libllama*`/`libggml*`/`libmtp*`, rpath `$ORIGIN`); `~/beellama-dist/cuda-libs/` (1.1 GB: `libcudart.so.13`, `libcublas*.so.13`) |
| Модель | `~/models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf`, 12 120 016 960 B, sha256 `58fd8267…c12f` |
| Внешние зависимости | `libstdc++.so.6`, `libgomp.so.1` — в дистрибутиве нет; CUDA-либы тоже (`ldd` без `LD_LIBRARY_PATH` → `libcudart.so.13 not found`) |
| ФС | `/` = `/home` = `/var/lib`, один LV (`st_dev 64512`), свободно 40 GB → hardlink вместо копии 12 ГБ |
| API custom backend 2.2.3 | `POST /v2/inference-backends` (`backend_name`, `health_check_path`, `default_env`, `version_configs{image_name, run_command, entrypoint, custom_framework, env}`); у модели — `local_path`, `image_name`, `run_command`, `env` (по `/openapi.json` живого сервера) |
| Образ-база | `nvidia/cuda:13.3.0-runtime-ubuntu24.04` (1.79 GB compressed); `-base` — 349 MB, но без cudart/cublas |
| Admin-доступ | API-ключа нет (R-G9), но есть bootstrap-пароль admin (`gpustack-admin.local.md`): `POST /auth/login` (form) → cookie `gpustack_session` → `/v2/*` (проверено) |

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

Почему так: **только custom backend** (встроенный `llama.cpp` в 2.2.3 — stock llama-box: нет `-ctk/-ctv
kvarn4`, `--kv-tail-tokens`, `--spec-type draft-mtp`; без 4-битного KV 128K в 16 GiB не собирается — f16-KV
≈ 8 ГиБ; без MTP декод падает с 48.8 до ~37 ток/с); **один монтируемый каталог вместо своего образа**
(GPUStack монтирует `/var/lib/gpustack` целиком, всё нужное едет рядом с моделью, fallback — §11);
**флаги ровно RUNBOOK §6** (меняется только способ запуска: `--port {{port}}` и лог в stdout, иначе не
сравнить с `bench-results.json`); **выгружаем, а не удаляем** (параметры возврата — §8); **BeeLlama остаётся
на диске** — повторный прогон = `Start`.

## 4. Каталог модели (подготовка на ноде, B2)

```bash
export NODE04="<node-user>@192.168.10.252"     # логин в доку не пишется
ssh "$NODE04"

D=/var/lib/gpustack/models/beellama-qwen38
mkdir -p "$D"/{cuda-libs,hostlibs}
ln "$HOME/models/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf" "$D"/          # hardlink: +0 места вместо +12.1 ГБ
cp -al "$HOME/beellama-dist/v0.4.8" "$D"/                            # rpath $ORIGIN подхватит либы рядом
cp -al "$HOME/beellama-dist/cuda-libs/." "$D"/cuda-libs/             # cudart/cublas в дистрибутиве нет
cp -L /lib/x86_64-linux-gnu/libgomp.so.1 /lib/x86_64-linux-gnu/libstdc++.so.6 "$D"/hostlibs/
chmod -R a+rX "$D"; du -sh "$D"; df -h "$D" | tail -1
```

`hostlibs/` кладём **только** если образ инстанса — тоже Ubuntu 24.04 (та же glibc/ABI); иначе слой нельзя
ставить в `LD_LIBRARY_PATH` — оставить пустым. Ожидание: `du` ≈ 14 ГБ при ≈2 ГБ фактического прироста
(hardlinks), свободно ≥ 45 GB. Каталог после теста **не удалять**.

## 5. Окно теста — открывает и закрывает владелец

Жёсткое правило (решение владельца 2026-10-29): **начало и конец теста задаёт человек явной командой.**
Исполнитель не открывает окно сам — ни по готовности спеки, ни по «удобному моменту», ни по расписанию,
ни «раз карта свободна».

| Событие | Что должно быть сказано | Что делает исполнитель |
|---|---|---|
| Открытие | «начали», «поехали, выгружай» | B1 → B5 по порядку, ничего не пропуская |
| Закрытие | «закончили», «возвращай модели» | B6 по §8 |
| Молчание, «посмотрим», вопрос про спеку | — | **ничего не выгружать**, ждать команды |

- Состояние между командами («резиденты `Stopped`, `Qwen3.8-27B-UD` `RUNNING`») — **штатное состояние окна**,
  а не авария: авто-отката по таймауту нет, «через час верну сам» нет.
- Перед открытием подтвердить, что демо не показывают и чат `owu` / транскрибация `spk` не нужны
  (на время окна они недоступны). Нет подтверждения — окно не открывается.
- «Продолжай тестировать» = продление окна: B1 не повторяется, идут B2–B5 и повторные прогоны §6.
- «Закончили» посреди прогона → прогон прерывается, недописанный JSON измерением не считается, сразу B6.

### Журнал прогонов (по факту, не задним числом)

| № | Начало: команда, дата-время МСК | Конец | `run_salt` ×2 | decode 4K / 32K / max, ток/с | MTP accept | Вердикт |
|---|---|---|---|---|---|---|
| 1 | 2026-11-02 22:13, «да, открываю окно» (резидент — страж `Qwen3Guard-Gen-4B`, gemma/whisper уже `Stopped`) | окно открыто | 77101, 77102 | 44.7 / 38.6 / 21.7 · 44.1 / 37.8 / 22.3 | 55–58 % (бенч), до 0.75 (needle) | **PASS** — всё в допуске −10 %, `cached_tokens=0`, Xid нет, 0 рестартов |
| 2 | 2026-11-09 23:21, «протестируй скорость по старой методологии» (продление; на карте только BeeLlama `-yaft4`, порт 40001) | окно открыто | 88101, 88102 | 80.8 / 65.4 / 41.7 · 77.7 / 58.8 / 42.5 | 46–62 % (бенч) | **PASS** — `cached_tokens=0` в 6 замерах, разброс ≤ 11 %, prefill/decode в 1.7–1.9× выше прогона 1. Причина — карта в живом замере **5070 Ti**, не софт (флаги, GGUF и `bench_speed.py` `sha256 80b2466b…` те же) |

## 6. Методика измерений

Мерим **тем же инструментом и способом**, что дал эталон: `bench_speed.py` из `host-beellama/`,
`parallelism = 1` (последовательно, без конкуренции); версия фиксируется
`shasum -a 256 host-beellama/bench_speed.py`. Свои бенчмарки, Playground и короткие `curl` не считаются —
с ними цифры не сравнить с `bench-results.json`.

Обязательно (иначе прогон недействителен):

1. **Точка замера** — `http://192.168.10.252:<port_инстанса>`, llama-server напрямую (под в host-network);
   порт — из свойств модели в UI либо `kubectl -n gpustack get pod <инстанс> -o jsonpath='{.spec.containers[*].ports[*].containerPort}'`.
   Через `api.demo-ai-lab.ru` — только маршрутизация и ключи (B5), в цифры не идёт: шлюз добавляет слой.
2. **`cached_tokens = 0` в каждом замере** (`*** WARM CACHE ***` в stderr = замер по кэшу → прогон недействителен).
3. **Два прогона** с разными `run_salt` (можно в разные дни в пределах §5), оба JSON сохраняются; вердикт — по
   лучшему, оба числа идут в отчёт; разброс > 15 % → сперва искать причину (чужой процесс на GPU, троттлинг,
   prompt-cache), потом докладывать. «Взять удобное число» запрещено.
4. **Вокруг прогона** фиксировать: `nvidia-smi` (driver/memory/temp/power), `lspci` `LnkSta` (ждём Gen4 x4),
   `sha256sum` GGUF, `dmesg | grep -i xid`, рестарты пода. В отчёт — `run_salt`, порт и id инстанса, дайджест
   образа, `shasum bench_speed.py`, VRAM до/после, начало/конец по §5.
5. **JSON на прогон отдельно**: `bench-custom-run1/2.json` — прогон 2026-11-02 (5060 Ti), **не перезаписывать**;
   прогон 11-09 — `bench-2026-11-09-run1/2.json` (88101/88102).

Как устроен сам скрипт (повторять не нужно, но знать): warmup `max_tokens=8` → калибровка «символы/токен» по
`usage.prompt_tokens` → три контекста `4096`, `32768`, `max = n_ctx − max_tokens − 256` (n_ctx 128000 →
≈126.5K) → филлер-кириллица с seed `run_salt + i` (уникальный текст = холодный prefill) → `max_tokens = 512`
при `--reasoning on` (бюджет в reasoning-токены, `visible_tokens = 0` — норма). Метрики: TTFT, prefill/decode
tok/s (клиент и серверные `timings`), MTP accept = `draft_n_accepted / draft_n`, E2E.

**Действующий эталон — 2026-11-09 (5070 Ti), прогоны 88101/88102**, два числа через «·», допуск −10 % по
decode и prefill; TTFT масштабируется по контексту почти линейно (3.2 → 148 с):

| Контекст (prompt_tokens) | TTFT | prefill tok/s (client / server) | decode tok/s | MTP | E2E |
|---:|---:|---:|---:|---:|---:|
| 4 019–4 091 | 3.15–3.22 с | 1270 · 1275 / 1398 · 1402 | 80.8 · 77.7 | 55–59 % | 9.5–9.7 с |
| 32 602–32 664 | 26.50–26.62 с | 1227 · 1230 / 1246 · 1249 | 65.4 · 58.8 | 46–55 % | 34.4–35.2 с |
| 126 389–126 508 (max) | 148.10–148.12 с | 853 · 854 / 860 · 861 | 42.5 · 41.7 | 60–62 % | 160.1–160.4 с |

История — эталон 5060 Ti (bare-metal, до замены карты): 4 107 → 5.53 с / 742 · 782 / 48.8 · 48.8 / 63 % / 16.0 с;
32 538 → 46.86 с / 694 · 706 / 40.0 · 39.9 / 61 % / 59.6 с; 126 515 → 256.78 с / 493 · 496 / 23.2 · 23.2 / 62 % /
278.8 с. Новые замеры с ней не сверять (другая карта, быстрее в 1.7–1.9×) — она для «было/стало».

Хуже допуска — разбирать по списку, а не списывать на образ: `cached_tokens ≠ 0` → прогон недействителен;
MTP < 0.5 → `--spec-type draft-mtp` не поднялся либо взят не `-mtp` GGUF; чужой процесс
(`nvidia-smi --query-compute-apps`); троттлинг (power/temp/Xid); другой `libcudart`/`libcublas` (`ldd` в поде);
неполный дистрибутив после hardlink (`sha256sum` бинаря).

Функциональное (не скорость): needle 60K по методике RUNBOOK §8 (затычка + строка-игла в середине, вопрос в
конце) → ответ содержит `изумруд-7742-дельта`, по желанию 120K; фиксировать `prompt_tokens`, TTFT и ответ —
это recall на `kvarn4` + tail 2048.

## 7. Фазы

**B0 — предпосылки.** Сервер и GPU-воркер `Running`, `/version` = `v2.2.3`, `/` ≥ 20 GB свободно
(`kubectl -n gpustack get pods -o wide | grep -E 'worker-nvidia|server'`, `nvidia-smi`, `df -h /`).
Расхождение — стоп, обновить §2 (цифры устарели).

**B1 — выгрузка целевых LLM** (только по команде владельца, §5). UI → `Model Service → Deployments` →
`Stop` у `Qwen3Guard-Gen-4B`, `gemma-4-12B`, `whisper-turbo`. Не `kubectl scale` и не удаление: состояние в БД
GPUStack должно остаться `Stopped`, чтобы `Start` вернул ту же конфигурацию. Приёмка: занято < 300 MiB,
процессов `VLLM::EngineCore`/`python` нет (остаток — чужие поды без CUDA, это норма). На время окна чат `owu`
и транскрибация `spk` не работают; ключи не трогаем.

**B2 — каталог и прогрев образа.** Команды §4 на ноде +
`sudo ctr -n k8s.io images pull docker.io/nvidia/cuda:13.3.0-runtime-ubuntu24.04` (иначе первый старт висит в
`ImagePullBackOff`). Гейт до регистрации бэкенда — бинарь и GPU видны с теми же либами, что будут в поде:

```bash
kubectl -n gpustack exec ds/gpustack-worker-nvidia -- \
  env LD_LIBRARY_PATH=/var/lib/gpustack/models/beellama-qwen38/cuda-libs:/var/lib/gpustack/models/beellama-qwen38/hostlibs \
  /var/lib/gpustack/models/beellama-qwen38/v0.4.8/llama-cli --list-devices
```

→ `CUDA0: NVIDIA GeForce RTX 5070 Ti (15xxx MiB free)`. Пусто / `not found` — стоп, чинить либы (hardlink
мог не сработать, если каталог оказался на другой ФС).

**B3 — регистрация backend.** `Model Service → Inference Backends → Add Backend → Custom` (есть импорт YAML);
имя обязано оканчиваться на `-custom`:

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

Правила, без которых не взлетит: `--port {{port}}` обязателен (host-network, GPUStack сам поллит
`http://<worker_ip>:<port>/health` с таймаутом 1 с — фиксированный 8081 нельзя); `run_command` режется
**shlex'ом без shell** — нет конвейеров, `&&`, `$VAR`, редиректов, поэтому JSON для `--chat-template-kwargs`
обёрнут одинарными кавычками внутри строки (без них shlex отдаст `{reasoning_effort:xhigh}` и сервер упадёт на
старте); `backend_parameters` у модели не используем (для custom backend порядок вставки не документирован) —
все флаги в `run_command`; `custom_framework: cuda` — фильтр планировщика на GPU-воркеры (multi-worker для
custom backends не поддерживается); `LD_LIBRARY_PATH` из трёх слоёв, симптом лишнего —
`error while loading shared libraries` / `GLIBC_2.xx not found`, лечится выбрасыванием `hostlibs`; образ
инстанса — тот же, что прогрет в B2, тег полностью, без `latest`. Приёмка: `beellama-custom` версии `0.4.8`
(`enabled`), в логе сервера нет ошибок парсинга YAML.

**B3a — грабли API-пути** (вместо ручного UI; cookie-сессии от `POST /auth/login` хватает на весь `/v2/*`):
`PUT /v2/models/{id}` требует полный объект (422 без `source`/`name`) — брать `GET`, снимать
`id`/`created_at`/`updated_at`/`ready_replicas`/`cluster_id`/`owner_principal_id`/`has_stale_lora_instances`,
менять поле; так же делается `Stop` (`replicas: 0`); `POST /v2/models` требует `cluster_id` явно (у стенда `1`,
иначе 500 `NOT NULL cluster_id`), а `POST /v2/inference-backends/from-yaml` ждёт `{"content": "<yaml/json>"}`;
**`default_env` бэкенда и `env` версии НЕ доезжают до контейнера** — работает только `env` на модели
(симптом: мгновенный `Error`, `libgomp.so.1: cannot open shared object file`); API-создание модели **не заводит
model route** → `/v1/*` отвечает `404 Model not found` при `RUNNING` инстансе, лечится `POST /v2/model-routes`
(`{"name":…,"categories":["llm"],"targets":[{"model_id":N,"use_model_route_name":true}]}`); UI маршрут создаёт сам.

**B4 — деплой модели.** `name: Qwen3.8-27B-UD` (равно `--alias`), `source: Local Path` →
`/var/lib/gpustack/models/beellama-qwen38`, backend/version `beellama-custom` / `0.4.8`, category `llm`,
replicas 1, worker `k8s-04` (GPU авто; при отказе валидации — `k8s-04:cuda:0` руками), restart on error
включено. Эквивалент API — `POST /v2/models` с теми же полями и `meta.max_model_len: 128000`.
Ожидаемый старт: `Running` через ~40–90 с после pull (веса ~40 с; первый запрос медленный — warmup, не
считать зависанием). Приёмка: 0 рестартов, `nvidia-smi` 15096–15600 MiB, в логе `kv cache type = kvarn4`,
`n_ctx = 128000`, нет `no kernel image` / `cudaMalloc failed`.

**B5 — приёмка функционала и скорости.** `API Keys → Create` — **новый** ключ `beellama-test`, доступ только к
`Qwen3.8-27B-UD`; существующие (`owu`, `spk`, `rag`, `her`) не трогать — иначе после возврата моделей они
получат `403 Not allowed to access model` (OWU с 11-02 живёт на своём ключе `owu-all`, `owu-spec` §7.2).
Затем через `api.` этим ключом: `GET /v1/models` → `Qwen3.8-27B-UD`; `POST /v1/chat/completions`
(`max_tokens: 800`, «17*23») → `391`, `reasoning_tokens > 0`; `draft acceptance` ≥ 0.55 в логах инстанса;
скорость — два прогона §6, оба JSON сохранены, decode/prefill в допуске −10 %; needle — §6.

**B6 — возврат целевых LLM** (обязательный шаг, только по команде «закончили», §8): `Stop`
`Qwen3.8-27B-UD` (не удалять) → `nvidia-smi` < 300 MiB → `Start` по набору §8 → приёмка возврата. Плюс
`python3 scripts/k8s_health.py --brief` (код 0) — стенд после теста не деградировал. Без команды владельца
BeeLlama остаётся `RUNNING`, а gemma/whisper — `Stopped`: это штатное состояние окна, не забытая уборка.

**B7 — состояние «оставить как есть»:** backend зарегистрирован и `enabled`; модель существует,
`replicas: 0` (0 VRAM); каталог модели и `~/beellama-dist`, `~/models/*.gguf` на месте; ключ `beellama-test`
остаётся. Повторный прогон = новая команда владельца (§5) → B1 → `Start` → B5 → B6.

## 8. Что именно возвращать (снято с живого API 2026-10-29)

| Поле | `gemma-4-12B` (id 1) | `whisper-turbo` (id 2) |
|---|---|---|
| backend / version | `vLLM` / `0.25.1` | `VoxBox` / `0.0.21` |
| source / local_path | `local_path` / `/var/lib/gpustack/models/gemma-4-12B-it-qat-w4a16-ct` | `huggingface` (кэш `/var/lib/gpustack/models/faster-whisper-large-v3-turbo-int8`) |
| backend_parameters | `--gpu-memory-utilization 0.63` (10-29 было 0.68 — правка живьём), `--enable-auto-tool-choice`, `--tool-call-parser gemma4`, `--max-model-len 8192` | — |
| worker_selector | — | `{"worker-name":"k8s-04"}` |
| gpu_selector | `{"gpu_ids":["k8s-04:cuda:0"],"gpus_per_replica":1}` | — |
| categories / replicas | `llm` / 1 | `speech_to_text` / 1 |
| access_policy | `authed` | `authed` |

**Набор возврата (подтверждён владельцем 11-02):** `Qwen3Guard-Gen-4B` (id 5; vLLM 0.25.1, `huggingface`,
`--gpu-memory-utilization 0.80 --max-model-len 32768 --max-num-seqs 4 --enforce-eager`, worker `k8s-04`,
replicas 1 — третий резидент, появился после 10-29, ADR-0008) → `Start`; `gemma-4-12B` и `whisper-turbo`
остаются `Stopped`, как до окна. Старая формулировка («gemma + whisper `RUNNING`, ≈14 900–15 100 MiB» —
gemma 12632 + whisper 2296 + оверхед) применяется только если владелец явно её вернёт. `Stop`/`Start` поля не
меняет — «пересоздавать» модели нельзя (правка конфига через API подхватывается только пересозданием инстанса).

## 9. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-B1** | Два инстанса на одной карте → CUDA OOM: custom backend заявляет планировщику синтетические 0.5 GiB | строгая последовательность B1 → B4 → B6, `replicas ≤ 1`; при OOM — `Stop` beellama, потом `Start` целевых |
| **R-B2** | Нет `libstdc++`/`libgomp`/`libcudart` в образе | всё в каталоге (`cuda-libs/`, `hostlibs/`) + `LD_LIBRARY_PATH`; гейт B2 ловит до GPUStack; fallback — §11 |
| **R-B3** | shlex портит JSON-флаг | кавычки как в B3; симптом — `invalid chat template kwargs` / мгновенный `Exited` |
| **R-B4** | Health-check 1 с при загрузке 40–90 с | GPUStack поллит до готовности; стартовое окно увеличить негде — временно снять `health_check_path` (без него custom backend всегда «готов») и проверять `/health` руками |
| **R-B5** | Забыли B6 — gemma/whisper не вернулись | B6 обязателен, гейт по `nvidia-smi`, затем `k8s_health.py --brief` |
| **R-B6** | Access Control сломал ключи демо | новый ключ `beellama-test`; `owu/spk/rag/her` не трогаем |
| **R-B7** | Демо показывают во время теста | окно только без демо: чат/транскрибация на время теста недоступны |
| **R-B8** | Hardlink «поедет» при обновлении BeeLlama | после апгрейда повторить B2-гейт (`--list-devices`) |
| **R-B9** | Модель оставлена `replicas: 1` → 15.5 GiB занято, демо-модели не стартуют | B7 фиксирует `Stopped`; `nvidia-smi` после каждого теста |
| **R-B10** | Каталог вне git и вне бэкапа | воспроизводится B2 за ~2 мин (hardlink + cp), модель — с HF; это не данные |

## 10. Запрещено

- Менять флаги RUNBOOK §6 «на своё усмотрение» (особенно `-ctk/-ctv`, `--kv-tail-tokens`, `-fa on`, `-kvu`,
  `--spec-draft-n-max`): тест существует, чтобы сравнить с `bench-results.json`.
- Удалять/«пересоздавать» `gemma-4-12B` и `whisper-turbo` вместо `Stop`/`Start`, править их
  `backend_parameters`, трогать ключи демо.
- Удалять `~/beellama-dist`, `~/models/*.gguf`, `/var/lib/gpustack/models/beellama-qwen38` после теста.
- Править `gitops/infra-apps/gpustack/values-gpustack.yaml`, `gpustack-spec.md`, ADR: путь тестовый, в
  архитектуру не входит. Удачный тест → отдельная спека и отдельное решение (тогда осознанно пересматриваются
  `gpustack-spec` §1 и ADR-0007).
- `kubectl delete pod`/`scale` вместо UI `Stop` (состояние в БД GPUStack разъедется).

## 11. Fallback: собственный образ (если базовый не годится)

```dockerfile
FROM nvidia/cuda:13.3.0-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY v0.4.8/ /opt/beellama/
ENV LD_LIBRARY_PATH=/opt/beellama/cuda-libs:/usr/local/cuda/targets/x86_64-linux/lib
```

Сборка/пуш — только amd64 (`docker buildx build --platform linux/amd64`), тег `ghcr.io/msklv/beellama:0.4.8-cuda13.3`;
`cuda-libs/` — в образе или в каталоге модели. В `version_configs` меняется только `image_name`,
`run_command` и `default_env` те же. Нода тянет образ из `ghcr` напрямую (локального реестра на стенде нет).

## 12. Открытые вопросы

1. **Ключ для приёмки через шлюз:** отдельный `beellama-test` (рекомендация — чужие ключи не ломаются при
   возврате моделей) или расширение Access Control существующего?
2. **`meta.max_model_len`** в карточке модели: для custom backend контекст не режется и валидацию
   пропускает — поле только как документация (128000).
3. **Вторая 27B-конфигурация** (другой квант/контекст): отдельный `local_path` + отдельная версия бэкенда, без
   переиспользования каталога (иначе hardlink-дрифт).

## 13. История версий

| Версия | Дата | Что |
|---|---|---|
| v1.6 | 2026-11-28 | Сокращение без изменения фактов: методика — только обязательные условия и эталон, фазы без повторов, §8–§12 сжаты. Статус окна и гейты прежние |
| v1.5 | 2026-11-09 | Повторный замер в том же окне (§5 строка 2): `run_salt` 88101/88102, порт 40001, decode 80.8/65.4/42.5; §2 — карта в живом замере 5070 Ti; эталон заменён на 11-09, 5060 Ti оставлен историей |
| v1.4 | 2026-11-02 | Исполнение B0–B5 в окне 02–03.11: приёмка §1 закрыта кроме B6; B3a — грабли API-пути; инстанс `-wxqeh` :40017, decode 44.7/38.6/21.7, needle PASS @97K |
| v1.0 | 2026-10-29 | Первая версия: живые факты, схема custom backend, фазы B0–B7, параметры возврата, риски R-B1…R-B10 |

## 14. Связанные документы

- `host-beellama/runbook-host-run.md` §6 — эталонные флаги `llama-server` (источник `run_command`), §7 приёмка, §8 needle.
- `host-beellama/deploy-report-2026-10-16.md` — замеры на k8s-04 (15096 MiB idle / 15524 @122K, decode 43 tok/s, needle 60K/122K PASS).
- `host-beellama/README.md` — сводные замеры и `bench_speed.py`.
- `architecture/specs/gpustack-spec.md` §1 (бэкенд — vLLM), §4.5 (модели/local_path), §7 (Stop вместо scale), R-G9 (нет admin-ключа).
- `adr/adr-0007-model-roster-and-gpu-budget.md` — модельный набор 16-ГБ карты k8s-04 (в силе, этим тестом не пересматривается).
