# Проксирование LLM к внешнему провайдеру (`llm.demo-ai-lab.ru`) — JWT, плагины, приёмка

> **Версия:** v1.3 (2026-11-05) · **Статус:** **развёрнуто 2026-10-29**, два хоста — `llm.` (JWT Keycloak)
> и `llm-svc.` (статический ключ для сервисов). Приёмка по §4: `llm.` без токена → `401`,
> `llm-svc.` с ключом → `200` (`/v1/models` отдаёт `deepseek-flash`, `deepseek-v4-pro`), без ключа → `401`;
> **P4-стрим (SSE ≥180 с) не снят**. Сценарий **ADR-0008**, **шаг 3 демо**. Решение и границы — в ADR-0008, здесь механика.
> **С 2026-11-02 (ревизия ADR-0008) в работе только `llm-svc.`** со статическим ключом: поднаправление
> «ключи от SSO» (`llm.`, JWT Keycloak) приостановлено, поэтому фазы P1–P6 ниже описывают оба хоста,
> но исполняются/принимаются по сервисному пути; `llm.` не снимается.
> **2026-11-05:** предел тела запроса на llm-хостах поднят с 32 КиБ (HTTP/1.1) / 64 КиБ (HTTP/2) до
> **1 МиБ** — шлюз отбивал `413 Payload Too Large` RAG-чаты OWU (тело 33 617 B). Замеры, причины и
> правка — §2.1.
> **Цель:** маршрут `llm.` со своей авторизацией, DLP, стражем, лимитами и аудитом; все средства
> защиты — на стенде (см. ADR-0008, принципы 1–3). Буква фаз — **P** (F/E/K/M/G/O/S/D/Y/L заняты).

## 1. Решения

| Параметр | Решение | Обоснование |
|---|---|---|
| Провайдер | `ai-proxy`, `provider.type: deepseek`, `apiTokens` из Secret, домен `api.deepseek.com` | провайдер есть на пине: `plugins/wasm-go/extensions/ai-proxy/provider/deepseek.go` в теге `v2.1.9` |
| Авторизация | **JWT Keycloak realm `dev`**, grant `client_credentials`, TTL access-token 5 мин + **отдельный хост `llm-svc.` со статическим `x-api-key`** для сервисов, у которых нет Keycloak-клиента | без статических ключей на пользовательском хосте: `key-auth` положил бы креды в конфиг плагина, т.е. в gitops. Два хоста, а не два плагина на одном: на одном домене Higress требует прохождения **обоих** auth-плагинов, ответы конкурируют по фазам (проверено). DLP/страж/квоты/`ai-proxy` привязаны к обоим доменам |
| Проверка подписи | `jwt-auth`: `issuer` + **inline JWKS** (публичные ключи) | в v2.1.9 `jwks` — строка JSON, загрузки по URL нет |
| Проверка `aud`/ролей | `opa`-политика (`aud` содержит `llm` **или** роль `llm.invoke`) | `jwt-auth` проверяет только подпись, `iss`, `exp` — `aud` и scopes не проверяет |
| Higress в SSO | **не регистрируется** (не OIDC-клиент, а верификатор): ни client_secret, ни redirect | `oidc`-плагин — браузерный вход на cookie, для OpenAI-API не годится |
| Квоты | `ai-token-ratelimit` по `x-consumer` (claim `azp` через `claims_to_headers`) | Redis — Valkey в ns `llm` (`gitops/apps/llm/10-valkey.yaml`) |
| DLP и страж | `ai-data-masking` + `ai-qwen-guard`, **fail-closed** на внешнем маршруте | ADR-0006 + ADR-0008, принцип 2 |
| Предел тела запроса | `downstream.connectionBufferLimits: 1048576` + `downstream.http2.initialStreamWindowSize: 1048576` в `higress-config` | плагины маршрута (`opa`, DLP, страж) обязаны прочитать тело целиком → Envoy его буферизует, а потолок задаёт слушатель. Чартовый дефолт (32 КиБ h1 / 65 535 B h2) рвал RAG-чаты OWU `413 Payload Too Large` (§2.1). 1 МиБ — дефолт самого Envoy для `per_connection_buffer_limit_bytes` и `client_max_body_size` nginx; покрывает полный контекст 128K токенов и вставку файла ~1 МБ, по памяти на нашем профиле нагрузки бесплатен |
| Ограничение egress | **белый список на уровне ISP и внешних роутеров** (решение владельца 2026-10-29) | стенд свой фильтр не настраивает; из пода egress выглядит открытым (`example.com` → 200) — это ожидаемо, ограничение стоит выше по пути |

