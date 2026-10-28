# MCP Registry — каталог MCP-серверов стенда (`mcp.demo-ai-lab.ru`)

> **Версия:** v2.0 (2026-10-28) · **Статус:** **спека, не установлено** — ns `mcp-registry` в кластере
> отсутствует; пины, env и API ниже сверены с исходниками `registry` **v1.8.6** (2026-10-28), предпосылки
> сняты замером того же дня.
> **Цель:** шаг 3 демо — **каталог (витрина) MCP-серверов** стенда: клиенты и агенты получают список
> серверов по API `/v0`, человек видит его в веб-витрине на `/`. **Вызовы инструментов реестр не
> проксирует** — они идут через Higress (`mcp-server`/`mcp-proxy`, ADR-0005).
> **Внешнее имя:** `mcp.demo-ai-lab.ru` (LAN — split-DNS на `.230`, снаружи — Cloudflare Tunnel).
> **Механизм развёртывания:** Argo CD, каталог `gitops/infra-apps/mcp-registry/` (plain-манифесты, как
> `keycloak/`); Secret'ы создаются **до** первого синка и в git не попадают.

Стиль-образцы: `architecture/k8s-install-spec.md` (F\*), `external-access-spec.md` (E\*),
`keycloak-spec.md` (K\*), `gpustack-spec.md` (G\*), `doc-spec.md` (D\*). Эта спека занимает букву **M**.

## 0. Что уточнила сверка с исходниками (v1.0 → v2.0)

