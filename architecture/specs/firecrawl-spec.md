# Firecrawl self-host (`fc`) — извлечение веб-страниц для агентов стенда

> **Версия:** v1.1 (2026-11-10) · **Статус:** **развёрнуто 2026-11-10 на k8s-05** (C1–C5 зелёные,
> каталог `gitops/apps/fc/`; ставили `kubectl apply`, Argo Application ещё не создан). Отличия от v1.0 —
> размещение на одной ноде, лимит api 3Gi и `args` у nuq-postgres (§1, §4); история — в конце документа.
> **Цель:** шаг 2+/4 — **web → markdown** внутри кластера: агент или сервис отдаёт URL и получает
> markdown/HTML/links, отрендеренный настоящим Chromium. Закрывает пробел «страница прочитана и
> приведена к LLM-виду», которого у стенда сейчас нет: `ysrch.` даёт только сниппеты поиска, а
> Chromium живёт внутри пода `her` и другим потребителям недоступен.
> **Внешнее имя:** **нет в v1** — только `ClusterIP` (`firecrawl-api.fc.svc.cluster.local:3002`).
> Ingress заводится отдельной фазой C6 и только с гейтом на шлюзе.
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/fc/` (plain-манифесты); Secret — до первого
> синка, в git не попадает.

Стиль-образцы: `architecture/specs/ysearch-spec.md` (Y\*), `architecture/specs/doc-spec.md` (D\*),
`architecture/specs/keycloak-spec.md` (K\*). Эта спека занимает букву **C** (C1–C6).

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Приложение | **Firecrawl** `2.10.19-production` + его микросервис `playwright-service` | единственный поддерживаемый self-host «URL → markdown» с рендером JS; альтернатива «свой Chromium + trafilatura» разобрана в §9 как отвергнутая |
| Лицензия | репозиторий firecrawl — **AGPL-3.0**; каталог `apps/playwright-service-ts` объявляет ISC | внутреннее использование на стенде обязательств не создаёт; **распространение изменённого образа наружу** — уже AGPL-обязательства. В публичных доках фиксируем факт, решение принято владельцем |
| Образы (пин по amd64-дигесту) | api `ghcr.io/firecrawl/firecrawl:2.10.19-production@sha256:618504f7…` · `ghcr.io/firecrawl/playwright-service@sha256:1bc39643…` · `ghcr.io/firecrawl/nuq-postgres@sha256:5a0be882…` · `redis:8.10.1-alpine@sha256:de4d1887…` · `rabbitmq:3.13.7-management@sha256:9cfb7e92…` | дигесты сняты `docker manifest inspect` 2026-11-10 (amd64-манифесты в §2). У `playwright-service` и `nuq-postgres` **версионных тегов нет** — тег `latest`, поэтому пин только по дигесту, тег в манифесте не указываем |
| Namespace | `fc` (создаёт ApplicationSet `apps` по имени каталога) | один ns на сервис, как у `ysrch`/`doc` |
| Состав | 5 объектов: Deployment `firecrawl-api`, Deployment `playwright-service`, Deployment `redis`, Deployment `rabbitmq`, StatefulSet `nuq-postgres` + 4 Service | полный стек нужен не «на всякий случай»: api на старте требует redis, очередь (RabbitMQ), state-БД (nuq-postgres) и рендерер — минимальный набор из официального compose |
| Реплики | по 1 каждого | демо-сервис; api масштабируется отдельно, если понадобится (очередь общая) |
| Размещение | **`nodeAffinity.required` `kubernetes.io/hostname=k8s-05` на все 5 подов** (решение владельца 2026-11-10; в v1.0 — `preferred` на `demo-ai-lab/role=ingress` = k8s-02/03 + anti-affinity api↔playwright) | стек с Chromium тяжёлый по памяти, на k8s-05 свободно 32 Gi, инференса и шлюза там нет. Размен: потеря k8s-05 = `Pending` у всего сервиса (в v1.0 hard-pin отвергался именно за это). Anti-affinity снят: на одной ноде он не разводит поды, а на `preferred`-скоринге увёл api на k8s-04 — рядом с GPUStack |
| Ресурсы | api **`500m/768Mi` → `2/3Gi`** (в v1.0 было `250m/512Mi` → `1/2Gi`: с лимитом 2Gi под уходит в `OOMKilled`, steady-state 2,6 Gi — в одном контейнере 9 node-процессов); playwright `200m/512Mi` → `1/2Gi`; rabbitmq `100m/256Mi` → `500m/512Mi`; redis `50m/64Mi` → `200m/256Mi`; nuq-postgres `100m/256Mi` → `500m/1Gi` | steady-state на Mac: api ~150Mi, playwright ~200Mi, pg ~40Mi; лимиты с запасом на Chromium и crawl. Сумма requests — 950m/1.9Gi, на k8s-05 (15,5 Gi allocatable, занято ~1,3 Gi) помещается с запасом |
| PriorityClass | `demo-stand-critical` (объект уже есть, свой не создаём) | Argo падает на дубле Cluster-объекта |
| Порты | api `3002`, playwright `3000`, redis `6379`, rabbitmq `5672` (management `15672` наружу не нужен), nuq-postgres `5432` | порты — как в апстрим-compose, чтобы env-контракт не расходился с документацией Firecrawl |
| Пробы | api `httpGet /` → 200 (`{"message":"Firecrawl API"}`); playwright `httpGet /health` → 200; redis/rabbitmq/pg — `tcpSocket` | **у firecrawl-api нет `/health`, `/v1/health`, `/test` — все 404** (проверено 2026-11-10); единственная дешёвая проба — корень |
| Хранилище | nuq-postgres PVC `5Gi` Longhorn; rabbitmq PVC `2Gi` Longhorn; redis — `emptyDir` | очередь и state переживают рестарт пода; redis — только rate-limit/кэш, терять нечего |
| TLS / Ingress | **не заводим в v1** | у self-host нет аутентификации (`USE_DB_AUTHENTICATION=false`): публичный маршрут = открытый скрап-прокси в интернет от имени стенда. Любой Ingress на стенде сразу публикуется наружу — это не то, что нужно в фазе C1–C5 |
| Egress | **нужен выход в интернет** (MikroTik NAT) | без него сервис бессмысленен; egress из подов проверен (§2) |
| Guard приватных адресов | `ALLOW_LOCAL_WEBHOOKS=false` (значение по умолчанию) | сервис резолвит цель и отбивает приватные/LAN-адреса и на входе, и в навигации. Оставляем включённым: страницы стенда читаются изнутри пода `her`, а не через внешний скрапер. Расширение доступа — отдельное решение с ADR, не побочный эффект установки |
| Секреты | Secret `fc-secrets`: `postgres-password`, `rabbitmq-user`, `rabbitmq-password`, `bull-auth-key` | в манифестах только `secretKeyRef`; файл `firecrawl.local.md` (gitignored, `0600`), раскладывает `scripts/firecrawl_secrets.sh` |
| Каталог MCP | не в v1; кандидат фазы C6 (`ru.demo-ai-lab/firecrawl@1.0.0`) | агентам на стенде привычнее MCP-контракт; обёртка ставится отдельным объектом, а не вместо API |

## 2. Предпосылки — проверено 2026-11-10

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass; kubectl get priorityclass demo-stand-critical
kubectl get nodes -L demo-ai-lab/role
kubectl top nodes
docker manifest inspect ghcr.io/firecrawl/playwright-service:latest   # локально, amd64-манифест
kubectl -n ysrch exec <pod> -- python -c 'import urllib.request;print(urllib.request.urlopen(
  "https://ghcr.io/token?scope=repository:firecrawl/playwright-service:pull&service=ghcr.io").status)'
kubectl -n ysrch exec <pod> -- python -c 'import urllib.request;print(urllib.request.urlopen(
  "https://example.com",timeout=10).status)'
```