## 2. Живые факты (2026-10-29)

| Что | Факт |
|---|---|
| Egress подов | `api.deepseek.com/v1/models` → `401` за 0.44 s; `cdn.deepseek.com` → `200`, 48.9 KB за 0.21 s (под в `demo-test` на k8s-01) |
| Плагины в `higress-system` | только поставки GPUStack (`gpustack-ai-proxy` 2.0.0-patched, `ai-statistics`, `llm-ext-auth`, `model-mapper`, `model-router`, `token-usage`); `jwt-auth`/`opa`/`ai-data-masking`/`ai-token-ratelimit` не установлены |
| Приоритеты плагинов (Authentication phase) | `opa` 225 · `key-auth` 310 · `oidc` 350 · `jwt-auth` 350 · `ai-data-masking` 991 → OPA исполняется **до** проверки подписи, DLP — после аутентификации |
| Keycloak | 26.8.1, `https://auth.demo-ai-lab.ru`, realm `dev`; клиенты шагов 2–3 уже есть (`owu`, `spk`, `gps`, `agent-runtime`, `smoke-cli`) |
| Ветки `aud` в токене | Keycloak отдаёт `aud` строкой или массивом (audience mapper добавляет значение в массив) — политика обязана принимать оба вида |
| Egress и allowlist | белый список реализуется на уровне **ISP и внешних роутеров** (решение владельца 2026-10-29); со стенда не настраивается и замером из пода не проверяется |
| Аккаунт провайдера | **оплачен** (2026-10-29) — блокер «нет доступа к API» снят; баланс/квоты — под ротацией ключа (§5) |

### 2.1 Предел тела запроса — `413 Payload Too Large` (правился 2026-11-05)

**Симптом.** 2026-11-04, OWU-чат с RAG: в диалоге «Payload Too Large», в логе пода OWU
`413, message='Attempt to decode JSON with unexpected mimetype: text/plain'` на
`https://llm-svc.demo-ai-lab.ru/v1/chat/completions`; в access-логе шлюза —
`response_code=413`, `response_code_details=request_payload_too_large`, `bytes_received=33617`,
`user_agent=Python/3.11 aiohttp` (OWU ходит по **HTTP/1.1**).

**Причина — сам шлюз, не провайдер и не клиент.** На маршрутах `llm.`/`llm-svc.` плагины (`opa`,
`llm-data-masking`, `llm-qwen-guard`) обязаны прочитать тело запроса, поэтому Envoy его буферизует,
а размер буфера ограничен настройкой слушателя. `413` — локальный ответ Envoy (`server: istio-envoy`,
`text/plain`, тело ровно `Payload Too Large`), до `api.deepseek.com` запрос не уходит. На хостах
`owu.`/`api.` тело не буферизуется: 70 КБ по HTTP/1.1 проходят до приложения (проверено), поэтому
симптом виден только на llm-хостах.

**Замеренные потолки** (тело = JSON `/v1/chat/completions`, граница с точностью до байта):

| протокол | до правки | после правки | откуда значение |
|---|---|---|---|
| HTTP/1.1 | **32 768 B** (32768 → доходит, 32769 → `413`) | **1 048 576 B** (1048576 → доходит, 1048577 → `413`) | `downstream.connectionBufferLimits` |
| HTTP/2 | **65 535 B** (65535 → доходит, 65536 → `413`) | **1 048 576 B** | `downstream.http2.initialStreamWindowSize` |

