# Проксирование LLM к внешнему провайдеру (`llm.demo-ai-lab.ru`) — JWT, плагины, приёмка

> **Версия:** v1.0 (2026-10-29) · **Статус:** **не развёрнуто** — спека под сценарий **ADR-0008**
> (безопасное проксирование к DeepSeek Platform), **шаг 3 демо**. Решение и границы — в ADR-0008, здесь механика.
> **Цель:** маршрут `llm.` со своей авторизацией, DLP, стражем, лимитами и аудитом; все средства
> защиты — на стенде (см. ADR-0008, принципы 1–3). Буква фаз — **P** (F/E/K/M/G/O/S/D/Y/L заняты).

## 1. Решения

| Параметр | Решение | Обоснование |
|---|---|---|
| Провайдер | `ai-proxy`, `provider.type: deepseek`, `apiTokens` из Secret, домен `api.deepseek.com` | провайдер есть на пине: `plugins/wasm-go/extensions/ai-proxy/provider/deepseek.go` в теге `v2.1.9` |
| Авторизация | **JWT Keycloak realm `dev`**, grant `client_credentials`, TTL access-token 5 мин | без статических ключей: `key-auth` положил бы креды в конфиг плагина, т.е. в gitops |
| Проверка подписи | `jwt-auth`: `issuer` + **inline JWKS** (публичные ключи) | в v2.1.9 `jwks` — строка JSON, загрузки по URL нет |
| Проверка `aud`/ролей | `opa`-политика (`aud` содержит `llm` **или** роль `llm.invoke`) | `jwt-auth` проверяет только подпись, `iss`, `exp` — `aud` и scopes не проверяет |
| Higress в SSO | **не регистрируется** (не OIDC-клиент, а верификатор): ни client_secret, ни redirect | `oidc`-плагин — браузерный вход на cookie, для OpenAI-API не годится |
| Квоты | `ai-token-ratelimit` по `x-consumer` (claim `azp` через `claims_to_headers`) | Redis — Valkey стека Langfuse |
| DLP и страж | `ai-data-masking` + `ai-qwen-guard`, **fail-closed** на внешнем маршруте | ADR-0006 + ADR-0008, принцип 2 |
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
Завести клиентов/маппер/роль (скрипт `scripts/keycloak_seed.py` — upsert, как для `gps`/`lng`).
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

### P6 — негативные и откат
Приёмка: отзыв роли `llm.invoke` → отказ в течение TTL; снятие Ingress-маршрута `llm` → `api.`
(локальные модели) отвечает `200` как раньше; повторный подъём — тем же коммитом.

## 5. Ротация ключей

Два разных секрета — две разные процедуры; путать их нельзя.

**5.1 Ключ провайдера DeepSeek.** Живёт в Secret `llm-deepseek` (не git). `WasmPlugin` в Higress
принимает конфиг **только инлайном** — `spec.config` не умеет ссылаться на Secret, поэтому объект
плагина рендерится скриптом `scripts/llm_proxy_plugins.sh` из Secret и живёт **вне Argo** (как
`higress-console`/`gpustack`); в git — шаблон с placeholder'ом, не значение.

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
(локальный набор), `architecture/endpoints.md` (адрес `llm.`), `gitops/` (каталог маршрута — при деплое).

- **v1.0** (2026-10-29): первая редакция под решение ADR-0008; факты по плагинам сверены по исходникам
  тега `v2.1.9`, egress замерен подом на стенде.
