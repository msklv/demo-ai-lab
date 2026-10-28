#!/usr/bin/env bash
# Импорт своего Grafana-дашборда в встроенный dashboard Higress Console.
#
# Консоль (`hgc.demo-ai-lab.ru`) проксирует Grafana под `/grafana/**`, поэтому отдельный
# Ingress/порт не нужен: скрипт логинится в консоль, забирает uid datasource Prometheus
# и делает POST дашборда от него. Повторный прогон обновляет дашборд (overwrite).
#
#   ./scripts/grafana_import.sh                       # дефолтный файл + LAN-IP гейтвея
#   ./scripts/grafana_import.sh --file <json>         # другой дашборд
#   ./scripts/grafana_import.sh --host hgc.example.ru --ip 1.2.3.4
#
# Хост и IP адреса по умолчанию — стендовые (`HGC_HOST`, `HGC_IP`), можно переопределить env'ом.
# Пароль админа консоли: env HGC_PASSWORD, иначе берётся из higress-console-admin.local.md
# (gitignored). Значения не печатаются — только имена объектов и итог.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${HGC_HOST:-hgc.demo-ai-lab.ru}
IP=${HGC_IP:-192.168.10.230}
FILE=scripts/grafana/namespaces-dashboard.json

while [ $# -gt 0 ]; do
  case "$1" in
    --file) FILE=$2; shift 2 ;;
    --host) HOST=$2; shift 2 ;;
    --ip)   IP=$2; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

PW=${HGC_PASSWORD:-}
if [ -z "$PW" ]; then
  PW=$(grep -oE '^admin / .+' higress-console-admin.local.md | head -1 | awk '{print $3}' || true)
fi
[ -n "$PW" ] || { echo "нет пароля: HGC_PASSWORD или higress-console-admin.local.md" >&2; exit 1; }
[ -f "$FILE" ] || { echo "нет файла дашборда: $FILE" >&2; exit 1; }

# Пароль Grafana-админа: писать в Grafana API через console-прокси можно только от админа
# (анонимный доступ в Grafana — Viewer). Пара лежит в разделе «Grafana» того же .local.md,
# патч CM `higress-console-grafana` → `[security] admin_user/admin_password`.
GPW=${GRAFANA_ADMIN_PASSWORD:-}
if [ -z "$GPW" ]; then
  GPW=$(awk '/^## Grafana/{f=1} f && /^admin \/ /{print $3; exit}' higress-console-admin.local.md || true)
fi
[ -n "$GPW" ] || { echo "нет пароля Grafana: GRAFANA_ADMIN_PASSWORD или раздел «Grafana» в .local.md" >&2; exit 1; }

CURL=(curl -sS --resolve "$HOST:443:$IP" --connect-timeout 10)
COOKIE=$(mktemp -t hgc.XXXXXX); trap 'rm -f "$COOKIE" "$COOKIE.json"' EXIT

code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -c "$COOKIE" \
  -X POST "https://$HOST/session/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PW\"}")
[ "$code" = "201" ] || { echo "login: HTTP $code" >&2; exit 1; }
echo "login ok"

# /grafana/** проксируется только с сессией консоли, права даёт Basic-заголовок → нужны оба.
AUTH=(-b "$COOKIE" -u "admin:$GPW")
DS_UID=$("${CURL[@]}" "${AUTH[@]}" "https://$HOST/grafana/api/datasources" |
  python3 -c 'import sys,json;print(next(d["uid"] for d in json.load(sys.stdin) if d["type"]=="prometheus"))')
echo "prometheus datasource uid: $DS_UID"

python3 - "$FILE" "$DS_UID" "$COOKIE.json" <<'PY'
import json, sys
src, uid, out = sys.argv[1], sys.argv[2], sys.argv[3]
raw = open(src, encoding="utf-8").read().replace("__PROM_UID__", uid)
json.dump(json.loads(raw), open(out, "w", encoding="utf-8"), ensure_ascii=False)
PY

resp=$("${CURL[@]}" "${AUTH[@]}" -X POST "https://$HOST/grafana/api/dashboards/db" \
  -H 'Content-Type: application/json' --data-binary @"$COOKIE.json")
echo "$resp" | python3 -c 'import sys,json
j=json.load(sys.stdin)
print("dashboard:", j.get("slug") or j.get("message") or j, "version", j.get("version"))'