Точное совпадение границ со значениями чарта `higress-core` 2.1.9 (32 768 / 65 535) — и есть
доказательство, что лимит оттуда, а не из плагина: правка потолка в `higress-config` сдвинула границу
на новое значение в обоих протоколах.

**Почему 1 МиБ, а не «как у upstream»** (там `10485760`): буферы Envoy выделяются по требованию, но
потолок памяти = лимит × число соединений, которые одновременно буферизуют тело. Под шлюза держит 6 GiB
(F8) и уже ловил OOM на 4 GiB; сейчас RSS ≈1.85 GiB на под. При 1 МиБ сотня одновременных больших
запросов — +100 МиБ (демо-нагрузка — единицы клиентов), при 10 МиБ 400 соединений на публичный `owu.`
= 4 GiB → OOM. Легитимный максимум, который надо покрыть: RAG-ход с историей 100–300 КБ, вставка файла
в чат до ~1 МБ, полный контекст 128K токенов (`deepseek-flash`) — 300–350 КБ. Всё, что больше, упрётся
в контекст модели и вернёт её `400 context length` — правильная ошибка вместо шлюзовой.

**Правка** (подхватывается шлюзом через xDS, поды не пересоздаются, дренаж слушателей штатный):

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl -n higress-system get cm higress-config -o jsonpath='{.data.higress}'   # блок downstream
# правка: downstream.connectionBufferLimits и downstream.http2.initialStreamWindowSize → 1048576
kubectl -n higress-system patch cm higress-config --type=merge -p '{"data":{"higress":"<полный YAML>"}}'
# приёмка: подтянулось ли до слушателей (active_state, не draining_state)
kubectl -n higress-system exec <pod> -c higress-gateway -- curl -s localhost:15000/config_dump \
  | grep -o '"per_connection_buffer_limit_bytes":[0-9]*'
```

Приёмка после правки (ключ `llm-svc` — из приватного хранилища, в команду не печатать): тело 33 617 B
и 300 КБ по `--http1.1` → `400` от провайдера; 1 048 576 B → `200`; 1 048 577 B → `413`.

**Дрейф с релизом.** `higress-config` рендерится helm-релизом `higress`, поэтому `helm upgrade`
вернёт чартовые 32 КиБ (и 2 GiB памяти шлюзу — см. F8). Правку переносить в values **вместе** с памятью,
осознанно, а не `--reuse-values`.

## 3. Токены: как формируются

- **Сервисы** (`owu`, `qm`, `her`, агентский рантайм): `POST https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/token`,
  `grant_type=client_credentials`, `client_id=llm-<svc>`, секрет — из Secret сервиса (не git).
  В токене: `iss`, `azp=llm-<svc>`, `aud` c `llm`, роль `llm.invoke`, `exp` ≈ +5 мин.
- **Человек напрямую** (сцена, приёмка): публичный клиент `smoke-cli` с direct access grant — токен
  живёт минуты, выдаётся вручную; в UI человек идёт в OWU/агент, а не в `llm.`.
- **Шлюз**: `jwt-auth` проверяет подпись по JWKS, `iss == https://auth.demo-ai-lab.ru/realms/dev`,
  `exp` (±60 c skew); `claims_to_headers: azp → x-consumer`. Затем `opa` решает доступ по `aud`/роли,
  затем `ai-data-masking`, `ai-qwen-guard`, `ai-proxy` (ключ провайдера из `apiTokens` — токен
  потребителя наружу не уходит), `ai-token-ratelimit`, `ai-statistics`.
- **Объекты Keycloak, которые надо завести**: клиенты `llm-owu`/`llm-qm`/`llm-her`/`llm-agent`
  (confidential, service accounts enabled), audience mapper `llm`, роль `llm.invoke` (realm-роль,
  выдана сервисным аккаунтам), TTL access-token 5 мин.

## 4. Фазы P1–P6 (приёмка — командой, не глаголом)

