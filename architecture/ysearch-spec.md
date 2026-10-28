# Yandex Search MCP (`ysrch.demo-ai-lab.ru`) — MCP-сервер веб-поиска

> **Версия:** v1.0 (2026-10-28) · **Статус:** **развёрнут и опубликован в каталоге 2026-10-28** (Argo CD,
> ns `ysrch`): под 1/1, `Certificate ysrch-demo-tls` Ready, MCP `initialize`/`tools/list`/`tools/call`
> через Higress из LAN и через edge — 200; `web_search` и `gen_search` отвечают живыми данными.
> **Цель:** шаг 2 демо — **инструмент веб-поиска для агентов** (Yandex Search API v2): агент ищет в
> интернете тем же MCP-протоколом, что и разбирает документы (Docling).
> **Внешнее имя:** `ysrch.demo-ai-lab.ru`, эндпоинт `/mcp`; LAN — split-DNS на `.230`, снаружи — туннель.
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/ysrch/` (plain-манифесты); Secret — до
> первого синка, в git не попадает.

Стиль-образцы: `k8s-install-spec.md` (F\*), `keycloak-spec.md` (K\*), `doc-spec.md` (D\*),
`mcp-registry-spec.md` (M\*). Эта спека занимает букву **Y**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Приложение | Форк `github.com/msklv/yandex-search-mcp-server` (Apache-2.0; форк официального `yandex/yandex-search-mcp-server`) | апстрим отдаёт только stdio; форк добавляет `run_http.py` (StreamableHTTP) и все типы поиска; не официальный продукт Yandex |
| Образ | `ghcr.io/msklv/yandex-search-mcp-server:v1.3.1` — индекс `sha256:6e0127cde129b0ab74a4b021fd566922222e6cce70a2e97a6febfa8c5dc6d98c`, amd64 `sha256:2d3e080ac80f106dfb3e52a0fc6ec6ba7d185019e9f8761cf29306cb0c8fbdf7`, 7 слоёв / **63,3 MiB**, база `python:3.10-slim` | `crane digest`/`crane manifest --platform linux/amd64`, 2026-10-28; CI форка публикует образ на каждый push в `main` и на теги `v*` |
| Namespace | `ysrch` (создаёт ApplicationSet `apps` по имени каталога) | один ns на сервис, TLS-секрет в своём ns |
| Состав | Deployment ×1 + Service + Ingress + Certificate + ConfigMap-обёртка запуска | сервис stateless, хранилища нет |
| Реплики | 1 | инструмент поиска, горизонтальное масштабирование не нужно |
| Размещение | `nodeAffinity.preferred` `demo-ai-lab/role in [ingress]` (k8s-02/03) | k8s-04 занят GPUStack; hard-pin даёт `Pending` при потере узла |
| Ресурсы | requests `100m/128Mi`, limits `500m/512Mi` | python+uvicorn+FastMCP; факт `top` — 5m/84Mi |
| PriorityClass | `demo-stand-critical` (объект уже создан каталогом `keycloak`, свой не дублируем) | Argo-конфликт на кластерном объекте |
| Порт / транспорт | `8766`, MCP StreamableHTTP на `/mcp` | `run_http.py`: `YANDEX_MCP_HOST/PORT`, дефолт `0.0.0.0:8766` |
| Пробы | только `tcpSocket: 8766` | `GET /mcp` отвечает **406 by design** (streamable-http) — httpGet-проба ложная; в образе тот же принцип (HEALTHCHECK через connect) |
| TLS | `Certificate ysrch-demo-tls` в ns `ysrch` | правило E-серии: серт живёт в ns Ingress'а |
| Ingress | `Ingress ysrch`, класс `higress`, host `ysrch.demo-ai-lab.ru`, `/` → `yandex-search:8766` | один порт на всё: `/mcp` и корень |
| Публичность | **весь хост, без авторизации** (как `doc.*`) | инструмент вызывает агент; наружу не отдаёт данные стенда, только результат поиска; решение 2026-10-28 |
| Креды | Secret `yandex-search`: `api-key` (Api-Key сервис-аккаунта Yandex Cloud), `folder-id` (нужен `gen_search`) | в манифестах только `secretKeyRef`; создаёт `scripts/yandex_search_secrets.sh` |
| Домен неймспейса в каталоге MCP | `ru.demo-ai-lab/yandex-search@1.0.0`, `remotes[0].url = https://ysrch.demo-ai-lab.ru/mcp` | `gitops/mcp-servers/yandex-search/server.json`; каталог — копия |