| Что | v1.0 (2026-10-24) | v2.0 — факт (2026-10-28) |
|---|---|---|
| Версия | пин по digest, версию не называл | релиз **v1.8.6** (образ собран 2026-10-26, GitHub release 2026-10-27); тег образа — `1.8.6` **без префикса `v`** (теги `vX.Y.Z` в ghcr отсутствуют) |
| Веб-витрина | «веб-UI нет, только `/v0` и `/docs`» | **есть встроенная страница на `/`**: «Recently Updated», поиск по имени, переключатель base-URL (`internal/api/handlers/v0/ui_index.html`) |
| Health | `GET /health` → 200 на корне | health/ping/version живут **только под префиксом**: `/v0/health`, `/v0/ping`, `/v0/version` (+ алиас `/v0.1/*`); на корне `/` — витрина, `/metrics` — Prometheus, `/docs` — OpenAPI |
| OIDC-админ | «IdP-токен принимается» | обмен `POST /v0/auth/oidc {oidc_token}` — это **ID-token с `aud` = `MCP_REGISTRY_OIDC_CLIENT_ID`** (go-oidc verifier); клиент Keycloak должен быть **публичным**, client-credentials из сида (§5.3 `keycloak-spec.md`) здесь не работают — M-O1 |
| JWT-ключ | «32-байтный seed, hex» | подтверждено `.env.example`: `openssl rand -hex 32`, **seed Ed25519, не полный ключ** |
| Миграции БД | не описано | миграции зашиты в бинарь и **применяются на старте** (`internal/database/postgres.go`); коннект к PG — с bounded retry (`cmd/registry/main.go`) |
| Образ | не разобран | база **Chainguard static**: нет shell, нет пакетов, non-root → **все пробы только `httpGet`** |
| Приёмка | M1–M5 | M1–M8 (добавлены витрина, OIDC-обмен, отказ/восстановление) |
| Edge | «чтение публично» | с 2026-10-28 в зоне действует allowlist Cloudflare (только ISP-egress владельца) → «публично» сейчас = «публично для владельца» |

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ реестра | `ghcr.io/modelcontextprotocol/registry:1.8.6` — индекс `sha256:f116000c08b41a477c8c7d90ea3fc7003ff4afb65cfb60cc9ebd82a85096fea3`, amd64-манифест `sha256:0901dac00df92ce2f96a6ef0e6f9cf52319f3d6eae7999121d68cd8059d395ed`, pull **7,7 MiB** (3 слоя) | `crane digest` / `crane manifest --platform linux/amd64`, 2026-10-28; Go-бинарь, качать почти нечего |
| PostgreSQL | `postgres:16-alpine` — индекс `sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`, amd64 `sha256:cbf42f0edc946c0bc1b8eeed62403734e1f25dc67a3491455d07a92fdb558b28`, pull **110,7 MiB** | версия из upstream `docker-compose.yml`; digest — замер 2026-10-28 |
| Namespace | `mcp-registry` (создаёт ApplicationSet `infra-apps` по имени каталога) | один ns на сервис, TLS-секрет в своём ns |
| Состав | Deployment ×1 (реестр) + StatefulSet ×1 (PG) + 2 Service + Ingress + Certificate | реестр stateless; состояние — только в PG |
| Реплики | реестр **1**, PG **1** | витрине хватает; PG — SPOF, принят (R-M2), как у Keycloak |
| Размещение | `nodeAffinity.preferred` `demo-ai-lab/role in [ingress]` (k8s-02/03) | k8s-04 занят инференсом (GPUStack), k8s-01 — резерв; hard-pin даёт `Pending` при потере узла |
| Ресурсы | реестр: requests `50m/64Mi`, limits `500m/256Mi`; PG: requests `100m/256Mi`, limits `1/768Mi` | Go-бинарь; цифры уточняются замером `kubectl top` в M3 |
| PriorityClass | `demo-stand-critical` (уже создан каталогом `infra-apps/keycloak`) | **не пересоздавать** — объект кластерный, второй экземпляр в другом каталоге даст конфликт Argo |
| Хранилище | PVC **8 Gi** `longhorn` (r=2) для PG, `PGDATA=/var/lib/postgresql/data/pgdata` | подкаталог обязателен: в корне тома Longhorn лежит `lost+found` → `initdb` падает (грабля K2) |
| Сервис PG | **ClusterIP, не headless** | headless-DNS появляется только с готовым подом → на первом синке реестр ловит «no such host» (грабля K2) |
| TLS | `Certificate mcp-demo-tls` (ClusterIssuer `letsencrypt-wildcard`) в ns `mcp-registry` | правило E-серии: серт живёт в ns Ingress'а, wildcard-секрет из `demo-test` не переиспользуется |
| Ingress | один `Ingress` класс `higress`, host `mcp.demo-ai-lab.ru`, path `/` → сервис реестра:8080 | витрина, `/v0*`, `/docs`, `/metrics` — с одного порта |
| Публичность | **весь хост** (чтение каталога без авторизации); запись — по токену | ADR-0005 схема 2; действующий edge-allowlist (§0) делает это «публичным для владельца» |
| Авторизация админа | OIDC Keycloak (`MCP_REGISTRY_OIDC_*`), клиент — **публичный** | `MCP_REGISTRY_OIDC_*` закрывают только права публикации/правки; владение неймспейсом — DNS (ADR-0005 §4) |
| GitHub OAuth | **не включаем** (`MCP_REGISTRY_GITHUB_CLIENT_ID/SECRET` пустые) | закрытый стенд, публикация через доменную проверку; `/v0/health` тогда отдаёт пустой `github_client_id` |
| Seed | `MCP_REGISTRY_SEED_FROM` **не задаём** | БД стартует пустой: каталог = только наши серверы (зеркало официального реестра не нужно) |
| Валидация | `MCP_REGISTRY_ENABLE_REGISTRY_VALIDATION=true` | `server.json` проверяется по схеме при публикации |
| Секреты | Secret `mcp-registry-db` (`db-name`,`db-username`,`db-password`,`url`) + `mcp-registry` (`jwt-private-key`) | в git только ссылки; создаёт `scripts/mcp_registry_secrets.sh` |
| Деплой | Argo CD (`gitops/infra-apps/mcp-registry/`), sync-waves `-1` (PG) → `0` (реестр, Ingress, Certificate) | паттерн `keycloak/`; Argo не создаёт и не удаляет Secret'ы |