### P1 — Keycloak: клиенты, `aud`, роль
Завести клиентов/маппер/роль (скрипт `scripts/keycloak_seed.py` — upsert, как для `gps`/`owu`).
Приёмка: `curl -s -d grant_type=client_credentials …` → токен; декод payload показывает `aud`
со `llm` и роль `llm.invoke`; токен протухает через ~5 мин (`exp`).

### P2 — `jwt-auth` на хост `llm.`
`WasmPlugin jwt-auth`: consumer `llm-jwt` (`issuer`, inline JWKS из
`/realms/dev/protocol/openid-connect/certs`, `claims_to_headers`).
Приёмка: без токена → `401 jwt-auth.token_missing`; протухший → `401 jwt-auth.token_expired`;
валидный → запрос доходит до `ai-proxy`.

### P3 — OPA (обязательно, иначе `aud` не проверяется)
Deployment OPA (Apache-2.0, политика в ConfigMap, `serviceSource: k8s`) + `Service`; политика:
`allow`, если в `aud` есть `llm` или в `realm_access.roles` — `llm.invoke`.
Приёмка: токен **без** `llm` в `aud` (например от `owu`) → отказ (`opa.server_not_allowed`);
токен с `llm` → пропуск. Политика принимает `aud` и строкой, и массивом.

### P4 — маршрут и `ai-proxy`
Ingress `llm` + `Certificate` (ns маршрута) + `WasmPlugin ai-proxy` (`provider.type: deepseek`,
`apiTokens` из Secret `llm-deepseek`, `modelMapping`).
Приёмка: `POST /v1/chat/completions` с `deepseek-flash` → `200` и ответ провайдера;
`GET /v1/models` → список моделей DeepSeek; ключ провайдера в логах и заголовках не появляется.

### P4-стрим — SSE через аплинк (критерии R-P5)

Длинный ответ идёт через ISP-роутеры с allowlist'ом, поэтому стрим проверяется отдельно и до сцены.

```bash
# токен сервисного клиента (секрет — из приватного хранилища, не в команду)
TOKEN=$(curl -s -d grant_type=client_credentials -d client_id=llm-agent \
  -d client_secret="$LLM_AGENT_SECRET" \
  https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/token | jq -r .access_token)

curl -N -sS -m 360 -D /tmp/stream.hdr -o /tmp/stream.out \
  -w 'code=%{http_code} ttft=%{time_starttransfer} total=%{time_total} bytes=%{size_download}\n' \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-flash","stream":true,"max_tokens":3000,
       "messages":[{"role":"user","content":"Напиши подробный технический текст на 1800 слов про мониторинг Kubernetes"}]}' \
  https://llm.demo-ai-lab.ru/v1/chat/completions

grep -c '^data:' /tmp/stream.out; tail -2 /tmp/stream.out   # чанки и финал потока
```

| Критерий | Чем измеряем | Порог приёмки |
|---|---|---|
| Соединение не рвётся | `curl -N`, `-m 360`, код выхода | `rc=0`, ни одного `reset`/`timeout` |
| Длительность | `total=` из `-w` | ≥ 180 с непрерывной генерации |
| Первый байт (TTFT) | `ttft=` из `-w` | ≤ 5 с |
| Число чанков | `grep -c '^data:'` | ≥ 200 |
| Финал | последние строки `stream.out` | `finish_reason: stop` и `data: [DONE]` |
| Код | `code=` из `-w` | `200` |
| Повторяемость | 3 прогона подряд с интервалом 1 мин | 3/3 по всем строкам выше |

Результат заносится в §2 с датой и значениями (`ttft`, `total`, чанки). Если критерий не выполнен —
это дефект канала, а не «иногда бывает»: лечение по порядку — (1) `stream:false` для длинных ответов,
(2) маршрут наружу через внешнюю VM-egress (E7) вместо прямого NAT.