| Факт | Значение (замер) |
|---|---|
| StorageClass | `longhorn` (default, `replica=2`), `longhorn-static` |
| IngressClass | `higress`; TLS-секрет читается только в ns Ingress'а |
| PriorityClass | `demo-stand-critical` (100000) есть |
| Ноды (allocatable / занято) | 01 — 24.3 Gi / 70 %; 02 — 15.5 Gi / 63 %; 03 — 15.5 Gi / 66 %; 04 — 32 Gi / 38 % (GPUStack); 05 — 15.5 Gi / 9 % |
| Роли | `demo-ai-lab/role=ingress` — k8s-02, k8s-03 |
| Pod-сеть | Cilium cluster-pool `10.0.0.0/8`, маска 24 |
| Дигесты amd64 | api `sha256:618504f749ec8c9564839b383262e91dd46739073db406438edd308f7079f16d`; playwright `sha256:1bc396438d3e2b4b20c3bff1a19d008e1c2649b54232d496ed54b804e8ab5772`; nuq-postgres `sha256:5a0be88215431b8dd57ae5d701ee191521cd1ac8e882a65558ae95c4587c57cb`; redis `sha256:de4d18872bf67ad0bd62224a712263975ca1d53b9b1d0d5d076082e7fa887890`; rabbitmq `sha256:9cfb7e92ae7d296aec4d1ae799e431209f7ed57d55f9c929d95667d0ccf1c920` |
| Размеры (сжатый pull) | api ≈ 1.6 GB, playwright ≈ 2.4 GB (слой «chromium + системные deps» — 1.31 GB), nuq-postgres ≈ 660 MB, rabbitmq ≈ 250 MB, redis ≈ 40 MB → **≈ 5 GB** на канал 4–6 МБ/с; предтяжка обязательна |
| GHCR с площадки | анонимный токен на `firecrawl/playwright-service` → **200** (pull разрешён; реестр не блокирован) |
| Egress из пода | `https://example.com` из ns `ysrch` → **200**, 577 B, 0.2 s |
| API Firecrawl (эталон на Mac, тот же тег) | `POST /v2/scrape {"url":"https://example.com","formats":["markdown"]}` → 200, `success:true`, markdown 958 симв.; `/v2/search` → 200; `/` → 200; `/health`, `/v1/health`, `/test` → **404** |
| Guard playwright-service | `POST /scrape` на `http://192.168.10.230/` и `http://10.20.20.5/` → `pageStatusCode: 403`, `pageError: "Blocked insecure target URL … resolves to a private/internal address"` (HTTP-код ответа при этом 200) |
| `nuq-postgres` | требует `command: postgres -c cron.database_name=<POSTGRES_DB>` — иначе init падает (грабля апстрим-образа) |