## 2. Предпосылки — проверено 2026-10-28

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass; kubectl get priorityclass
kubectl get nodes -L demo-ai-lab/role
kubectl top nodes; kubectl get certificate -A
kubectl get ns | grep -c mcp-registry           # 0 — ns отсутствует
dig +short @192.168.10.1 mcp.demo-ai-lab.ru     # LAN → 192.168.10.230
dig +short @1.1.1.1 mcp.demo-ai-lab.ru          # снаружи → anycast Cloudflare
crane digest ghcr.io/modelcontextprotocol/registry:1.8.6
crane digest --platform linux/amd64 ghcr.io/modelcontextprotocol/registry:1.8.6
crane digest docker.io/library/postgres:16-alpine
curl -fsSL https://github.com/modelcontextprotocol/registry/archive/refs/tags/v1.8.6.tar.gz | tar tz | head
```

| Факт | Значение (замер) |
|---|---|
| StorageClass / Ingress | `longhorn` default (r=2), `longhorn-static`; `higress`, VIP `192.168.10.230` (`externalTrafficPolicy: Local`) |
| Ноды (allocatable) | 01 — 32 GiB RAM / 16 CPU, 02 — 15,5 GiB / 12, 03 — 15,5 GiB / 12, 04 — 29,5 GiB / 16; taints нет |
| Занято (`top nodes`) | 01 — 5620 Mi, 02 — 6478 Mi, 03 — 9505 Mi, 04 — 11 539 Mi |
| Свободная RAM на диске (02/03) | `free -g`: 02 — 14 total / **9 avail**, 03 — 14 total / **6 avail**; `df -h /`: 02 — 67 G, 03 — 53 G свободно |
| Longhorn | allocatable: 02 — 242,8 GiB, 03 — 241,9 GiB, 04 — 242,5 GiB, 01 — 68,7 GiB (вне пула по ADR-0003) |
| Метки размещения | `demo-ai-lab/role=ingress` — только 02 и 03; `feature.gpustack.ai/acceleratable=true` — только 04 |
| PriorityClass | `demo-stand-critical` (100000) — существует с K2, создаётся каталогом `keycloak` |
| TLS | ClusterIssuer `letsencrypt-wildcard`; 8 LE-сертов (6 `*-demo-tls`, `demo-wildcard`, `gpustack-tls`) — все `Ready`; плюс 4 self-signed (operator/kueue) |
| Namespace | `mcp-registry` **отсутствует** (есть: argocd, cert-manager, cilium-secrets, default, demo-test, doc, gpustack, higress-system, infra, keycloak, owu, spk, longhorn-system, node-feature-discovery, kube-*) |
| DNS | `*.demo-ai-lab.ru` уже покрыт: CF proxied CNAME на туннель + regexp-wildcard в split-DNS MikroTik → `.230`; отдельная запись не нужна |
| Образ реестра | 1.8.6: индекс `f11600…`, amd64 `0901da…`, 3 слоя / 7,7 MiB, база Chainguard static (uid `65532`, без shell) |
| Образ PG | 16-alpine: индекс `0cefaab…`, amd64 `cbf42f0…`, 110,7 MiB |
| API v1.8.6 | `GET /v0/{health,ping,version,servers}`, `GET /v0/servers/{name}/versions[/{version}]`, `POST /v0/{publish,validate}`, `PUT /v0/servers/{name}/versions/{version}` (edit), `PATCH /v0/servers/{name}[/versions/{version}]/status`; `POST /v0/auth/{dns,http,oidc,github-at,github-oidc,none}`; алиас `/v0.1/*`; `/docs`, `/metrics`, `/` (витрина) |
| Параметры списка | `cursor`, `limit` (1–100, дефолт 30), `updated_since` (RFC3339), `search` (≥3 символа после trim), `version`, `include_deleted` |
| Витрина | `/` тянет `${base}/v0.1/servers?updated_since=<час назад>&limit=96`, поиск по имени, base-URL в `localStorage`; CSS — `cdn.tailwindcss.com` (внешний CDN) |

## 3. Секреты

| Приватный файл (вне git, `0600`) | Что внутри | Кто читает |
|---|---|---|
| `mcp-registry.local.md` | `db-password`, `db-username`, `db-name`, `jwt-private-key` (hex, 32 байта) | `scripts/mcp_registry_secrets.sh` |

- `.gitignore`: широкое правило `*.local.md` уже покрывает файл; приёмка — `git check-ignore -v mcp-registry.local.md`.
- `scripts/mcp_registry_secrets.sh` (значения не печатает) создаёт `Secret mcp-registry-db`
  (`db-name=mcp-registry`, `db-username=mcpregistry`, `db-password`, `url` =
  `postgres://<user>:<pw>@postgres.mcp-registry.svc:5432/mcp-registry?sslmode=disable`) и
  `Secret mcp-registry` (`jwt-private-key`).
- Генерация seed — `openssl rand -hex 32`; это **seed Ed25519, а не PEM-ключ** (иначе реестр падает на подписи JWT).
- Ротация `jwt-private-key` инвалидирует выданные publisher'ам токены (данные каталога целы) — делать до показа, не в его середине.
- Гигиена: скрипт идемпотентен, печатает только имена ключей; значения не попадают ни в логи Argo, ни в `kubectl describe`.

## 4. Развёртывание (`gitops/infra-apps/mcp-registry/`)

| Файл | Содержимое | sync-wave |
|---|---|---|
| `10-postgres.yaml` | Service ClusterIP `postgres` + StatefulSet (PG 16-alpine, PVC 8Gi, `PGDATA` подкаталог, `POSTGRES_INITDB_ARGS=--data-checksums`, exec-пробы `pg_isready` — shell в образе есть) | `-1` |
| `20-registry.yaml` | Deployment `registry` + Service :8080 | `0` |
| `30-ingress.yaml` | `Certificate mcp-demo-tls` + `Ingress mcp` (`mcp.demo-ai-lab.ru` → `registry:8080`) | `0` |

Ключевые фрагменты (полные манифесты — в gitops, здесь — решения):

```yaml
# 20-registry.yaml — существенное
spec:
  replicas: 1
  strategy: {type: Recreate}          # без двух подов и параллельных миграций при рестарте
  template:
    spec:
      priorityClassName: demo-stand-critical
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - {key: demo-ai-lab/role, operator: In, values: [ingress]}
      securityContext: {runAsNonRoot: true, runAsUser: 65532, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: registry
          image: ghcr.io/modelcontextprotocol/registry:1.8.6@sha256:f116000c08b41a477c8c7d90ea3fc7003ff4afb65cfb60cc9ebd82a85096fea3
          ports: [{name: http, containerPort: 8080}]
          securityContext: {readOnlyRootFilesystem: true, allowPrivilegeEscalation: false,
                            capabilities: {drop: [ALL]}}
          env:
            - {name: MCP_REGISTRY_SERVER_ADDRESS, value: ":8080"}
            - {name: MCP_REGISTRY_VERSION, value: "1.8.6"}
            - name: MCP_REGISTRY_DATABASE_URL
              valueFrom: {secretKeyRef: {name: mcp-registry-db, key: url}}
            - name: MCP_REGISTRY_JWT_PRIVATE_KEY
              valueFrom: {secretKeyRef: {name: mcp-registry, key: jwt-private-key}}
            - {name: MCP_REGISTRY_ENABLE_ANONYMOUS_AUTH, value: "false"}
            - {name: MCP_REGISTRY_ENABLE_REGISTRY_VALIDATION, value: "true"}
            - {name: MCP_REGISTRY_OIDC_ENABLED, value: "true"}
            - {name: MCP_REGISTRY_OIDC_ISSUER, value: "https://auth.demo-ai-lab.ru/realms/dev"}
            - {name: MCP_REGISTRY_OIDC_CLIENT_ID, value: "mcp"}
            - {name: MCP_REGISTRY_OIDC_EDIT_PERMISSIONS, value: "*"}
            - {name: MCP_REGISTRY_OIDC_PUBLISH_PERMISSIONS, value: "*"}
          # shell в образе нет → только httpGet
          startupProbe:   {httpGet: {path: /v0/health, port: http}, periodSeconds: 3, failureThreshold: 30}
          readinessProbe: {httpGet: {path: /v0/health, port: http}, periodSeconds: 10}
          livenessProbe:  {httpGet: {path: /v0/health, port: http}, periodSeconds: 20, failureThreshold: 5}
          resources: {requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 500m, memory: 256Mi}}
```

- **Порядок и отказы.** Миграции выполняет сам реестр на старте, коннект к PG — с повторами, поэтому
  «PG поднялась чуть позже» первого синка не ломает. `Recreate` исключает две миграции одновременно.
- **PG в том же ns**, Service `postgres.mcp-registry.svc:5432`, `sslmode=disable` (трафик не покидает ns).
- **Secret'ы — до первого синка**, иначе под висит в `CreateContainerConfigError` (симптом «реестр не
  стартует», а не «сломан Argo»).
- **PriorityClass не дублировать**: `demo-stand-critical` уже создан каталогом `keycloak`.

## 5. Каталог: что публикуем и как

**Неймспейс серверов — строго reverse-DNS домена:** для `demo-ai-lab.ru` это **`ru.demo-ai-lab/<server>`**
(правило реестра: `com.example.*/*` для `example.com`). `io.github.*` не используем — стенд закрытый.

Владение доменом доказываем **DNS-записью на apex** (не на селекторе вида `_mcp-auth.*`):

```bash
# OpenSSL 3 обязателен: системный LibreSSL на macOS не умеет Ed25519 («Algorithm Ed25519 not found»)
OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
$OPENSSL genpkey -algorithm Ed25519 -out key.pem            # приватный ключ — вне git
PUB="$($OPENSSL pkey -in key.pem -pubout -outform DER | tail -c 32 | base64)"
echo "demo-ai-lab.ru. IN TXT \"v=MCPv1; k=ed25519; p=${PUB}\""
# TXT добавляется в apex зоны Cloudflare; при ротации ключа СТАРУЮ запись удалить —
# устаревшая проверяется первой и ломает логин
```

```bash
mcp-publisher init                     # генерирует server.json со свежей $schema — руками не писать
mcp-publisher login dns --domain demo-ai-lab.ru --private-key "<hex приватного ключа>"
mcp-publisher publish --registry https://mcp.demo-ai-lab.ru
```

`server.json` кладём **рядом с сервером в git** (каталог реестра — копия, не источник истины). Минимум полей:

```json
{
  "name": "ru.demo-ai-lab/docling",
  "description": "Docling: OCR и разбор документов (MCP на doc.demo-ai-lab.ru/mcp)",
  "version": "1.0.0",
  "remotes": [{"type": "streamable-http", "url": "https://doc.demo-ai-lab.ru/mcp"}]
}
```

- **Первый сервер каталога — нативный MCP Docling** (`doc.demo-ai-lab.ru/mcp`, развёрнут 2026-10-28):
  он уже отвечает на `initialize`, отдельного хоста не требует.
- Серверы, опубликованные только как `packages`/`stdio`, шлюзом не обслуживаются — в каталог идут
  только записи с `remotes` (`streamable-http`/`sse` + `url`): этот URL и заводится в Higress
  (`mcp-server` → `mcp-proxy`). REST→MCP для RAGFlow/Open WebUI и `allowTools` по личности — слой
  Higress шага 3 (ADR-0005), в эту спеку не входят.
- Повторная публикация того же `name`+`version` отклоняется — перед показом поднимать версию.

## 6. Фазы M1–M8 (каждая — приёмка командами)

### M1 — секреты и манифесты

```bash
bash scripts/mcp_registry_secrets.sh                     # Secret'ы в ns mcp-registry (ns создать заранее)
kubectl -n mcp-registry get secret mcp-registry-db mcp-registry
git add gitops/infra-apps/mcp-registry && git commit -m "feat(gitops/mcp): каталог MCP-серверов" && git push
kubectl -n argocd get application mcp-registry -o jsonpath='{.status.sync.status} {.status.health.status}'
```

Ожидаемо: `Synced Healthy`, `PersistentVolumeClaim` → `Bound`, `Certificate mcp-demo-tls` → `Ready`.

### M2 — поды и API

```bash
kubectl -n mcp-registry get pods -o wide
curl -s --resolve mcp.demo-ai-lab.ru:443:192.168.10.230 https://mcp.demo-ai-lab.ru/v0/health
curl -s https://mcp.demo-ai-lab.ru/v0/version            # {"version":"1.8.6",...}
curl -sI https://mcp.demo-ai-lab.ru/docs | head -1       # 200, OpenAPI UI
```

Ожидаемо: 2/2 пода `Running`; `/v0/health` → `{"status":"ok"}`; `/v0/version` = `1.8.6`; `/docs` → 200.

### M3 — БД, миграции, ресурсы

```bash
kubectl -n mcp-registry exec postgres-0 -- psql -U mcpregistry -d mcp-registry \
  -c '\dt' -c 'select count(*) from servers;' -c 'select count(*) from schema_migrations;'