### P5 — DLP, страж, лимиты
`ai-data-masking` (словарь + `restore`), `ai-qwen-guard` (fail-closed), `ai-token-ratelimit`
(токены/мин + суточная квота на `x-consumer`).
Приёмка: в промпте телефон/e-mail → наружу уходит плейсхолдер (видно в теле запроса к провайдеру /
в логе плагина), в ответе клиенту — исходное значение; `Unsafe`/`Jailbreak` → блок; при остановленном
страже — запрос **не уходит** (5xx/block), а не проходит без проверки; превышение квоты → `429`.

#### Целевая настройка стража (2026-11-02, сделана в веб-интерфейсе GPUStack/Higress)

**Внешний ID модели стража — `Qwen3Guard-Gen-4B` и он не меняется.** По этому ID зовёт и плагин
`llm-qwen-guard` (`model: Qwen3Guard-Gen-4B`), и любой внешний потребитель; смена версии стража не
требует правок ни в плагине, ни у клиентов.

| Слой | Что стоит | Факт |
|---|---|---|
| GPUStack, страж кейсов 02/05/06 | **`Qwen3Guard-Gen-4B`** (`Qwen/Qwen3Guard-Gen-4B`, vLLM), ≈12.7 GiB — страж для всех кейсов с внешним вызовом (02 — блокировка, 05 — RAG, 06 — агенты) | с ASR на одной карте не уживается: проверено 02.11 — `whisper-turbo` уходит в `replicas=0`, транскрибация `404` |
| GPUStack, страж кейса 03 (ASR) | **`Qwen3Guard-Gen-0.6B`** (`Qwen/Qwen3Guard-Gen-0.6B`, vLLM), ≈1.4 GiB — `replicas=1`, инстанс `Qwen3Guard-Gen-0.6B-3ihgo` на k8s-04 | влезает рядом с `whisper-turbo` (≈2.3 GiB): сумма ≈3.7 из 15.93 GiB. В этом режиме `4B` остановлена; оба варианта отвечают на один ID |
| Маршруты Higress | `ai-route-route-4.internal` (основной) + **`ai-route-route-4.fallback.internal`** (резервный), у обоих `higress.io/exact-match-header-x-higress-llm-model: Qwen3Guard-Gen-4B`, `destination: 100% model-4-32.static:80` | два маршрута на один внешний ID: пока жив исполнитель 0.6B, запрос с `model: Qwen3Guard-Gen-4B` обслуживается им — прямой вызов вернул `200` за 0.12 с и `model: Qwen3Guard-Gen-0.6B` в ответе |
| Ключ GPUStack `guard` (id 7) | `allowed_model_names`: `Qwen3Guard-Gen-4B`, `qwen3guard-gen-4b`, `qwen3guard-gen-0.6b`, `guard` | ключ обязан пускать обе версии, иначе резерв даёт `403 Not allowed to access model` → fail-closed |
| Авторизация `llm-svc.` | `key-auth` с **двумя консьюмерами на один статический ключ**: `llm-svc` (credential = ключ, вход `x-api-key`) и `llm-svc-bearer` (credential = `Bearer <ключ>`, вход `authorization`); `keys: [x-api-key, authorization]` | OpenAI-совместимые клиенты (Speakr, OpenAI SDK) шлют `Authorization: Bearer`, скрипты зала — `x-api-key`. Без второго консьюмера Speakr получал `Request denied by Key Auth check. No Key Authentication information found` (проверено 02.11: 401 → после правки 200) |
| Плагин `llm-qwen-guard` | `serviceHost: api.demo-ai-lab.ru`, `model: Qwen3Guard-Gen-4B`, `failOpen: false`, `timeout: 8000` | рендерится `scripts/llm_proxy_plugins.sh`; при смене версии стража **не перерендеривается** |

Следствие: `llm-svc`/`llm.` отвечают `200` с живым стражем, пока в GPUStack запущена **любая** модель,
которую GPUStack отдаёт под ID `Qwen3Guard-Gen-4B`. Проверено 2026-11-02: `llm-svc` + `deepseek-flash`
→ `200` за 1.76 с, `reasoning_tokens` 145, контент непустой.