## 3. Секреты

| Приватный файл (вне git, `0600`) | Что внутри | Кто читает |
|---|---|---|
| `firecrawl.local.md` | `postgres-password`, `rabbitmq-user`, `rabbitmq-password`, `bull-auth-key` — генерируются, никем не выдаются | `scripts/firecrawl_secrets.sh` |

```bash
./scripts/firecrawl_secrets.sh --init   # один раз: шаблон файла, значения генерируются (openssl rand -hex 24)
./scripts/firecrawl_secrets.sh          # Secret fc-secrets в ns fc до первого синка Argo
```

Правила: значения не печатаются (скрипт выводит только имена объектов), Secret создаётся
идемпотентно (`create --dry-run=client | apply`), файл покрыт правилом `*.local.md` из `.gitignore`
(проверка: `git check-ignore -v firecrawl.local.md`).

## 4. Развёртывание

Состав каталога `gitops/apps/fc/` (ApplicationSet `apps` подхватывает каталог по имени):

```
gitops/apps/fc/
  10-nuq-postgres.yaml   # StatefulSet + volumeClaimTemplates 5Gi + Service
  15-redis-rabbit.yaml   # Deployment redis (emptyDir) + Deployment rabbitmq (PVC 2Gi) + 2 Service
  20-playwright.yaml     # Deployment playwright-service + Service
  25-api.yaml            # Deployment firecrawl-api + Service
  README.md              # чем отличается от апстрим-compose и почему
```