kubectl -n mcp-registry top pods
```

Ожидаемо: таблица `servers` пустая, счётчик миграций > 0; `top` подтверждает (или правит) requests/limits из §1.

### M4 — витрина

```bash
curl -s --resolve mcp.demo-ai-lab.ru:443:192.168.10.230 https://mcp.demo-ai-lab.ru/ | grep -o '<title>[^<]*'
```

Ожидаемо: HTML витрины (заголовок `Official MCP Registry`), список «Recently Updated» пуст — каталог
ещё не наполнен. В браузере — `https://mcp.demo-ai-lab.ru/` из LAN (Chrome, hosts/split-DNS).

### M5 — публикация сервера (каталог не пустой)

```bash
dig +short TXT demo-ai-lab.ru                            # v=MCPv1; k=ed25519; p=…
curl -s https://mcp.demo-ai-lab.ru/v0/servers | python3 -m json.tool | head -30
curl -s 'https://mcp.demo-ai-lab.ru/v0/servers?search=docling'
```

Ожидаемо: `mcp-publisher publish` → `✓`; `GET /v0/servers` отдаёт `ru.demo-ai-lab/docling` с
`remotes[0].url`; поиск по `docling` находит; витрина показывает карточку.

### M6 — админ-OIDC Keycloak

```bash
# ID-token публичного клиента (direct grant) → обмен на JWT реестра
TOKEN=$(curl -s -d "client_id=mcp" -d "username=<admin-test>" -d "password=<…>" \
  -d "grant_type=password" -d "scope=openid" \
  https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/token \
  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id_token",""))')
curl -s -X POST https://mcp.demo-ai-lab.ru/v0/auth/oidc -H 'Content-Type: application/json' \
  -d "{\"oidc_token\":\"$TOKEN\"}"                        # → registry JWT (bearer)
curl -s -o /dev/null -w '%{http_code}\n' -X PUT \
  https://mcp.demo-ai-lab.ru/v0/servers/ru.demo-ai-lab%2Fdocling/versions/1.0.0 \
  -H 'Content-Type: application/json' -d '{}'             # без bearer → 401
```

