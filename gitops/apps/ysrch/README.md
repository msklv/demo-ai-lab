# Yandex Search MCP server (`ysrch.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/ysearch-spec.md` (фазы Y1–Y5). Раскатывает ApplicationSet `apps` в ns `ysrch`
(имя ns = имя каталога) как plain-манифесты.

Источник образа — форк `github.com/msklv/yandex-search-mcp-server` (HTTP-транспорт поверх официального
`yandex/yandex-search-mcp-server`, все типы поиска, дефолт `ru`). Сервис — **MCP-эндпоинт** `/mcp`,
отдельного UI нет.

| Файл | Sync-wave | Что |
|---|---|---|
| `05-entrypoint-configmap.yaml` | — | обёртка запуска: снимает DNS-rebinding-проверку Host (иначе `421 Invalid Host header` за Higress) |
| `10-deployment.yaml` | — | Deployment `yandex-search` (образ `v1.3.1` по digest, порт 8766, TCP-пробы) |
| `20-service.yaml` | — | ClusterIP `yandex-search`:8766 |
| `30-ingress.yaml` | — | `Certificate ysrch-demo-tls` + `Ingress ysrch` → `yandex-search:8766` |

## Деплой (Y1 → Y2)

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
./scripts/yandex_search_secrets.sh --init        # один раз: yandex-search.local.md (0600, gitignored)
$EDITOR yandex-search.local.md                   # api-key из консоли Yandex AI Studio (Search API v2)
./scripts/yandex_search_secrets.sh               # Secret yandex-search ДО синка
kubectl -n ysrch apply -f gitops/apps/ysrch/     # или git push — Argo создаст Application `ysrch`
```

Смоук (MCP-рукопожатие + живой вызов):

```bash
curl --resolve ysrch.demo-ai-lab.ru:443:192.168.10.230 -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://ysrch.demo-ai-lab.ru/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
# ожидаемо 200 + Mcp-Session-Id в заголовках; GET /mcp отдаёт 406 by design
```

## Решения, важные для работоспособности

- **421 `Invalid Host header`.** `server.py` создаёт `FastMCP` с `host=127.0.0.1`, и SDK `mcp` 1.29.1
  включает DNS-rebinding-защиту с `allowed_hosts` только для localhost. Запрос через Higress с
  `Host: ysrch.demo-ai-lab.ru` режется. `run_http.py` образа меняет только host/port, транспортную
  безопасность — нет. Поэтому запуск переопределён ConfigMap'ом (`transport_security = None`):
  периметр — Higress + TLS, порт наружу не выставлен. Правильное место правки — форк
  (`run_http.py`), до его релиза обёртка живёт здесь.
- **Пробы только TCP.** На `GET /mcp` сервер отвечает `406` (streamable-http), поэтому httpGet-проба
  не годится; `tcpSocket` на 8766 — то же, что HEALTHCHECK в образе.
- **Ключ не в git.** `SEARCH_API_KEY` и `FOLDER_ID` — из Secret `yandex-search`; создаёт
  `scripts/yandex_search_secrets.sh` из `yandex-search.local.md`. `FOLDER_ID` нужен только
  `gen_search`; без него сервис стартует, а `gen_search` отвечает ошибкой.
- **Egress наружу обязателен:** под ходит в `searchapi.api.cloud.yandex.net` и
  `operation.api.cloud.yandex.net`. На стенде проверено 2026-10-28: `web_search` и `gen_search`
  отвечают из кластера и через edge.
- **Root-ФС не readonly**: образ на `python:3.10-slim`, python пишет `__pycache__` в `/app`.
- **ResourceClass/приоритет:** `demo-stand-critical`, soft-affinity на пару k8s-02/03.

## Каталог MCP

Манифест публикации — `gitops/mcp-servers/yandex-search/server.json`:

```bash
SEED=$(openssl pkey -in mcp-publisher.local.pem -outform DER | tail -c 32 | xxd -p -c 64)
mcp-publisher login dns --domain demo-ai-lab.ru --private-key "$SEED" --registry https://mcp.demo-ai-lab.ru
mcp-publisher publish gitops/mcp-servers/yandex-search/server.json
```

`ru.demo-ai-lab/yandex-search@1.0.0`, `remotes[0].url = https://ysrch.demo-ai-lab.ru/mcp` —
опубликован 2026-10-28. При изменении инструментов/версии образа — поднять `version` в `server.json`
и переопубликовать (повтор того же `name`+`version` реестр отклоняет; витрина показывает обновлённое
за час).
