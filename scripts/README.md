# scripts

Health-скрипты стенда (кластер и обвязка) и вспомогательные операции. Health-скрипты — stdlib-only;
прогресс печатают в stderr, результат — в stdout; цвет только в TTY.

## Health-скрипты

### k8s_health.py — кластер

```bash
python3 scripts/k8s_health.py            # полный аудит (~10 с)
python3 scripts/k8s_health.py --brief    # только WARN/FAIL
python3 scripts/k8s_health.py --json     # машинный вывод
python3 scripts/k8s_health.py --no-ssh   # без живого замера нод по SSH
```

Флаги: `--kubeconfig` (по умолчанию `~/.kube/demo-ai-lab.conf`), `--context`, `--ssh user@host`
(повторяемо), `--no-ssh`, `--no-origin` (алиас `--no-external`), `--timeout S`, `--brief`, `--json`, `--no-color`.

Проверяет: API через VIP → ноды+pressure → health-gate подов → кворум etcd → control-plane/kube-vip →
Argo/Longhorn/Higress → железо по SSH → origin в LAN (`.230` + сертификат). Туннель и внешний путь —
в `env_health.py`.

SSH-цели: `--ssh` → env `K8S_HEALTH_SSH="u@h,u@h"` → `ansible/hosts.cluster.yml` (+env `K8S0X_USER`) → `inventory.local.md`.

### env_health.py — обвязка

```bash
python3 scripts/env_health.py                 # внешняя VM + туннель + edge
python3 scripts/env_health.py --brief         # только WARN/FAIL
python3 scripts/env_health.py --no-vm         # без SSH к внешней VM
python3 scripts/env_health.py --no-check-host # без подтверждения из внешних точек
```

Флаги: `--vm user@host`, `--kubeconfig`, `--no-vm`, `--no-tunnel`, `--no-edge`, `--no-check-host`,
`--samples N`, `--timeout S`, `--brief`, `--json`, `--no-color`.

Проверяет:
- **внешняя VM-egress** — SSH-доступ и ресурсы, `cloudflared` (active + версия), `haproxy` (active),
  бэкенды hop-ов через stats-сокет (`UP/DOWN`), слушатели `19443/18443/18444`, ответ origin через hop;
- **Cloudflare-туннель** — API: `status`, число соединений, colo, сверка egress коннектора с адресом VM;
- **внешний путь** — 4 запроса к edge; при неудаче вердикт подтверждается из внешних точек check-host
  (консоль стоит за ZTN и видит edge из colo FRA — одна консоль не показатель); плюс smoke `echo.*`.

Креды и цели: `--vm` → env `ENV_HEALTH_VM` → `inventory.local.md`; API-токен Cloudflare → env
`CF_API_TOKEN` / `CLOUDFLARE_API_TOKEN` → Secret `cert-manager/cloudflare-api-token` через `kubectl`.
Секретов в скрипте нет.

## Контракт и общие правила

Коды выхода: `0` — всё зелёное, `2` — WARN, `1` — FAIL. Цвет: зелёный/жёлтый/красный/серый по
критичности, включается в TTY; гасится `--no-color`, `NO_COLOR=1`, `--json`; `FORCE_COLOR=1` включает в пайпе.
Ход работы виден строками `… шаг` в stderr; в `--json` прогресс выключен, stdout остаётся чистым JSON.

Разбор не-зелёного — `references/health-runbook.md` (кластер) и
`architecture/specs/external-access-spec.md` §E7 (обвязка внешнего доступа).

## Как писать и расширять чеки

**Язык — Python 3 (только stdlib), не bash и не PowerShell 7.** Аргумент фактический, не вкусовой:
`python3` + `PyYAML` есть на всех нодах, а **`jq` нет ни на одной** — bash-вариант
`kubectl -o json | jq` тянет новую зависимость на каждый хост, а без jq остаётся разбор текстового
вывода (`get`/`describe` без `-o json`), т.е. ровно «сбор информации по крупицам». PowerShell 7 стоит
на всех нодах (snap 7.6.6), но консоль Mac — 7.5.4: нужен `#Requires -Version 7.2` и политика
синхронного патча; берём только если в контуре появится Windows-сегмент.

**Правило класса: один верхнеуровневый идемпотентный запрос на домен, ноль обходов объектов.**
Замена `kubectl describe` и grep'а логов:

- API-сервер: `kubectl get --raw='/readyz?verbose'` — все проверки одним ответом.
- Ноды: `kubectl get nodes -o json` → `status.conditions[type=Ready|…Pressure]`.
- Нагрузки: ОДИН bulk `kubectl get pods,deploy,sts,ds,svc,ingress -A -o json` → сверка с декларативным
  списком `(kind, ns, name, minReady)` по `readyReplicas`/`updatedReplicas`/`observedGeneration`;
  события и `describe` не читать.
- Argo CD: `kubectl get applications.argoproj.io -A -o json` → `status.health.status` +
  `status.sync.status` — собственный агрегат здоровья не писать, он уже посчитан.
- Ожидание/раскатка: `kubectl wait --for=condition=Ready … --timeout=…`, `kubectl rollout status`.
- Внешние точки: по одному HTTP-запросу, параллельно (`concurrent.futures`), общий бюджет таймаута на
  прогон; печатать код+латентность, тело ошибки — только при не-200.
- Runtime-условия (Certificate Ready, Longhorn node Ready, тоннель) — из `conditions` CR, а не из логов.

**Контракт скрипта (такой у `scripts/k8s_health.py` — следовать ему, а не изобретать второй):**
флаги `--brief` / `--json` / `--timeout`, коды выхода `0` = всё зелёное, `2` = есть WARN, `1` = есть FAIL
(машиночитаемый режим возвращает `{worst, counts, checks[]}` с `status` по каждому чеку), проверка =
чистая функция «снапшот → вердикт» (повторный запуск ничего не меняет).
Поток вывода: шаг объявляется в stderr (`… <шаг>`), вердикт шага печатается сразу по готовности с его
временем — длинные шаги (внешний путь, VIP по SSH) не должны выглядеть зависанием; `--json` прогресс
выключает, цвет — только оформление (TTY / `--no-color` / `NO_COLOR` / `FORCE_COLOR`).
Гонять с консоли (`KUBECONFIG=~/.kube/demo-ai-lab.conf`), не на нодах — там user-kubeconfig нет.

**Грабли написания самих чеков:**
- **Образ etcd — distroless: shell нет.** `kubectl exec <etcd-pod> -- sh -c 'etcdctl …'` падает;
  `etcdctl` вызывать напрямую аргументами: `kubectl exec -n kube-system etcd-k8s-01 -- etcdctl
  --endpoints=https://127.0.0.1:2379 --cacert=… --cert=… --key=… member list`.
- Вывод `member list` разделён запятыми С ПРОБЕЛОМ (`id, started, k8s-03, …`): поля стрипить перед
  сравнением, иначе `f[1] == "started"` не совпадёт и чек соврёт «кворума нет» при живом etcd.
- `kubectl logs` у CrashLoop-пода отдаёт последнюю попытку и может выглядеть «старьём»: для вердикта
  брать статусы/`conditions`/счётчики рестартов, логи — только как контекст к причине.
- `kubectl exec` без stdin у static-подов висит дольше обычного — оборачивать в таймаут (10–30 с).
- Если SSH-цели берутся разбором `inventory.local.md` по шаблону `user@ip`, в список попадает и роутер
  (`admin@192.168.10.1`): фильтровать цели по фактическому набору InternalIP из `get nodes`, иначе
  счётчик нод и опрос уезжают на лишний хост.
- `account_id` для Cloudflare API брать из объекта зоны (`zones[0].account.id`): у токена с DNS:Edit
  список `/accounts` может быть пуст, и `accounts[0]` даёт ложное «CNAME на туннель не найден».

## Прочие скрипты

### llm_stats.py — статистика внешнего маршрута

Разбор access-лога шлюза: consumer, модель, токены, коды ответов и цена защиты. Это **не health-проверка**,
а наблюдаемость маршрута `llm-svc.`; колонки и примеры — `cases/02-proxy-dlp-guard.md`.

Флаги: `--tail N`, `--since 10m|1h|2d`, `--host <хост>` (повторяемо), `--namespace`, `--selector`,
`--stdin` (лог из stdin вместо `kubectl`), `--last N` (сколько запросов в таблице), `--json <файл>`,
`--events-only` (только ответы плагинов: страж/DLP/квоты).

### check_doc_links.py — ссылки в доках

Проверяет относительные ссылки в `*.md` (markdown-ссылки и **пути к `*.md`** в бэктиках); пути к
YAML/каталогам/JSON не проверяются — их сверять глазами. Битые печатает как
`файл:строка: нет файла: путь`, код выхода 1. Гонять перед коммитом (процедура — `AGENTS.md`);
`*.local.md`, `old/` и `beellama-rtx5060/` не проверяются.