## 2. Предпосылки — проверено 2026-10-28

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
crane digest ghcr.io/msklv/yandex-search-mcp-server:v1.3.1
crane digest --platform linux/amd64 ghcr.io/msklv/yandex-search-mcp-server:v1.3.1
kubectl get ingressclass; kubectl get priorityclass demo-stand-critical
curl --resolve ysrch.demo-ai-lab.ru:443:192.168.10.230 -s -o /dev/null -w '%{http_code}\n' \
  https://ysrch.demo-ai-lab.ru/mcp
```

| Факт | Значение (замер) |
|---|---|
| Дигисты образа | индекс `6e0127…`, amd64 `2d3e08…`, 63,3 MiB, 7 слоёв |
| Сервер MCP | `serverInfo = Yandex Search Api v2 (all search types)`, версия SDK `1.29.1` |
| Инструменты (`tools/list`) | `web_search`, `web_search_async`, `get_operation`, `gen_search`, `image_search`, `image_search_by_image` |
| Живой вызов | `web_search {"query":"ГНИВЦ ФНС России","region":225}` → 694 симв. результатов (`gnivc.ru`, hh.ru); `gen_search` → 3453 симв. связного ответа |
| Маршрут | из LAN (`.230`, `--resolve`) и через edge (обычный DNS) — `initialize`/`tools/call` 200 |
| Egress из кластера | `searchapi.api.cloud.yandex.net`, `operation.api.cloud.yandex.net` доступны (вызовы проходят) |
| Грабля прокси | без обёртки: `POST /mcp` через Higress → **421 `Invalid Host header`** (SDK-защита Host) |

## 3. Секреты

| Приватный файл (вне git, `0600`) | Что внутри | Кто читает |
|---|---|---|
| `yandex-search.local.md` | `api-key` (Search API v2), `folder-id` | `scripts/yandex_search_secrets.sh` |

- `.gitignore`: широкое правило `*.local.md` уже покрывает; приёмка — `git check-ignore -v yandex-search.local.md`.
- `scripts/yandex_search_secrets.sh` (`--init` создаёт шаблон; значения не печатает) создаёт ns `ysrch`
  (если нет) и Secret `yandex-search` с ключами `api-key`, `folder-id`.
- Ключ **не генерируется**: Api-Key сервис-аккаунта выдаёт владелец в консоли Yandex AI Studio.
  `folder-id` пустой допустим — сервис стартует, `gen_search` отвечает ошибкой, `web_search` работает.
- Ротация: обновить `api-key` в файле → `./scripts/yandex_search_secrets.sh` → `rollout restart deploy/yandex-search`.

## 4. Развёртывание (`gitops/apps/ysrch/`)

| Файл | Содержимое |
|---|---|
| `05-entrypoint-configmap.yaml` | ConfigMap `yandex-search-entrypoint`: обёртка запуска (`transport_security = None`) |
| `10-deployment.yaml` | Deployment `yandex-search`: образ по digest, `command: python3 /opt/wrapper/run_http.py`, `PYTHONPATH=/app`, env из Secret, TCP-пробы, limits |
| `20-service.yaml` | ClusterIP `yandex-search`:8766 |
| `30-ingress.yaml` | `Certificate ysrch-demo-tls` + `Ingress ysrch` |

Ключевые фрагменты:

```yaml
# 10-deployment.yaml — существенное
spec:
  replicas: 1
  strategy: {type: Recreate}
  template:
    spec:
      priorityClassName: demo-stand-critical
      affinity: {nodeAffinity: {preferredDuringSchedulingIgnoredDuringExecution:
        [{weight: 100, preference: {matchExpressions:
          [{key: demo-ai-lab/role, operator: In, values: [ingress]}]}}]}}
      containers:
        - name: yandex-search
          image: ghcr.io/msklv/yandex-search-mcp-server:v1.3.1@sha256:6e0127…
          command: ["python3", "/opt/wrapper/run_http.py"]
          env:
            - {name: PYTHONPATH, value: /app}
            - name: SEARCH_API_KEY
              valueFrom: {secretKeyRef: {name: yandex-search, key: api-key}}
            - name: FOLDER_ID
              valueFrom: {secretKeyRef: {name: yandex-search, key: folder-id}}
          startupProbe:  {tcpSocket: {port: mcp}, periodSeconds: 3, failureThreshold: 20}
          readinessProbe: {tcpSocket: {port: mcp}, periodSeconds: 10}
