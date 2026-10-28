# MCP Registry — каталог MCP-серверов (`mcp.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/mcp-registry-spec.md` (фазы M1–M8). Раскатывает ApplicationSet `infra-apps`
в ns `mcp-registry` (имя ns = имя каталога) как plain-манифесты, как `infra-apps/keycloak/`.

Каталог **не проксирует** вызовы инструментов: он отдаёт метаданные (`/v0`, витрина на `/`),
сами вызовы идут через Higress (`mcp-server`/`mcp-proxy`, ADR-0005).

| Файл | Sync-wave | Что |
|---|---|---|
| `10-postgres.yaml` | -1 | Service ClusterIP `postgres` + StatefulSet (PG 16-alpine, PVC 8Gi `longhorn`, `PGDATA` подкаталог) |
| `20-registry.yaml` | 0 | Service :8080 + Deployment `registry` (`modelcontextprotocol/registry` 1.8.6) |
| `30-ingress.yaml` | 0 | `Certificate mcp-demo-tls` + `Ingress mcp` → `registry:8080` |

## Деплой (M1 → M2)

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf           # или --context demo-ai-lab
./scripts/mcp_registry_secrets.sh --init             # один раз: mcp-registry.local.md (0600, gitignored)
./scripts/mcp_registry_secrets.sh                    # Secret'ы mcp-registry-db / mcp-registry ДО синка
git add gitops/infra-apps/mcp-registry && git commit -m "feat(gitops/mcp): каталог MCP-серверов" && git push
kubectl -n argocd get application mcp-registry -o jsonpath='{.status.sync.status} {.status.health.status}\n'
kubectl -n mcp-registry get pods,pvc,certificate
```

Ожидаемо: `Synced Healthy`, PVC `Bound`, `Certificate mcp-demo-tls` → `Ready`, 2/2 пода `Running`.

Смоук (M2/M4):

```bash
curl -s --resolve mcp.demo-ai-lab.ru:443:192.168.10.230 https://mcp.demo-ai-lab.ru/v0/health
curl -s https://mcp.demo-ai-lab.ru/v0/version                     # {"version":"1.8.6",...}
curl -s --resolve mcp.demo-ai-lab.ru:443:192.168.10.230 https://mcp.demo-ai-lab.ru/ | grep -o '<title>[^<]*'
```

Ожидаемо: `{"status":"ok"}`, версия `1.8.6`, HTML витрины со списком «Recently Updated»
(пустой, пока в каталог ничего не опубликовано — это норма, не поломка).

## Решения, важные для работоспособности

- **Secret'ы до первого синка.** Argo не создаёт и не удаляет Secret'ы: без них под висит в
  `CreateContainerConfigError` — симптом читается как «реестр не стартует», а не «сломан Argo».
- **`jwt-private-key` — hex-seed Ed25519** (`openssl rand -hex 32`), не PEM. С PEM реестр падает
  на подписи JWT. Скрипт отвергает PEM-значение по содержимому.
- **`PGDATA=/var/lib/postgresql/data/pgdata`** — в корне тома Longhorn лежит `lost+found`,
  `initdb` на непустом каталоге падает (грабля K2).
- **Service PG — ClusterIP, не headless**: headless-DNS появляется только с готовым подом,
  на первом синке реестр ловит «no such host».
- **Пробы только `httpGet`**: образ реестра — Chainguard static (uid 65532, без shell и пакетов).
  Health живёт **под префиксом** `/v0/health`; на `/` — витрина, её пробой не проверяем.
- **`Recreate`, не RollingUpdate**: миграции БД применяет сам реестр на старте, две реплики
  запустили бы их одновременно.
- **`demo-stand-critical` не пересоздаём**: PriorityClass кластерный и уже создан каталогом
  `keycloak`; второй экземпляр дал бы конфликт Argo.
- **`MCP_REGISTRY_SEED_FROM` не задаём**: каталог стартует пустым — только серверы стенда,
  зеркало официального реестра не нужно.

## Публикация сервера (M5)

Неймспейс серверов — reverse-DNS домена стенда: `ru.demo-ai-lab/<server>`. Владение доменом
доказывается apex-TXT (`v=MCPv1; k=ed25519; p=<pub>`), логин — `mcp-publisher login dns`, публикация —
`mcp-publisher publish --registry https://mcp.demo-ai-lab.ru`. Первый сервер каталога — нативный
MCP Docling (`doc.demo-ai-lab.ru/mcp`, развёрнут 2026-10-28). Детали и грабли — спека §5.

`server.json` — `gitops/mcp-servers/<svc>/server.json` (первый: `mcp-servers/docling/`): каталог — копия,
источник истины — git (R-M1: API v0.1 в заморозке). Внутрь `gitops/apps/<svc>/` не кладём — Argo читает все
файлы каталога приложения и падает на JSON без `kind`.

Приватный Ed25519-ключ — `mcp-publisher.local.pem` в корне репо (`.gitignore`: `*.local.pem`), seed для
`login dns` берётся из него: `openssl pkey -in mcp-publisher.local.pem -outform DER | tail -c 32 | xxd -p -c 64`.

Публикация проверена 2026-10-28: `ru.demo-ai-lab/docling@1.0.0` (apex-TXT `v=MCPv1; …` в Cloudflare).
Грабли публикации: `description` ≤ 100 символов (иначе 422); `mcp-publisher validate` валидирует против
**публичного** реестра, а не нашего; `mcp-publisher publish` берёт реестр из сессии `login --registry`.

## Блокеры и ограничения

- **M-O1 — клиент Keycloak `mcp`.** Нужен **публичный** клиент, выдающий `id_token` (`aud=mcp`):
  сейчас в `scripts/keycloak_seed.py`/`keycloak-spec.md` §5.3 он confidential + service account.
  До правки сида M6 (обмен `/v0/auth/oidc`) не принимается; чтение каталога и витрина от этого
  не зависят.
- **allowlist Cloudflare (2026-10-28)** делает «публичный» хост публичным только для ISP-egress
  владельца (R-M7) — гостям со сцены нужен доступ из LAN.
- **Витрина** показывает только обновлённые за последний час → перед показом сервер
  переопубликовать с новой версией; повторная публикация того же `name`+`version` отклоняется.
- **`/metrics`** открыт на том же хосте (R-M5): при выходе за allowlist — закрывать путём в Higress.

## Откат

```bash
kubectl -n argocd patch application mcp-registry --type merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'     # снять selfHeal
kubectl -n mcp-registry delete deploy registry        # каталог не источник истины
kubectl -n mcp-registry delete sts postgres           # + PVC data-postgres-0 (данные каталога)
```

Бэкап перед показом и апгрейдом: `pg_dump -Fc` вне репо (спека §7).
