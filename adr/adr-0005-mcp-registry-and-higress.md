# ADR-0005: MCP на стенде — официальный реестр и Higress вместе

- Дата: 2026-10-24
- Статус: **Accepted** (решение владельца 2026-10-24: «сравни реестр с Higress, итог — совместное
  использование»).
- Ревизия 2026-10-24 (2): **решение изменено владельцем — `modelcontextprotocol/registry` ставим и
  используем на демо**; первоначальная редакция («реестр не ставим, только Higress») отменена.
  Развёртывание — `architecture/specs/mcp-registry-spec.md`, адрес — `mcp.demo-ai-lab.ru`.

## Контекст

Шаг 3 демо — агенты (qm, Hermes) вызывают инструменты через MCP; сервисы стенда (RAGFlow, Docling,
Open WebUI) должны быть доступны как MCP-инструменты, с нашей авторизацией и логами. Нужно было решить,
чем это закрывать: официальным реестром `modelcontextprotocol/registry`, возможностями Higress или обоими.

**`modelcontextprotocol/registry`** (github.com/modelcontextprotocol/registry):

- **Роль:** каталог («app store for MCP servers») — отдаёт клиентам **список** MCP-серверов; вызовы
  инструментов не проксирует, это не шлюз.
- **Стек:** Go + PostgreSQL (`MCP_REGISTRY_DATABASE_URL`), API v0.1 в заморозке; upstream-деплой —
  Pulumi (GCP staging/prod), k8s-манифестов нет — пишем свои.
- **Публикация:** проверка владения неймспейсом — GitHub OAuth, GitHub OIDC (из GH Actions),
  DNS-верификация домена, HTTP-верификация; выдача JWT (Ed25519 seed, `MCP_REGISTRY_JWT_PRIVATE_KEY`).
- **OIDC:** есть, но как **админский/привилегированный** вход (`MCP_REGISTRY_OIDC_ENABLED`,
  `..._OIDC_ISSUER`, `..._OIDC_CLIENT_ID`, `..._OIDC_EXTRA_CLAIMS`, `..._OIDC_EDIT_PERMISSIONS`,
  `..._OIDC_PUBLISH_PERMISSIONS`): Keycloak'ом закрывается вход админа и права публикации, а
  **верификация неймспейса остаётся GitHub- или DNS/HTTP-based** — «выдать `io.github.*` через Keycloak» нельзя.
- **Сиды:** `MCP_REGISTRY_SEED_FROM` — локальный файл или официальный реестр (зеркало);
  `ENABLE_REGISTRY_VALIDATION` валидирует записи.
- **Формат описания:** `server.json`; сервер публикуется либо как `packages` (npm/oci/nuget/pypi,
  транспорт `stdio`), либо как `remotes` (`type: streamable-http`/`sse` + `url`).

**Higress** (наш standalone `higress-core` 2.1.9):

- **Роль:** хостинг MCP-серверов и **шлюз вызовов**, не каталог.
- `mcp-server` plugin: REST → MCP без кода (`server.tools`, `requestTemplate`, `responseTemplate`, тип `rest`);
  mcp-proxy на готовый MCP-сервер (`server.mcpServerURL`, `transport: http|sse`, `protocolStrategy`);
  `toolSet` — объединение инструментов нескольких серверов; `allowTools` + динамическое ограничение
  через заголовок `x-envoy-allow-mcp-tools` (RBAC по инструментам на основе личности);
  `securitySchemes`/`defaultUpstreamSecurity`/`passthroughAuthHeader` для кредов к бэкенду; всё
  остальное от шлюза — auth-плагины, лимиты, аудит, метрики/трейсы.
- **Требования:** Higress ≥ 2.1.0; для SSE-сессий — Redis (`global.enableRedis=true`,
  `redis-stack-server`, `match_list` в ConfigMap `higress-config`); для streamable HTTP ConfigMap не нужен.
- **Источники сервисов:** `nacos3`, `nacos2`, `nacos`, `consul`, `zookeeper`, `eureka`, `static`, `dns`;
  **MCP поддержан только у `nacos3`** (Nacos ≥ 3.0, Higress ≥ 2.1.2). Официального реестра MCP
  в этом списке нет — прямой интеграции «реестр как source» не существует.
- **Условия стенда:** standalone gateway без консоли (`higress-core` + `ansible/values-f8.yaml`, Redis
  не включён) → MCP конфигурируется плагином/аннотацией и ConfigMap, без UI.

### Сравнение по задачам (основание решения)

| Задача | registry | Higress | Кто закрывает |
|---|---|---|---|
| Каталог MCP-серверов с версиями/метаданными | да (это его работа) | нет (только Nacos как внешний источник) | registry |
| Вызов инструмента, прокси, сессии | нет | да (SSE / streamable HTTP) | Higress |
| REST API → MCP без кода | нет | да (`mcp-server`) | Higress |
| Per-tool RBAC по личности | нет | да (`allowTools` + `x-envoy-allow-mcp-tools`) | Higress |
| Лимиты/аудит/трейсы вызовов | нет | да (штатные плагины шлюза) | Higress |
| Публикация с проверкой владения | да (GitHub/DNS/HTTP) | нет | registry |
| Вход через наш Keycloak | admin/права публикации (`MCP_REGISTRY_OIDC_*`); неймспейс — GitHub/DNS/HTTP | да: маршрут закрывается `oidc`/`jwt-auth`, личность идёт в RBAC инструментов | оба |
| Доп. компоненты | Go-сервис + PostgreSQL | Redis (только для SSE) | — |

## Решение