Ожидаемо: обмен даёт JWT, запись с токеном проходит, без токена — 401. **Блокер, если клиент `mcp`
остался confidential-service-account из сида** (M-O1): `id_token` он не выдаёт.

### M7 — витрина «как на сцене»

```bash
# витрина по умолчанию показывает только обновлённые за последний час
curl -s "https://mcp.demo-ai-lab.ru/v0/servers?updated_since=$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)&limit=96"
```

Ожидаемо: перед показом сервер **переопубликован с новой версией** (иначе «Recently Updated» пуст — это
не поломка); поиск по имени работает всегда.

### M8 — отказ и восстановление

```bash
kubectl -n mcp-registry delete pod -l app=registry
kubectl -n mcp-registry delete pod postgres-0                     # StatefulSet пересоздаст
curl -s -o /dev/null -w '%{http_code}\n' https://mcp.demo-ai-lab.ru/v0/health
```

Ожидаемо: реестр поднимается за секунды (состояние в PG); потеря PG — реестр пережидает (bounded retry
+ миграции), поды возвращаются после переаттача тома Longhorn (**RTO 1–3 мин**, как у Keycloak).

## 7. Операции

| Задача | Как |
|---|---|
| Health-смоук | `/v0/health` из LAN (`--resolve …:192.168.10.230`) и через edge (`--resolve …:<anycast>`); `scripts/k8s_health.py` каталог не проверяет |
| Бэкап | `kubectl -n mcp-registry exec postgres-0 -- pg_dump -U mcpregistry -Fc mcp-registry > <вне-репо>/mcp-registry-<дата>.dump` — перед показом и перед апгрейдом |
| Восстановление | `scale deploy/registry --replicas=0`, `pg_restore -c`, вернуть реплики (Argo — `selfHeal`, временно снять automated) |
| Апгрейд | сменить тег+digest в `20-registry.yaml`, `kubectl -n argocd annotate app mcp-registry argocd.argoproj.io/refresh=hard`; миграции применит сам реестр; откат — предыдущий digest (перед апгрейдом бэкап) |
| Ротация JWT seed | обновить Secret `mcp-registry` → `rollout restart deploy/registry`; ранее выданные publisher-токены станут недействительны |
| Сброс каталога | `psql -c 'truncate servers cascade'` (таблицу `schema_migrations` не трогать) + переопубликовать `server.json` из git |
| Наблюдение | `/metrics` (Prometheus) — тянуть изнутри кластера через Service, не снаружи |