```

```python
# 05-entrypoint-configmap.yaml — суть обёртки
from server import mcp
mcp.settings.host, mcp.settings.port = "0.0.0.0", 8766
mcp.settings.transport_security = None   # иначе SDK валидирует Host и режет запросы из-под Higress
mcp.run(transport="streamable-http")
```

- **Почему обёртка, а не `run_http.py` образа.** `server.py` создаёт `FastMCP(..., host=127.0.0.1)`,
  и SDK включает DNS-rebinding-защиту с `allowed_hosts=["127.0.0.1:*","localhost:*","[::1]:*"]`.
  `run_http.py` меняет только `settings.host/port`, из-за чего `Host: ysrch.demo-ai-lab.ru` режется
  (**421**). Правильное место правки — форк; до релиза форка обёртка живёт в нашем каталоге (Y-O1).
- **Root-ФС не readonly**: python пишет `__pycache__` в `/app`; образ под RO не рассчитан.
- **Секрет до синка**, иначе под висит в `CreateContainerConfigError` — читается как «сервис не стартует».

## 5. Инструменты и ограничения

| Инструмент | Что делает | Ограничение |
|---|---|---|
| `web_search` | веб-поиск (`query`, `search_region` ru/tr/com/kk/be/uz, `region` — id региона, дефолт 225) | работает без `FOLDER_ID` |
| `gen_search` | генеративный ответ по поиску | требует `FOLDER_ID` и доступ к `searchapi` |
| `image_search`, `image_search_by_image` | поиск по картинкам / по изображению | — |
| `web_search_async` + `get_operation` | асинхронный поиск и опрос операции | опрос идёт на `operation.api.cloud.yandex.net` (в форке v1.3.1 поправлено; host переопределяется `OPERATION_API_BASE`) |

- Лимиты и квоты — на стороне Yandex Cloud (сервис-аккаунт стенда); при исчерпании API возвращает
  ошибку в контент инструмента, MCP-сессия при этом жива.
- Кириллица — родная для API; `region: 213` (Москва), `2` (СПб) — для демонстрации локальности выдачи.

## 6. Фазы Y1–Y5 (каждая — приёмка командами)

### Y1 — секреты

```bash
./scripts/yandex_search_secrets.sh --init   # yandex-search.local.md (0600)
# заполнить api-key / folder-id
./scripts/yandex_search_secrets.sh
kubectl -n ysrch get secret yandex-search
```
Ожидаемо: Secret `yandex-search` с 2 ключами; значения в вывод не попадают.

### Y2 — деплой

```bash
kubectl -n ysrch apply -f gitops/apps/ysrch/       # либо git push → Application `ysrch`
kubectl -n ysrch get pods,certificate
```
Ожидаемо: под `1/1 Running`, `Certificate ysrch-demo-tls` → `Ready`.

### Y3 — MCP-рукопожатие через Higress

```bash
curl --resolve ysrch.demo-ai-lab.ru:443:192.168.10.230 -s -D- -o /dev/null \
  -X POST https://ysrch.demo-ai-lab.ru/mcp -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' | head -5
```
Ожидаемо: `200`, заголовок `Mcp-Session-Id`; без ConfigMap-обёртки — `421 Invalid Host header`.

### Y4 — живой поиск

```bash
# tools/call web_search с Mcp-Session-Id из Y3
```
Ожидаемо (2026-10-28): 694 симв. выдачи, первые результаты — `gnivc.ru`; `gen_search` — 3,4 КБ ответа.

### Y5 — публикация в каталоге MCP

```bash
SEED=$(openssl pkey -in mcp-publisher.local.pem -outform DER | tail -c 32 | xxd -p -c 64)
mcp-publisher login dns --domain demo-ai-lab.ru --private-key "$SEED" --registry https://mcp.demo-ai-lab.ru
mcp-publisher publish gitops/mcp-servers/yandex-search/server.json
curl --resolve mcp.demo-ai-lab.ru:443:192.168.10.230 -s 'https://mcp.demo-ai-lab.ru/v0/servers?search=yandex'
```
Ожидаемо: `✓ Server ru.demo-ai-lab/yandex-search version 1.0.0`; поиск в реестре находит запись с
`remotes[0].url = https://ysrch.demo-ai-lab.ru/mcp`.

