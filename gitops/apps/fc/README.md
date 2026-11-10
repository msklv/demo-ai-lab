# Firecrawl self-host (`fc`) — извлечение веб-страниц для агентов стенда

Спека: `architecture/specs/firecrawl-spec.md` (фазы C1–C6). Каталог раскатывает ApplicationSet `apps`
в ns `fc` (имя ns = имя каталога) как plain-манифесты.

Состав — 5 подов: `firecrawl-api` (3002), `playwright-service` (3000), `rabbitmq` (5672),
`redis` (6379), `nuq-postgres` (5432, StatefulSet). Внешнего имени нет: только `ClusterIP`
(`firecrawl-api.fc.svc.cluster.local:3002`) — у self-host нет аутентификации.

| Файл | Что |
|---|---|
| `10-nuq-postgres.yaml` | StatefulSet `nuq-postgres` + Service, PVC 5Gi Longhorn |
| `15-redis-rabbit.yaml` | Deployment `redis` (emptyDir) + `rabbitmq` (PVC 2Gi) + 2 Service |
| `20-playwright.yaml` | Deployment `playwright-service` (Chromium, `/health`) + Service |
| `25-api.yaml` | Deployment `firecrawl-api` + Service |

## Размещение — k8s-05 (отличие от спеки)

Спека v1.0 ставила стек `preferred`-ом на пару k8s-02/03 (`demo-ai-lab/role=ingress`). Здесь — **все
пять подов закреплены `required`-ом на `k8s-05`** (решение владельца 2026-11-10: Chromium-стек тяжёлый
по памяти, на 05 свободно 32 Gi и она не несёт инференс/шлюз). Отсюда два следствия:

- потеря k8s-05 = `Pending` у всего стека (в спеке hard-pin отвергался именно за это — осознанный
  размен на предсказуемое размещение);
- `podAntiAffinity` api↔playwright из спеки **снят**: на одной ноде он не разводит поды, а на
  `preferred`-скоринге уводил `firecrawl-api` на k8s-04 (проверено — под сел на 04 рядом с GPUStack).

## Деплой

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
./scripts/firecrawl_secrets.sh --init   # один раз: firecrawl.local.md (0600, gitignored)
./scripts/firecrawl_secrets.sh          # Secret fc-secrets ДО первого синка (создаёт ns fc)
kubectl -n fc apply -f gitops/apps/fc/  # или git push — Argo создаст Application `fc`
```

Предтяжка образов (≈5 GB; на стенде ушло ~90 с) — одноразовые поды с `nodeSelector` на k8s-05,
приёмка — совпадение digest в `imageID`:

```bash
kubectl run prepull-api --image='ghcr.io/firecrawl/firecrawl:2.10.19-production@sha256:618504f7…' \
  --restart=Never --image-pull-policy=IfNotPresent --command -- /bin/sh -c true
```

## Как ходить (доступа снаружи нет)

Только из кластера или через port-forward — Ingress в v1 не заводится (фаза C6):

```bash
# из любого пода стенда
curl -s -X POST http://firecrawl-api.fc.svc.cluster.local:3002/v2/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","formats":["markdown"]}' | head -c 400

# с ноутбука в LAN — туннель на 127.0.0.1
kubectl --context demo-ai-lab -n fc port-forward svc/firecrawl-api 3002:3002
curl -s -X POST http://127.0.0.1:3002/v2/scrape \
  -H 'Content-Type: application/json' -d '{"url":"https://example.com","formats":["markdown"]}'
```

## Грабли, снятые установкой (10.11.2026)

- **api в `OOMKilled` при лимите 2Gi.** В одном контейнере живут 9 node-процессов (`api`, `worker`,
  `extract-worker`, 5 × `nuq-worker`, `prefetch`, `reconciler`); steady-state после нескольких scrape —
  **2.6 Gi**. Лимит поднят до **3Gi** (`requests` 500m/768Mi), спека правила «2Gi» — обновлена.
- **`nuq-postgres`: `command` вместо `args` ломает старт.** `command: ["postgres", "-c", …]` затирает
  `docker-entrypoint.sh` → `"root" execution of the PostgreSQL server is not permitted` (CrashLoop).
  Правильно — `args: ["-c", "cron.database_name=firecrawl"]`, точка входа образа сама сбрасывает
  привилегии через `gosu`.
- **`securityContext` с `drop: [ALL]`** на nuq-postgres/rabbitmq ломает их entrypoint (`chown
  /var/lib/rabbitmq: Operation not permitted`). У этих двух контейнеров ограничение снято, seccomp
  `RuntimeDefault` на уровне пода оставлен.
- **Guard приватных адресов отвечает иначе, чем на Mac-эталоне:** вместо `pageStatusCode: 403` при
  HTTP 200 — `500 SCRAPE_ALL_ENGINES_FAILED` (`engines tried: [pdf, document]`), в логах api —
  `Connection violated security rules` (`safeFetch.js`). Страница не отдаётся — цель достигнута,
  но проверку в C5 писать по коду 500, а не по `pageStatusCode`.
- `RABBITMQ_NODENAME=rabbit@localhost` — имя узла Mnesia стабильно между пересозданиями пода
  (у Deployment hostname меняется); `rabbitmq-diagnostics ping` из `exec` при этом работает.

## Факт приёмки 10.11.2026

C1 — 5/5 образов по тем же digest (предтяжка ~90 с). C2 — Secret `fc-secrets`, 4 ключа. C3 —
`pg_isready` accepting, `rabbitmq-diagnostics ping` ok, `redis-cli ping` → `PONG`, PVC
`data-nuq-postgres-0`/`rabbitmq-data` Bound. C4 — `POST /v2/scrape` example.com → `success:true`,
markdown 958 симв.; SPA `quasar.dev` 6,9 КБ; ru-wiki «Москва» 632 КБ кириллицей. C5 — 5 параллельных
scrape 5/5 (0,6–2,5 с), `activePages` вернулся в 0; guard на `192.168.10.230` и на
`firecrawl-api.fc.svc.cluster.local` — отказ без содержимого. Память простоя: api 2.6 Gi,
playwright 233 Mi, rabbitmq 142 Mi, pg 92 Mi, redis 5 Mi.