Ключевые фрагменты (полные манифесты — в каталоге; здесь то, что легко сделать неправильно):

```yaml
# 25-api.yaml — env-контракт повторяет апстрим-compose, иначе api не поднимается
        env:
          - {name: PORT, value: "3002"}
          - {name: HOST, value: "0.0.0.0"}
          - {name: REDIS_URL, value: "redis://redis:6379"}
          - {name: REDIS_RATE_LIMIT_URL, value: "redis://redis:6379"}
          - {name: PLAYWRIGHT_MICROSERVICE_URL, value: "http://playwright-service:3000/scrape"}
          - {name: POSTGRES_HOST, value: "nuq-postgres"}
          - {name: POSTGRES_PORT, value: "5432"}
          - {name: POSTGRES_DB, value: "firecrawl"}
          - {name: POSTGRES_USER, value: "firecrawl"}
          - {name: POSTGRES_PASSWORD, valueFrom: {secretKeyRef: {name: fc-secrets, key: postgres-password}}}
          - name: RABBITMQ_USER          # объявлены ВЫШЕ NUQ_RABBITMQ_URL: $(VAR) разрешается только так
            valueFrom: {secretKeyRef: {name: fc-secrets, key: rabbitmq-user}}
          - name: RABBITMQ_PASSWORD
            valueFrom: {secretKeyRef: {name: fc-secrets, key: rabbitmq-password}}
          - {name: NUQ_RABBITMQ_URL, value: "amqp://$(RABBITMQ_USER):$(RABBITMQ_PASSWORD)@rabbitmq:5672"}
          - {name: USE_DB_AUTHENTICATION, value: "false"}   # self-host без аккаунтов
          - {name: BULL_AUTH_KEY, valueFrom: {secretKeyRef: {name: fc-secrets, key: bull-auth-key}}}
          - {name: BLOCK_MEDIA, value: "false"}             # строки "true"/"false", не bool
          - {name: ALLOW_LOCAL_WEBHOOKS, value: "false"}    # guard приватных адресов — см. §1
          - {name: LOGGING_LEVEL, value: "info"}
        args: ["node", "dist/src/harness.js", "--start-docker"]
```

- **Порядок старта.** `depends_on` в k8s нет: api падает и перезапускается, пока очередь/БД/рендерер
  не поднялись (`backoffLimit`-подобное поведение даёт сам Deployment). Это нормально и ожидаемо —
  в приёмке C4 считается, что до 2 минут api может быть в `CrashLoopBackOff`.
- **`RABBITMQ_DEFAULT_USER/PASS`** — на rabbitmq из `fc-secrets`; api получает те же значения через
  `NUQ_RABBITMQ_URL` (подстановка `$(VAR)` работает только для переменных, объявленных **выше** в списке).