### grafana_import.sh — дашборд «неймспейсы» во встроенной Grafana Higress

```bash
./scripts/grafana_import.sh                     # импорт/обновление scripts/grafana/namespaces-dashboard.json
./scripts/grafana_import.sh --file <json>       # другой дашборд (uid/заголовок — из файла)
./scripts/grafana_import.sh --host h --ip i     # не стендовые адреса (env HGC_HOST/HGC_IP)
```

Встроенный dashboard Higress Console — это Grafana+Prometheus+Loki из чарта `higress-console`
(`global.o11y.enabled=true`), наружу торчит только через консоль под `/grafana/**`. Скрипт логинится
в консоль (`/session/login`), резолвит uid datasource Prometheus и делает `POST /api/dashboards/db`
с `overwrite: true` — повторный прогон обновляет дашборд, а не плодит копии. В JSON вместо uid
datasource стоит плейсхолдер `__PROM_UID__`, его подставляет скрипт (uid уникален для инсталляции).

Права: прокси консоли требует её сессионную куку, а писать в Grafana может только админ — поэтому
запросы идут с `-b <cookie> -u admin:<pw>`. Оба пароля берутся из `higress-console-admin.local.md`
(env `HGC_PASSWORD` / `GRAFANA_ADMIN_PASSWORD`), в вывод не печатаются. Пароль Grafana тот же, под
которым в Grafana ходит сама консоль (`podEnvs.HIGRESS_CONSOLE_DASHBOARD_USERNAME/PASSWORD`, дефолт
`admin`/`admin`) — менять его без правки `podEnvs` нельзя, иначе `/dashboard/info` отдаёт 500.

Дашборд показывает то, чего нет в штатном: неймспейс берётся из имени envoy-кластера
(`outbound|<port>||<svc>.<ns>.svc.cluster.local`) и из cadvisor — req/s, доля 5xx, p90, ТОП сервисов,
CPU/память/сеть/поды по всем неймспейсам. Штатный «Higress Dashboard» привязан к неймспейсу самого
шлюза (`label_values(envoy_server_live, higress)` → только `higress-system`).

### higress_console_upgrade.sh — апгрейд консоли и размеры томов o11y

```bash
./scripts/higress_console_upgrade.sh --check   # preflight: helm upgrade --dry-run=server, без изменений
./scripts/higress_console_upgrade.sh           # апгрейд + догон FS-resize + подъём подов
```

Значения — `ansible/values-higress-console.yaml` (без секретов): `o11y.enabled`, `ingressClass` и размеры
PVC (Prometheus 2500Mi, Loki 2000Mi, Grafana 1Gi) плюс ресурсы Prometheus (76k серий не влезали в 2Gi —
OOMKilled, `exit 137`).

Почему только скриптом:

- «голый» `helm upgrade` берёт дефолты чарта → `o11y.enabled: false` **удаляет** Prometheus/Grafana/Loki,
  а `podEnvs.HIGRESS_CONSOLE_DASHBOARD_*` пропадают (витрина `/dashboard` → 500);
- дефолтные размеры PVC меньше живых → API запрещает уменьшать том, релиз уходит в `failed`
  (плюс известный SSA-конфликт `.data.grafana.ini`, который ловит preflight);
- Deployment'ы чарта объявлены без `strategy`, а тома RWO: при смене шаблона новый под не может взять
  flock на `/prometheus/lock` → скрипт гасит поды ДО апгрейда и поднимает после (эмуляция Recreate);
- расширение PVC в Longhorn завершается только при повторном монтировании — скрипт ждёт `capacity`
  и при необходимости перезапускает под.

Loki-retention чартом не настраивается (конфиг целиком в шаблоне) — рост ограничен только размером тома;
у Prometheus retention 6h захардкожен в шаблоне и служит естественным ограничителем объёма.

### Секреты и служебные

`keycloak_secrets.sh`, `keycloak_seed.py`, `mcp_registry_secrets.sh`, `yandex_search_secrets.sh` — разовые
операции с кредами и сидом (значения только из локального приватного хранилища, в git — имена ресурсов);
`llm_proxy_plugins.sh` — рендер Wasm-плагинов шлюза; `render_diagrams.py` — рендер диаграмм.