## 8. Риски

| Риск | Что делаем |
|---|---|
| **R-M1** API v0.1 в заморозке (с 2025-10-24), до GA возможны сбросы данных | каталог не источник истины: `server.json` каждого сервера — в git рядом с его кодом |
| **R-M2** PostgreSQL ×1 — SPOF | принято для демо; `pg_dump` вне репо перед показом; RTO 1–3 мин |
| **R-M3** витрина показывает только «updated_since = 1 час» | переопубликовать сервер (bump версии) за минуты до показа; поиск работает всегда |
| **R-M4** HTML витрины тянет Tailwind с `cdn.tailwindcss.com` | без интернета страница без стилей, данные и поиск живы; проверять на том же браузере, что и сцена |
| **R-M5** `/metrics` публичен на том же хосте | оставляем: edge закрыт allowlist'ом; при снятии allowlist'а — закрыть путь в Higress |
| **R-M6** доменная проверка зависит от apex-TXT | запись держим в Cloudflare; при ротации ключа старую запись удалять, иначе проверка берёт устаревшую |
| **R-M7** allowlist Cloudflare (2026-10-28) закрывает гостей | «публично» = «для ISP-egress владельца»; публичный показ требует решения по правилу, а не побочного эффекта |
| **R-M8** OIDC-обмен требует публичного клиента, а в сиде `mcp` — confidential с service account | M-O1: правка сида и `keycloak-spec.md` §5.3; до этого M6 красный |
| **R-M9** в образе нет shell/пакетов (Chainguard static) | пробы только `httpGet`; отладка — `kubectl debug`/debug-контейнер, сеть из ns — пробным подом `busybox` |
| **R-M10** реестр не проксирует вызовы | зафиксировано ADR-0005: вызовы — Higress (`mcp-server`/`mcp-proxy`), у реестра только метаданные |
| **R-M11** +1 БД и +1 сервис на паре 02/03 (6–9 GiB свободно) | PG 768Mi limit, реестр 256Mi; при нехватке RAM на 03 первым уходит RAGFlow-стек, не каталог |