- **nuq-postgres** — `args: ["-c", "cron.database_name=firecrawl"]` (именно `args`: `command` затирает
  `docker-entrypoint.sh`, и postgres отказывается стартовать root'ом — `"root" execution … is not
  permitted`, CrashLoop). Без этой опции
  на pg_cron (проверено на стенде: апстрим-образ ждёт совпадения имени БД).
- **Размещение/`securityContext`** (факт установки 10.11.2026): у `nuq-postgres` и `rabbitmq` контейнерный
  `securityContext` не ограничивается (`drop: [ALL]` ломает их entrypoint — `chown /var/lib/rabbitmq:
  Operation not permitted`), seccomp `RuntimeDefault` оставлен на уровне пода. У `rabbitmq` задан
  `RABBITMQ_NODENAME=rabbit@localhost` — иначе имя узла Mnesia следует за hostname пода и меняется при
  пересоздании.
- **Отличия от Mac-стека** (переносим осознанно): нет `extra_hosts: host.docker.internal` (в кластере
  модель берётся по DNS, а `/extract` в v1 вообще не включён — §9 Q-C2); нет `ulimits nofile=65535`
  (в pod-spec этого поля нет — при нехватке fd поднимаем `limits` и следим по `top`/логам).
- **Root-ФС**: оба образа пишут в `/tmp` (Chromium, node) — `readOnlyRootFilesystem` не включаем, как
  у `ysrch` (там причина другая — `__pycache__`, принцип тот же).

## 5. Конфигурация потребителей

| Потребитель | Как ходит | Что получает |
|---|---|---|
| `her` (Hermes) | `http://firecrawl-api.fc.svc.cluster.local:3002/v2/scrape` + `web_extract` через бэкенд firecrawl (если включим) | markdown страницы; Chromium в поде остаётся для интерактивных сценариев |
| `owu` (RAG) | тот же API как внешний «web loader» (не в v1) | markdown для ingest |
| `qm` (шаг 4) | через MCP-обёртку (фаза C6) | `firecrawl_scrape`-подобный инструмент |
| `scripts/*.py` (health, доки) | `curl` из пода/с ноутбука в LAN | markdown/HTML без своего браузера |

Контракт вызовов — апстримный Firecrawl v2 (`/v2/scrape`, `/v2/crawl`, `/v2/map`), своей обёртки в v1 нет.
Ограничения задаём на уровне api: `MAX_CONCURRENT_PAGES=5` у playwright-service (апстрим-дефолт).

## 6. Фазы и приёмка

### C1 — пины и предтяжка образов

```bash
for img in ghcr.io/firecrawl/firecrawl:2.10.19-production@sha256:618504f7… \
           ghcr.io/firecrawl/playwright-service@sha256:1bc39643… \
           ghcr.io/firecrawl/nuq-postgres@sha256:5a0be882… \
           redis:8.10.1-alpine@sha256:de4d1887… \
           rabbitmq:3.13.7-management@sha256:9cfb7e92…; do
  kubectl -n fc run prepull-$(echo $img | tr '/:@' '___' | cut -c1-30) --image=$img \
    --restart=Never --image-pull-policy=IfNotPresent --command -- /bin/true
done
kubectl -n fc get pods -o custom-columns='POD:.metadata.name,STATUS:.status.phase,IMAGE:.status.containerStatuses[0].imageID'
```

Приёмка: у всех пяти подов `Succeeded`, в `imageID` — **тот же digest**, что в манифесте; поды удалить.
Грабля из спеки-образца: `--overrides` с `nodeSelector` может быть проигнорирован — читать `.spec.nodeName`.

### C2 — секреты

```bash
./scripts/firecrawl_secrets.sh --init   # один раз: файл с генерированными значениями
./scripts/firecrawl_secrets.sh          # Secret fc-secrets (идемпотентно)
kubectl -n fc get secret fc-secrets -o jsonpath='{.data}' | tr ',' '\n' | cut -d'"' -f2
```

Приёмка: 4 ключа на месте, значения не выводились в терминал, `git status --porcelain` не содержит
`firecrawl.local.md`.

### C3 — stateful-часть (nuq-postgres, redis, rabbitmq)

```bash
kubectl -n fc get pods -o wide
kubectl -n fc exec deploy/nuq-postgres -- pg_isready -U firecrawl -d firecrawl
kubectl -n fc exec deploy/rabbitmq -- rabbitmq-diagnostics -q ping
kubectl -n fc exec deploy/redis -- redis-cli ping
```

Приёмка: `pg_isready` → `accepting connections`, `ping` RabbitMQ → без ошибок, `PONG`; PVC
`data-nuq-postgres-0` в `Bound` (Longhorn, 2 реплики).

### C4 — api + playwright-service

```bash
kubectl -n fc get deploy,pods,svc
kubectl -n fc exec deploy/firecrawl-api -- node -e \
  "fetch('http://playwright-service:3000/health').then(r=>r.text()).then(console.log)"
# прод-путь: scrape через ClusterIP (из любого пода стенда)
kubectl -n ysrch exec <pod> -- python -c "
import urllib.request,json
r=urllib.request.urlopen(urllib.request.Request('http://firecrawl-api.fc.svc.cluster.local:3002/v2/scrape',
  data=json.dumps({'url':'https://example.com','formats':['markdown']}).encode(),
  headers={'Content-Type':'application/json'}),timeout=90)
d=json.load(r);print(r.status, d['data']['markdown'][:120])"
```

Приёмка: `success:true`, markdown непустой; страница с JS (SPA) отдаёт контент, а не пустой каркас;
русская страница даёт читаемую кириллицу. Факт в `kubectl top pod` (ожидание: api ≤ 300Mi, playwright
≤ 400Mi на простое).

### C5 — приёмка поведения (главная)

| Проверка | Команда | Ожидание |
|---|---|---|
| Guard приватных адресов | `POST /v2/scrape {"url":"http://192.168.10.230/"}` | `pageStatusCode: 403`, `pageError` про private/internal; **никакой** страницы стенда в ответе |
| Guard на кластер | `POST /v2/scrape {"url":"http://firecrawl-api.fc.svc.cluster.local:3002/"}` | то же (403) |
| Отказ рендерера | `kubectl -n fc scale deploy/playwright-service --replicas=0`, scrape, затем вернуть 1 | scrape → ошибка без зависания (таймаут апстрима), после возврата пода — снова 200 без рестарта api |
| Параллельность | 5 одновременных scrape | все 5 завершаются, `playwright-service /health` показывает `activePages ≤ 5` |
| Память под нагрузкой | `kubectl top pod -n fc` после 20 scrape | playwright ≤ лимита 2Gi, api ≤ 2Gi; OOMKilled в `describe` нет |
| Отсутствие публичного маршрута | `curl --resolve fc.demo-ai-lab.ru:443:192.168.10.230 https://fc.demo-ai-lab.ru/` | не резолвится/нет Ingress — в v1 имени не существует |

### C6 (опционально) — MCP-обёртка и внешний маршрут

- **Обёртка:** официальный `firecrawl-mcp` (или своя на `@modelcontextprotocol/sdk`) в ns `fc`,
  `FIRECRAWL_API_URL=http://firecrawl-api:3002`, StreamableHTTP `/mcp`, TCP-проба.
- **Маршрут:** Ingress `fc.demo-ai-lab.ru` (Higress) + **key-auth** (как `llm-svc.`) либо LAN-гейт
  `WasmPlugin ip-restriction` (как `argo.`/`lng.`). Без гейта маршрут не заводить: анонимный скрапер
  на публичном хосте = исходящий трафик стенда по чужой указке.
- **Каталог:** `gitops/mcp-servers/firecrawl/server.json` + публикация по правилам `ysearch`/`docling`
  (`gitops/apps/ysrch/README.md`, `architecture/specs/mcp-registry-spec.md` §публикация); каталог
  `mcp-servers/` лежит **вне** `apps/*` — Argo падает на JSON без `kind`.

## 7. Операции

| Операция | Как |
|---|---|
| Health-smoke | `kubectl -n fc get pods` + `httpGet /` у api + `POST /v2/scrape` на `example.com`; в `scripts/k8s_health.py` сервис **не заводим**, пока он не станет демо-маршрутом |
| Апгрейд | поднять пин в `gitops/apps/fc/*.yaml` (новый amd64-дигест) → Argo sync; для `playwright-service`/`nuq-postgres` сначала проверить, что `latest` не сломал контракт (тег не переиспользуем — только дигест) |
| Откат | вернуть предыдущий дигест в git → sync; PVC при этом не трогаем (совместимость схемы миграций не гарантирована — при мажорном апгрейде api сначала `pg_dump`) |
| Бэкап | состояние не критично (очередь crawl + rate-limit), но перед апгрейдом: `pg_dump -U firecrawl firecrawl` дамп вне репо |
| Ротация паролей | `./scripts/firecrawl_secrets.sh` с новыми значениями → `kubectl -n fc rollout restart deploy/nuq-postgres deploy/rabbitmq deploy/firecrawl-api` |
| Чистка | `kubectl -n fc delete pod -l app=playwright-service` — свежий браузер (утечки Chromium лечатся рестартом рендерера, api переживает) |

## 8. Риски

| # | Риск | Что делаем |
|---|---|---|
| R-C1 | 5 GB образов через 4–6 МБ/с, окно pull растягивает C1 | предтяжка отдельной фазой, критерий — digest в `imageID`; не начинать C4 до успеха C1 |
| R-C2 | Память на 02/03 (~6 Gi свободно) при crawl большого сайта | лимиты 2Gi у api/playwright, `preferred`-affinity на пару, замер в C5; при OOM — снизить `MAX_CONCURRENT_PAGES` |
| R-C3 | Chromium упал → api отдаёт 500 на все scrape | рестарт рендерера не требует рестарта api (проверяется в C5); пробы у playwright — `/health` |
| R-C4 | Анонимный API + egress = внутренний скрап-прокси | нет Ingress в v1; доступ только из кластера; при появлении потребителей вне кластера — key-auth/LAN-гейт (C6). NetworkPolicy на ns `fc` — кандидат, но на стенде сейчас **ни одного** объекта NetworkPolicy: вводить её одной этой спекой значит завести первый класс объектов — отдельное решение |
| R-C5 | `latest`-теги у `playwright-service`/`nuq-postgres` | пин по дигесту; обновление — осознанным коммитом, не `pull_policy: always` |
| R-C6 | AGPL-3.0 у firecrawl | внутреннее использование; распространение изменённого образа — только после юридической проверки |
| R-C7 | Нет `/health` у api → проба только `/` | проба корня ловит «процесс жив», но не «БД доступна»: добавить второй probe-контейнер нельзя, поэтому живость стека проверяет C5-скрипт (scrape + pg_isready) |
| R-C8 | `nuq-postgres` — форк postgres от Firecrawl, обновляется без версий | свой PVC и `pg_dump` перед апгрейдом; при смене мажорной версии — новый PVC и перенос дампом |
| R-C9 | Дублирующая роль: у `her` уже есть Chromium | спека нужна не «агенту Hermes», а **потребителям без браузера**; если таких не появится — сервис не разворачиваем (Q-C1) |
| R-C10 | Внешние страницы тянутся в обход шлюза с DLP (ADR-0006/0008) | это не LLM-трафик, но новый egress-путь со стенда: фиксируем в §1 и в ADR о egress, а не только в спеке |

## 9. Что забывают в таких спеках + открытые вопросы

- **Обоснование нужности.** Ставить 5 подов «чтобы было» нельзя: закрываемый пробел — «URL → markdown
  для того, у кого нет браузера». Сегодня это `owu`/`rag`/скрипты и будущий `qm`; `her` обходится своим
  Chromium. Если ни один потребитель не подтвердится — установка не выполняется (Q-C1).
- **Развилка «firecrawl или свой тонкий сервис».** Вариант «playwright-service + trafilatura/markdownify
  в 200 строках» легче в 8 раз (нет redis/rabbit/pg, образ 2.4 GB вместо 5 GB) и без AGPL-firecrawl, но
  теряет `/crawl`, `/map` и обновления апстрима. Решение принято в пользу firecrawl (Q-C4) — при
  изменении приоритетов возвращаться к этому пункту, а не переписывать §1.
- **`/extract` (LLM-структурирование) в v1 выключен.** Ему нужен OpenAI-совместимый бэкенд: кандидат —
  `llm-svc.demo-ai-lab.ru` (через Higress с ключом) либо `api.demo-ai-lab.ru` (GPUStack). Это работа
  C6+ и отдельное решение по данным (страница уходит в модель).
- **Кладовая образов.** Прямой pull из GHCR на стенде работает, но 5 GB на каждый пересоздание ноды —
  аргумент за зеркало в Artifactory; пока не делаем (ADR-0003/пункт «доставка образов», строка 14 §7
  борда: локальный реестр снят).
- **Логи и метрики.** Своего `/metrics` у firecrawl нет: наблюдаемость — логи подов + Kuvasz HTTP-монитор
  на `firecrawl-api:3002/` (когда сервис станет маршрутом). Отдельный Prometheus-скрейп не заводим.

| # | Вопрос | Кому/когда |
|---|---|---|
| Q-C1 | Подтверждён ли хотя бы один потребитель вне `her` (owu/rag/скрипты/qm)? | владельцу, до C1 |
| Q-C2 | Нужен ли `/extract` и через какой LLM-бэкенд (`llm-svc.` vs `api.`)? | владельцу, C6 |
| Q-C3 | Заводить ли первый NetworkPolicy на стенде (ingress только из `her`/`owu`/`qm`) или ограничиться отсутствием маршрута? | владельцу, после C5 |
| Q-C4 | Остаёмся на firecrawl или переходим на тонкий «playwright + markdownify»? | владельцу, если C1 покажет, что 5 GB/5 подов не окупаются |
| Q-C5 | Нужен ли MCP-контракт для агентов (обёртка) или агентам достаточно HTTP-вызова из скилла | владельцу, C6 |

## 10. Связанные документы и история

- `architecture/specs/hermes-spec.md` — Chromium в поде агента (§7, §8.1), откуда взят вывод «Playwright агенту не нужен»;
- `architecture/specs/ysearch-spec.md` — поиск (сниппеты), разделение ролей «поиск ≠ извлечение»;
- `architecture/specs/doc-spec.md` — извлечение **документов** (PDF/сканы), не страниц;
- `architecture/specs/llm-proxy-spec.md`, ADR-0006/0008 — DLP/страж на внешнем трафике;
- `architecture/specs/mcp-registry-spec.md`, `gitops/apps/ysrch/README.md` — публикация в каталоге (фаза C6);
- `adr/` — решение о новом egress-пути (R-C10) фиксируется отдельным ADR при переходе к C1.

| Версия | Дата | Что |
|---|---|---|
| v1.1 | 2026-11-10 | **развёрнуто на k8s-05** (`gitops/apps/fc/`, C1–C5): hard-pin на одну ноду вместо пары 02/03 (anti-affinity снят), лимит api 3Gi (2Gi → `OOMKilled`, факт 2,6 Gi), `nuq-postgres` через `args`, `securityContext` снят у pg/rabbitmq (их entrypoint'ы делают `chown`/`gosu`). Факт приёмки: scrape example.com 958 симв., SPA `quasar.dev` 6,9 КБ, ru-wiki «Москва» 632 КБ кириллицей, 5/5 параллельных scrape, guard отбивает `192.168.10.230` и `*.svc.cluster.local` (ответ 500 `SCRAPE_ALL_ENGINES_FAILED`, а не `pageStatusCode: 403`). Ставили `kubectl apply` — Argo Application ещё не создан |
| v1.0 | 2026-11-10 | первая редакция: пины amd64 (5 образов), решения по ns/размещению/ресурсам/пробам, guard приватных адресов включён, Ingress и MCP — фаза C6; живьём проверены дигесты, размеры, доступность GHCR с площадки, egress из пода, контракт `/v2/scrape` на эталоне и поведение guard. Живых шагов на стенде не выполнено — статус «спека, не установлено» |
