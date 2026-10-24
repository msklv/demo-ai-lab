# MCP Registry на стенде (`mcp.demo-ai-lab.ru`)

Каталог MCP-серверов `modelcontextprotocol/registry` — сервис шага 3. Решение и схемы совместного
использования с Higress — `adr/adr-0005-mcp-registry-and-higress.md`; адрес — `architecture/endpoints.md`.

## Что это и зачем на стенде

Реестр хранит **метаданные** MCP-серверов (`server.json`: имя-неймспейс, версия, `packages`/`remotes`)
и отдаёт их клиентам по API v0. Он **не проксирует вызовы** — вызовы инструментов идут через Higress
(`mcp-server` plugin, `mcp-proxy` по `remotes`-URL из реестра). На демо реестр показывает «витрину»
своих MCP-серверов и служит источником URL для маршрутов Higress.

## Пины

| Компонент | Пин | Проверено |
|---|---|---|
| Registry | `ghcr.io/modelcontextprotocol/registry@sha256:c00bf81de156bc62cb61880dcc1ebec0372c6c661ac1bbeaac0da36551d960ec` (index, amd64-манифест `sha256:1bd72027…`) | `docker buildx imagetools inspect`, 2026-10-24 |
| PostgreSQL | `postgres:16-alpine@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36` | Docker Hub API, 2026-10-24 (версия как в upstream compose) |
| Порт / health | `:8080`, `GET /health` (также `/metrics`, `/docs`, `/ping`) | `internal/api/router/router.go` |
| API-префикс | `/v0/*` (алиас `/v0.1/*`) | там же |

## Размещение

- **ns `mcp-registry`**; Deployment ×1 (реестр лёгкий, Go-бинарь; requests/limits выставить по факту
  `kubectl top` после деплоя) + StatefulSet PostgreSQL ×1 (это лёгкая БД каталога, не data-heavy —
  поэтому живёт на паре 02/03, как БД Keycloak),
  PVC **8 Gi** Longhorn r=2.
- Узлы — **пара k8s-02/03** (ADR-0003: «каталоги и лёгкие сервисы»), soft-affinity, без hard-pin:
  k8s-04 занят GPUStack/инференсом, на 02/03 ~11 Gi свободно. PostgreSQL — SPOF, как у Keycloak
  (RTO 1–3 мин на переаттач тома) — для демо принимаем.
- Развёртывание — **Argo CD**, plain-манифесты в `gitops/infra-apps/mcp-registry/` (тот же паттерн,
  что `keycloak/`): Secret'ы Argo не создаёт и не удаляет.

## Конфигурация (env)

```
MCP_REGISTRY_SERVER_ADDRESS=:8080
MCP_REGISTRY_DATABASE_URL=postgres://<user>:<pass>@mcp-registry-db:5432/mcp-registry?sslmode=disable
MCP_REGISTRY_JWT_PRIVATE_KEY=<32-байтный seed, hex>        # из Secret
MCP_REGISTRY_ENABLE_ANONYMOUS_AUTH=false                   # dev-only режим не включаем
MCP_REGISTRY_ENABLE_REGISTRY_VALIDATION=true
MCP_REGISTRY_OIDC_ENABLED=true                             # админ/права публикации через наш Keycloak
MCP_REGISTRY_OIDC_ISSUER=https://auth.demo-ai-lab.ru/realms/dev
MCP_REGISTRY_OIDC_CLIENT_ID=mcp
MCP_REGISTRY_OIDC_EDIT_PERMISSIONS=*
MCP_REGISTRY_OIDC_PUBLISH_PERMISSIONS=*
# MCP_REGISTRY_SEED_FROM — не задаём: БД стартует пустой, публикуем только свои серверы
```

Секреты — вне git: `mcp-registry.local.md` (db-пароль, JWT seed) → `scripts/mcp_registry_secrets.sh` →
Secret `mcp-registry-db` + `mcp-registry`. Файл под `.gitignore: *.local.md`, `0600`.

## Публикация своих MCP-серверов

Верификация владения неймспейсом (факты из `docs/modelcontextprotocol-io/authentication.mdx`):
**GitHub**, **DNS** (TXT на apex домена) или **HTTP** (`/.well-known/mcp-registry-auth` на домене).
GitHub в закрытом демо не используем — берём доменную проверку `demo-ai-lab.ru`.

- **Имя сервера — строго reverse-DNS домена:** для `demo-ai-lab.ru` это `ru.demo-ai-lab/<server>`
  (правило реестра: `com.example.*/*` для `example.com`).
- **DNS-путь:** TXT-запись на **apex** `demo-ai-lab.ru` (не на селекторе вида `_mcp-auth.*`),
  значение `v=MCPv1; k=ed25519; p=<публичный ключ>`; старые записи при ротации ключа удалять —
  иначе проверка берёт устаревшую.
- **HTTP-путь:** файл `https://demo-ai-lab.ru/.well-known/mcp-registry-auth`.

```
mcp-publisher init                                    # server.json рядом с сервером
mcp-publisher login dns --domain demo-ai-lab.ru --private-key <ключ>
#   либо: mcp-publisher login http --domain demo-ai-lab.ru --private-key <ключ>
mcp-publisher publish --registry https://mcp.demo-ai-lab.ru
```

Каждый опубликованный сервер должен иметь `remotes` (`streamable-http`/`sse` + `url`) — именно этот URL
заводится маршрутом в Higress (`mcp-proxy`). Пакетные (`packages`, `stdio`) для нашей демонстрации
бесполезны: их нечем вызывать через шлюз.

## Приёмка (M1–M5)

- **M1** — поды Running, `GET https://mcp.demo-ai-lab.ru/health` → 200 из LAN и снаружи;
  `/docs` открывается; TLS — LE-серт в ns `mcp-registry`.
- **M2** — `psql` из пода реестра: схема создана миграциями, пустая таблица серверов.
- **M3** — публикация своего сервера (неймспейс `ru.demo-ai-lab`), `GET /v0/servers` его отдаёт.
- **M4** — в Higress маршрут с `mcp-server` (`mcp-proxy`) на `remotes`-URL из реестра: `tools/list`
  от клиента (qm/Hermes) приходит, `allowTools` работает.
- **M5** — админ-доступ: OIDC-токен Keycloak (`realm dev`) принимается, публикация без токена — 401.

## Риски

| Риск | Что делаем |
|---|---|
| API v0.1 в заморозке, до GA возможны изменения/сбросы данных | каталог не источник истины: `server.json` каждого сервера лежит в git рядом с его кодом; в реестре — только опубликованная копия |
| PostgreSQL ×1 — SPOF | принято для демо; бэкап `pg_dump` вне репо перед показом |
| Публикация без GitHub — через домен | DNS TXT/HTTP-файл держим в Cloudflare/MikroTik; при смене домена публикация ломается |
| Реестр не проксирует вызовы | вызовы — только через Higress (`mcp-proxy`), это зафиксировано в ADR-0005 |
| Лишний вес для демо | реестр лёгкий (Go, 8Gi PVC); если на сцене не нужен — Argo `Application` отключается одной правкой |

## Что дальше (не сделано)

1. Манифесты `gitops/infra-apps/mcp-registry/` (Deployment, PG StatefulSet, Service, Ingress,
   Certificate, sync-waves) — по образцу `keycloak/`.
2. `scripts/mcp_registry_secrets.sh` + `mcp-registry.local.md` (генерация пароля БД и JWT seed).
3. Прогон M1–M3 до первой публикации; M4 — вместе с включением MCP на Higress (Redis не нужен, если
   сразу streamable HTTP).