### P6 — негативные и откат
Приёмка: отзыв роли `llm.invoke` → отказ в течение TTL; снятие Ingress-маршрута `llm` → `api.`
(локальные модели) отвечает `200` как раньше; повторный подъём — тем же коммитом.

## 5. Ротация ключей

Два разных секрета — две разные процедуры; путать их нельзя.

**5.1 Ключ провайдера DeepSeek.** Живёт в Secret `llm-deepseek` (не git). `WasmPlugin` в Higress
принимает конфиг **только инлайном** — `spec.config` не умеет ссылаться на Secret, поэтому объект
плагина рендерится скриптом `scripts/llm_proxy_plugins.sh` из Secret и живёт **вне Argo** (как
`higress-console`/`gpustack`); в git — шаблон с placeholder'ом, не значение.

**Смена хоста/домена — только вместе с перерендером.** Домены матчинга есть и в шаблоне (git), и в уже
отрендеренных объектах `llm-key-auth`, `llm-ai-proxy`, `llm-qwen-guard`, `llm-jwt-auth` — последние
вне Argo. Правки в git создают Ingress и обновляют Argo-объекты (`ai-data-masking`,
`ai-token-ratelimit`), но `ai-proxy` продолжает матчить **старый** домен, и новый хост отвечает `403`
без внятной причины. Порядок: правка git → push (Argo) → `scripts/llm_proxy_plugins.sh` → проверка
`/v1/models` с ключом. Поймано 2026-11-01 при переименовании `llm-test.` → `llm-svc.`.

В v2.1.9 у `ai-proxy` `apiTokens` — **массив**, токен на запрос выбирается случайно
(`GetRandomToken`), и есть штатный `failover`: недоступный токен выводится из ротации, проверяется
health-check'ом и возвращается, когда снова работает (`provider/failover.go`:
`enabled`, `failureThreshold`, `successThreshold`, `healthCheckInterval`, `healthCheckModel`,
`failoverOnStatus`). Отсюда ротация **перекрытием, без простоя**:

1. В `platform.deepseek.com/api_keys` создать ключ `demo-lab-<YYYY-MM>` (платформа держит несколько ключей с именами).
2. Добавить его в Secret вторым полем; перерендерить плагин: `apiTokens: [old, new]` → `kubectl apply`.
   Перезагружается конфиг wasm, gateway **не** рестартует.
3. Проверка: 20 запросов `POST /v1/chat/completions` (или `GET /v1/models`) → все `200`, в
   `ai-statistics`/access-логе нет `401` от провайдера.
4. Удалить старый ключ в платформе; перерендерить плагин с `apiTokens: [new]`.
5. Приёмка: `200`, `401` нет, `nvidia`-путь не затронут (ключ живёт на шлюзе, не на карте).

**Экстренный отзыв (компрометация).** Ключ удаляется в платформе; `failover` сам выводит его из
ротации после `failureThreshold` отказов, новый вставляется сразу тем же скриптом. Окно отказа —
до `failureThreshold` запросов, не «до следующего релиза». Включить в конфиг: `enabled: true`,
`failoverOnStatus: ["401","429"]`, `failureThreshold: 3`, `successThreshold: 2`,
`healthCheckInterval: 30s`, `healthCheckTimeout: 5s`, `healthCheckModel: deepseek-flash`.

**Триггеры:** планово раз в 90 дней; смена людей с доступом к платформе; подозрение на утечку
(скриншот, лог, тикет); смена биллинга. Детект «ключ мёртв» — доля `401` на маршруте `llm.`
(оба ключа невалидны → клиент получает отказ: это алерт, а не штатная деградация).

**5.2 Секреты и ключи Keycloak** (внутренняя сторона JWT): секрет клиента `llm-<svc>` —
regenerate в Keycloak → новое значение в Secret сервиса → rollout; старые токены доживают максимум
TTL (5 мин). Ключи подписи realm — только с перекрытием: сначала в Keycloak появляется новый активный
ключ (**старый остаётся** и его `kid` есть в JWKS), затем обновляется inline JWKS в `jwt-auth`
(публичные ключи, правка в git), и только после истечения старых токенов старый ключ отключается в
realm. Обратный порядок даёт `401 jwt-auth.verification_fails` на живых токенах.