## 9. Что забывают в таких спеках + открытые вопросы

| Пункт | Как закрыто здесь |
|---|---|
| Секреты до первого синка | M1 создаёт Secret'ы до коммита каталога |
| TLS в ns Ingress'а | `Certificate mcp-demo-tls` в `mcp-registry`, не wildcard из `demo-test` |
| Дубль кластерного объекта | `PriorityClass` берём существующий, свой не создаём |
| Headless Service у БД | ClusterIP (иначе «no such host» на первом синке) |
| `lost+found` на томе Longhorn | `PGDATA=/var/lib/postgresql/data/pgdata` |
| Пробы в образе без shell | только `httpGet` на `/v0/health` |
| Bootstrap-учётки | нет своего админа: доступ — OIDC Keycloak |
| NTP | расхождение часов ломает проверку `exp`/`iat` ID-token — NTP на узлах проверить перед M6 |
| Бэкап перед апгрейдом | `pg_dump` вне репо, восстановление описано (§7) |
| Лимиты LE | 50 сертов/нед: серт выпускается один раз, перевыпуск не в цикле |

**Открытые вопросы:**

1. **M-O1 — клиент Keycloak `mcp`.** Сейчас в `scripts/keycloak_seed.py` и `keycloak-spec.md` §5.3 он
   confidential + service account (client-credentials, standard flow off). Реестру нужен **публичный**
   клиент с выдачей `id_token` (`aud = mcp`). Правка сида — за владельцем; до неё M6 не принимается.
