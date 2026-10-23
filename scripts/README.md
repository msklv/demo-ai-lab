# scripts

## k8s_health.py

Быстрая проверка здоровья кластера demo-ai-lab. Только stdlib; из PATH — `kubectl`, `ssh`, `curl`, `openssl`.

```bash
python3 scripts/k8s_health.py            # полный аудит (~10 с)
python3 scripts/k8s_health.py --brief    # только WARN/FAIL
python3 scripts/k8s_health.py --json     # машинный вывод
python3 scripts/k8s_health.py --tunnel   # + статус туннеля в Cloudflare API (FAIL → WARN, если сквозной 200 через edge проходит)
```

Флаги: `--kubeconfig` (по умолчанию `~/.kube/demo-ai-lab.conf`), `--context`, `--no-ssh`, `--no-external`, `--samples N`, `--timeout S`, `--ssh user@host` (повторяемо), `--no-color`.

Вывод красится по критичности (зелёный PASS / жёлтый WARN / красный FAIL / серый SKIP) только в TTY; `--no-color`, `NO_COLOR=1` и `--json` цвет отключают, `FORCE_COLOR=1` — включает принудительно (для пайпов).

Проверяет: API/VIP → ноды+pressure → health-gate подов → кворум etcd → control-plane/kube-vip → Argo/Longhorn/Higress → железо по SSH → внешний путь.

Ход работы виден сразу: строка `… шаг` в stderr и результат с временем шага — по мере выполнения, а не одним блоком в конце. В `--json` прогресс выключен, stdout остаётся чистым JSON.

Коды выхода: `0` — всё зелёное, `2` — WARN, `1` — FAIL.

SSH-цели: `--ssh` → env `K8S_HEALTH_SSH="u@h,u@h"` → `ansible/hosts.cluster.yml` (+env `K8S0X_USER`) → `inventory.local.md`. Секретов в скрипте нет.

Разбор не-зелёного — skill `demo-ai-lab-stand`, `references/status-audit.md`.