1. **`modelcontextprotocol/registry` ставим** (решение владельца 2026-10-24): ns `mcp-registry`,
   Deployment ×1 + PostgreSQL ×1 (PVC 8 Gi Longhorn), пара **k8s-02/03**, внешний адрес
   **`mcp.demo-ai-lab.ru`**, развёртывание через Argo CD — пины, env, публикация и приёмка M1–M5
   в `architecture/specs/mcp-registry-spec.md`.
2. **MCP-хостинг и вызовы инструментов — Higress:** `mcp-server` (REST→MCP на существующих маршрутах)
   и `mcp-proxy` (на MCP-серверы по их `remotes`-URL), `allowTools` по личности из Keycloak.
   Реестр вызовы не обслуживает — это его природа, а не ограничение настройки.
3. **Совместное использование — схемы 1 и 2 включаем, схема 3 отложена** (нативного чтения реестра
   Higress не умеет):

| Схема | Как | Что даёт | Ограничение |
|---|---|---|---|
| **1. Реестр = каталог, Higress = вызовы** | в `server.json` есть `remotes` (`streamable-http`/`sse` + `url`); в Higress маршрут `mcp-server` в режиме `mcp-proxy` (`server.mcpServerURL` = этот URL) | discovery отдельно, политика/лимиты/аудит вызовов на шлюзе, патчить ничего не нужно | только **remote**-серверы; серверы из `packages` (`stdio`) URL не имеют — их надо где-то запускать и заворачивать в `mcp-proxy` |
| **2. Реестр за шлюзом** | Ingress `mcp.demo-ai-lab.ru/v0/*` через Higress + `oidc`/`jwt-auth` + лимиты; чтение — публично, запись — по токену | каталог проходит через нашу авторизацию и логи шлюза, единый внешний вход | на вызовы инструментов не влияет: реестр остаётся каталогом |
| **3. Синхронизация реестр → Nacos 3.x** | джоб `GET /v0/servers` → регистрация MCP-сервисов в Nacos; в Higress service source `nacos3` | единственный путь к «нативной» интеграции | нужен свой коннектор (готового официального нет) + Nacos ≥ 3.0; отложено |

Чего совместно **не получится**: заставить Higress читать реестр напрямую как service source; заставить
реестр проксировать вызовы, считать лимиты или проверять права на инструменты — это не его роль.

4. **Уточнение по Keycloak (исправление прежней формулировки ARCHITECTURE §3):** «верификация
   неймспейсов заменяется `MCP_REGISTRY_OIDC_*` → Keycloak» — неверно. Верно: Keycloak закрывает
   админский доступ и права публикации в реестре; владение неймспейсом доказывается GitHub- или
   DNS/HTTP-верификацией `demo-ai-lab.ru` (неймспейс — `ru.demo-ai-lab/<server>`).

### Что нужно для MCP на Higress

1. Redis в `higress-system` **или** сразу streamable HTTP (предпочтительно — зависимости от Redis нет).
2. `mcp-server` на нужных маршрутах (REST→MCP) либо `mcp-proxy` для серверов из реестра.
3. `allowTools`/`x-envoy-allow-mcp-tools` связать с личностью (маршрут закрыт `oidc`/`jwt-auth`).
4. Отдельный хостнейм инструментам не нужен: маршруты живут под хостами сервисов, а
   `mcp.demo-ai-lab.ru` занят реестром-каталогом.

## Последствия

- **+1 сервис и +1 PostgreSQL**: реестр лёгкий (Go-бинарь, ресурсы подобрать по факту первого деплоя, PVC 8 Gi), но БД — SPOF
  (RTO 1–3 мин на переаттач тома Longhorn), как у Keycloak; для демо принимаем.
- Появляется «витрина» MCP-серверов: `GET https://mcp.demo-ai-lab.ru/v0/servers`, `/docs` — API самодокументируется.
- Вызовы по-прежнему идут через Higress: политика, лимиты, аудит и RBAC инструментов остаются в одном месте.
- API реестра — **preview v0.1** (заморожен, но до GA возможны изменения/сбросы): каталог не источник
  истины — `server.json` каждого своего MCP-сервера лежит в git рядом с его кодом, `architecture/endpoints.md`
  держит только адрес реестра.
- MCP-серверы, опубликованные только как `packages` (`stdio`), шлюзом не обслуживаются: для них нужен
  рантайм (под/сайдкар) и `mcp-proxy` поверх него.
- Конфигурация Higress без UI (standalone `higress-core`): правки — плагин/аннотация/ConfigMap, руками и в git.

## Альтернативы (рассмотрены и отклонены)

- **Только реестр, без шлюза** — нет политики вызовов, лимитов, RBAC по инструментам и аудита; реестр
  к тому же не проксирует. Отклонено.
- **Только Higress, без каталога** — было принято первой редакцией этого ADR (2026-10-24), **отменено
  в тот же день**: владелец решил ставить реестр и показывать витрину MCP-серверов на демо.
- **Nacos 3.x как каталог вместо реестра** — нативный источник для Higress, но не даёт публикации
  с проверкой владения и «витрины»; отложено.
- **Синхронизация registry → Nacos** — путь к нативной интеграции, требует коннектора и Nacos; отложено (схема 3).

## Ссылки

- `architecture/specs/mcp-registry-spec.md` — развёртывание реестра: пины, env, публикация, приёмка M1–M5.
- `architecture/endpoints.md` — адрес `mcp.demo-ai-lab.ru` и остальные публичные имена.
- `architecture/specs/keycloak-spec.md` §5.3/§9 — клиент `mcp` (OIDC-админ реестра) и SSO-периметр.
- `architecture/ARCHITECTURE.md` §3/§5/§7 — место MCP в целевой архитектуре, размещение, статус.
- `architecture/specs/k8s-install-spec.md` §10 — Higress/MCP в контексте инсталляции.