2. **M-O2 — публичность витрины.** Держим ли `mcp.*` в allowlist'е вместе со всем стендом (2026-10-28)
   или на время показа выносим его в открытый доступ (тогда `/metrics` закрывать отдельно, R-M5)?
3. **M-O3 — где живёт `server.json`.** Предложение — `gitops/apps/<svc>/mcp/server.json` рядом с
   манифестами публикуемого сервиса; владелец не подтверждал, решается при первой публикации.
4. **M-O4 — административные пути.** `/metrics` и операции edit/delete открыты на том же хосте; при
   выходе за пределы allowlist'а нужен путь-гейт в Higress (`oidc`/`ip-restriction`) — отдельная фаза.

## 10. Связанные документы и история версий

- `adr/adr-0005-mcp-registry-and-higress.md` — решение: реестр = каталог, Higress = вызовы; схемы 1/2 включены.
- `architecture/endpoints.md` — адрес `mcp.demo-ai-lab.ru` и правило коротких имён.
- `architecture/keycloak-spec.md` §5.3/§9 — клиент `mcp` (админ/права публикации) и SSO-периметр.
- `architecture/doc-spec.md` — первый сервер каталога (`doc.demo-ai-lab.ru/mcp`).
- `architecture/external-access-spec.md` §E7 — туннель и внешний путь.
- `gitops/README.md` — паттерн `infra-apps/<имя>` → Application + ns по имени каталога.

История версий:

- **v2.0** (2026-10-28): спека переписана по скелету `references/service-spec-authoring.md` и **сверена
  с исходниками v1.8.6** (тег `v1.8.6`: `internal/config`, `internal/api/router`, `handlers/v0`,
  `cmd/registry/main.go`, `.env.example`). Исправлено: версия и digest'ы (1.8.6, индекс `f11600…`),
  health только под `/v0`, встроенная витрина на `/` вместо «UI нет», OIDC = обмен ID-token (нужен
  публичный клиент), seed-JWT, авто-миграции и retry к PG, Chainguard static → только `httpGet`-пробы.
  Приёмка расширена до M1–M8 (витрина, OIDC-обмен, отказ/восстановление). Замер предпосылок 2026-10-28:
  ns отсутствует, RAM/диск 02/03, Longhorn, серты, digest'ы. Учтён edge-allowlist Cloudflare от 2026-10-28.
- **v1.0** (2026-10-24): первая версия — пины по digest, размещение на паре 02/03, env-набор, публикация
  через доменную проверку, приёмка M1–M5.
