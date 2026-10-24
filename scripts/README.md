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

## Общее

Коды выхода: `0` — всё зелёное, `2` — WARN, `1` — FAIL. Цвет: зелёный/жёлтый/красный/серый по
критичности, включается в TTY; гасится `--no-color`, `NO_COLOR=1`, `--json`; `FORCE_COLOR=1` включает в пайпе.
Ход работы виден строками `… шаг` в stderr; в `--json` прогресс выключен, stdout остаётся чистым JSON.

Разбор не-зелёного — `references/status-audit.md` (кластер);
`architecture/external-access-spec.md` §E7 (обвязка внешнего доступа).