## 7. Операции

| Задача | Как |
|---|---|
| Health | `tcpSocket` через readiness; снаружи — `curl` `initialize` (200 + `Mcp-Session-Id`); `scripts/k8s_health.py` под проверяет как обычный |
| Ротация ключа | правка `yandex-search.local.md` → скрипт → `rollout restart` |
| Апгрейд образа | сменить тег+digest в `10-deployment.yaml`, `git push`; при новых инструментах — поднять `version` в `server.json` и переопубликовать |
| Логи | `kubectl -n ysrch logs deploy/yandex-search` (uvicorn + FastMCP) |
| Бэкап | не требуется: состояния нет |

## 8. Риски

| Риск | Что делаем |
|---|---|
| **R-Y1** Форк, а не официальный продукт; апстрим может уйти вперёд | пины по digest; при расхождении — сверка `CHANGELOG.md` форка перед апгрейдом |
| **R-Y2** Зависимость от внешнего API (закрытый контур стенда) | `web_search`/`gen_search` требуют egress к `*.api.cloud.yandex.net`; при блокировке канала инструмент отвечает ошибкой, остальные сервисы стенда не затронуты |
| **R-Y3** 421 `Invalid Host header` при смене образа | обёртка в ConfigMap; при обновлении форка проверить, не появился ли `transport_security` в `run_http.py` — тогда обёртку снять |
| **R-Y4** Квоты/лимиты Search API | ключ сервис-аккаунта стенда; на сцене — 1–2 запроса, не цикл |
| **R-Y5** Публичный маршрут без авторизации | как у `doc.*`: наружу отдаётся только результат поиска; злоупотребление ограничено ключом и allowlist Cloudflare (R-M7) |
| **R-Y6** `GET /mcp` = 406 | не считать поломкой: это by design streamable-http; проба — TCP/`initialize` |

## 9. Что забывают в таких спеках + открытые вопросы

| Пункт | Как закрыто здесь |
|---|---|
| Проба на 406 | TCP-проба, а не httpGet |
| Host-валидация за прокси | ConfigMap-обёртка + Y3 в приёмке |
| Ключ внешнего API | Secret + скрипт, шаблон без значений |
| Разные типы инструментов в одном сервере | `gen_search` явно помечен как требующий `FOLDER_ID` |

**Открытые вопросы:**

1. **Y-O1 — `transport_security` в форке.** Перенести снятие Host-проверки в `run_http.py`
   `msklv/yandex-search-mcp-server` (или сделать настраиваемым через env `YANDEX_MCP_ALLOWED_HOSTS`) и
   выпустить `v1.3.2`; тогда ConfigMap-обёртка из этого каталога уходит.
2. **Y-O2 — SSO на маршруте.** Сейчас без авторизации (как `doc.*`). Если понадобится ограничить
   инструмент по личности — путь-гейт в Higress (`oidc`), но агентские вызовы тогда требуют токена.
3. **Y-O3 — кэш/лимит на стороне шлюза.** При частых вызовах имеет смысл квота в Higress, а не в сервисе.

## 10. Связанные документы и история версий

- `gitops/apps/ysrch/README.md` — runbook деплоя и грабли.
- `architecture/endpoints.md` — адрес `ysrch.demo-ai-lab.ru` и правило коротких имён.
- `architecture/mcp-registry-spec.md` — каталог, в который публикуется сервер; `gitops/mcp-servers/`.
- `architecture/doc-spec.md` — второй MCP-инструмент стенда (разбор документов).
- Форк: `github.com/msklv/yandex-search-mcp-server` (Apache-2.0; файлы апстрима © 2025 YANDEX LLC).

История версий:

- **v1.0** (2026-10-28): первая версия и сразу факт — образ `v1.3.1` по digest, деплой в ns `ysrch`,
  TCP-пробы, ConfigMap-обёртка из-за 421 `Invalid Host header`, Secret `yandex-search`, приёмка
  `initialize`/`tools/list`/`web_search`/`gen_search` из LAN и через edge, публикация
  `ru.demo-ai-lab/yandex-search@1.0.0` в каталоге MCP.