## 6. Риски

| Риск | Что делаем |
|---|---|
| **R-P1** `jwt-auth` не проверяет `aud`/scopes | OPA-чек обязателен и входит в приёмку P3; без него маршрут не считается готовым |
| **R-P2** JWKS inline — ротация ключей Keycloak ломает проверку | в конфиг кладутся все активные `kid`; при ротации — правка плагина (публичные ключи, git допустим), проверка P2 повторяется |
| **R-P3** OPA — ещё один под на 02/03 | stateless, политика в ConfigMap, лимиты 64Mi/128Mi; при недоступности OPA запросы отклоняются (fail-closed) |
| **R-P4** Секреты клиентов `llm-*` | только в Secret сервисов (не git), шаблон — `scripts/*.local` (gitignored) |
| **R-P5** Длинный SSE-стрим через аплинк | **критерии приёмки — «P4-стрим» в §4** (rc=0, ≥180 с, TTFT ≤5 с, ≥200 чанков, `[DONE]`, 3/3 прогона); результат — в §2 с датой |
| **R-P6** Оплата аккаунта DeepSeek из РФ | **закрыт 2026-10-29**: аккаунт оплачен (владелец); остаётся следить за балансом/квотой ключа ротацией (§5) |
| **R-P7** Где реализован белый список egress | **решено 2026-10-29**: allowlist — на уровне **ISP и внешних роутеров** (владелец); на стенде фильтр не настраивается, поэтому замер из пода ничего не доказывает (`example.com` → 200 — ожидаемо). Проверка ограничения — на стороне провайдера/аплинка, не командой из кластера; для маршрута `llm.` существенно лишь то, что `api.deepseek.com` в списке разрешённых |

## 7. Связанные документы и история

ADR-0008 (решение), ADR-0006 (DLP/страж), ADR-0001 (единственный ingress и LLM-шлюз), ADR-0007
(локальный набор), `architecture/endpoints.md` (адрес `llm.`), `gitops/apps/llm/` (каталог маршрута — задеплоен, Application `llm` Synced/Healthy).

- **v1.0** (2026-10-29): первая редакция под решение ADR-0008; факты по плагинам сверены по исходникам
  тега `v2.1.9`, egress замерен подом на стенде.
- **v1.1** (2026-11-01): второй хост `llm-svc.` со статическим ключом (переименован из `llm-test.`;
  грабля — домены матчинга в отрендеренных плагинах, §5.1); OOM gateway при reload — лимит поднят до 3072Mi
  (`ansible/values-f8.yaml`, `rollingMaxSurge: 0`).
- **v1.2** (2026-11-02): целевая настройка стража в §P5 (внешний ID `Qwen3Guard-Gen-4B` не меняется,
  в кейсе 03 исполняет `0.6B`), второй консьюмер `llm-svc-bearer` на `Authorization: Bearer` (Speakr);
  `llm.` приостановлен (ревизия ADR-0008), маршрут не снят.
- **v1.3** (2026-11-05): **предел тела запроса на llm-хостах → 1 МиБ (§2.1).** `413 Payload Too Large`
  от шлюза рвал RAG-чаты OWU: тело 33 617 B при потолке 32 768 B по HTTP/1.1 (OWU ходит aiohttp).
  В `higress-config` подняты `downstream.connectionBufferLimits` 32 768 → **1 048 576** и
  `downstream.http2.initialStreamWindowSize` 65 535 → **1 048 576**; границы замерены до/после
  (32 768/32 769 и 65 535/65 536 → 1 048 576/1 048 577). Оговорка: `higress-config` рендерится
  helm-релизом `higress`, `helm upgrade` вернёт чартовый дефолт вместе с памятью 2 GiB (F8).
