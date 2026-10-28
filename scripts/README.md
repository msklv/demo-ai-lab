# scripts

Два независимых инструмента: кластер и обвязка (то, что живёт вне кластера). Оба — stdlib-only;
прогресс печатают в stderr, результат — в stdout; цвет только в TTY.

## k8s_health.py — кластер

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

## env_health.py — обвязка

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

## grafana_import.sh — дашборд «неймспейсы» во встроенной Grafana Higress

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

## Общее

Коды выхода: `0` — всё зелёное, `2` — WARN, `1` — FAIL. Цвет: зелёный/жёлтый/красный/серый по
критичности, включается в TTY; гасится `--no-color`, `NO_COLOR=1`, `--json`; `FORCE_COLOR=1` включает в пайпе.
Ход работы виден строками `… шаг` в stderr; в `--json` прогресс выключен, stdout остаётся чистым JSON.

Разбор не-зелёного — `references/status-audit.md` (кластер);
`architecture/external-access-spec.md` §E7 (обвязка внешнего доступа).
