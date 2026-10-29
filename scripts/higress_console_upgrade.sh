#!/usr/bin/env bash
# Апгрейд консоли Higress (release `higress-console`, chart higress.io/higress-console) с
# сохранением o11y-стека — единственный правильный путь обновления этого релиза.
#
#   ./scripts/higress_console_upgrade.sh --check    # только preflight (helm --dry-run=server)
#   ./scripts/higress_console_upgrade.sh            # preflight → апгрейд → догон FS-resize
#   ./scripts/higress_console_upgrade.sh --set podEnvs.HIGRESS_CONSOLE_DASHBOARD_PASSWORD=<pw>
#                                                   # ротация пароля Grafana: --set пробрасывается в helm
#
# Почему скрипт, а не «helm upgrade руками» (инциденты 2026-10-28/29):
#  - `helm upgrade` без `--reuse-values` берёт ДЕФОЛТЫ чарта: `global.o11y.enabled` станет false и
#    Prometheus/Grafana/Loki будут удалены, а `podEnvs.HIGRESS_CONSOLE_DASHBOARD_*` (пароль Grafana,
#    которым ходит консоль) пропадут → витрина /dashboard отдаёт 500;
#  - дефолтные размеры PVC меньше живых → API запрещает уменьшать том, релиз уходит в `failed`
#    (ревизия 3 умерла ещё и на SSA-конфликте `.data.grafana.ini` — preflight ловит его бесплатно);
#  - расширение PVC в Longhorn завершается только после рестарта пода (`FileSystemResizeRequired`),
#    иначе `status.capacity` остаётся старым и Prometheus продолжает писать в полный том.
#
# Размеры томов и прочие значения — `ansible/values-higress-console.yaml` (секретов там нет).
set -euo pipefail
cd "$(dirname "$0")/.."

NS=higress-system
RELEASE=higress-console
CHART=higress.io/higress-console
VERSION=${HGC_CHART_VERSION:-2.1.9}
VALUES=ansible/values-higress-console.yaml
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"
H="helm --kube-context $CTX"

MODE=upgrade
extra=""
for a in "$@"; do
  case "$a" in
    --check|--dry-run) MODE=check ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    --*) extra="$extra $a" ;;
    *)
      case "$a" in
        *=*) extra="$extra $a" ;;   # значение для предыдущего --set
        *) echo "неизвестный аргумент: $a (--check | [--set key=value …])" >&2; exit 2 ;;
      esac ;;
  esac
done

[ -f "$VALUES" ] || { echo "нет $VALUES" >&2; exit 1; }

upgrade_args="$RELEASE $CHART --version $VERSION -n $NS --reuse-values -f $VALUES"
[ -n "$extra" ] && upgrade_args="$upgrade_args$extra"

# --- 1. preflight: тот же рендер сервер-сайдом, без применения -------------------------------
echo "== preflight: helm upgrade --dry-run=server"
# shellcheck disable=SC2086
if ! $H upgrade $upgrade_args --dry-run=server > /tmp/hgc-preflight.yaml 2> /tmp/hgc-preflight.err; then
  echo "PREFLIGHT FAILED — апгрейд не запускаю. Причина:" >&2
  sed -n '1,10p' /tmp/hgc-preflight.err >&2
  echo "Подсказки: SSA-конфликт '.data.grafana.ini' → kubectl -n $NS delete cm ${RELEASE}-grafana;" >&2
  echo "            отказ на сжатии PVC → в $VALUES указан размер меньше живого тома." >&2
  exit 1
fi
echo "   ok: $(grep -c '^kind:' /tmp/hgc-preflight.yaml) объектов, o11y: $(grep -cE 'name: higress-console-(prometheus|grafana|loki)$' /tmp/hgc-preflight.yaml) упоминаний prometheus/grafana/loki"
for must in higress-console-prometheus higress-console-grafana higress-console-loki; do
  grep -q "name: $must\$" /tmp/hgc-preflight.yaml || { echo "preflight без $must — стоп (o11y выключился бы)" >&2; exit 1; }
done

if [ "$MODE" = check ]; then
  echo "== только проверка, изменений не вносил"
  exit 0
fi

# --- 2. апгрейд ------------------------------------------------------------------------------
# ВАЖНО: три пода o11y держат RWO-том Longhorn (prometheus/grafana/loki пишут в свои PVC), а
# Deployment'ы чарта объявлены без `strategy`, т.е. RollingUpdate: при смене шаблона (resources,
# env) новый под встаёт рядом со старым, не может взять flock на /prometheus/lock и уходит в
# Error/CrashLoop (наблюдалось 2026-10-29). Поэтому гасим старые поды ДО апгрейда и поднимаем
# после — это и есть Recreate, которого чарт не умеет.
scale_state=""
for c in prometheus loki grafana; do
  d="$RELEASE-$c"
  n=$($K -n "$NS" get deploy "$d" -o jsonpath='{.spec.replicas}' 2>/dev/null || true)
  [ -n "$n" ] || continue
  $K -n "$NS" scale "deploy/$d" --replicas=0 >/dev/null && echo "   остановлен $d (было реплик: $n)"
  scale_state="$scale_state $d:$n"
done
for c in prometheus loki grafana; do
  d="$RELEASE-$c"
  i=0
  while [ "$i" -lt 24 ]; do
    left=$($K -n "$NS" get pods -l "app=$d" --no-headers 2>/dev/null | wc -l | tr -d ' ')
    [ "$left" = "0" ] && break
    sleep 5; i=$((i+1))
  done
  [ "${left:-0}" = "0" ] || echo "   внимание: у $d остались поды ($left) — том может быть занят" >&2
done

echo "== helm upgrade"
# shellcheck disable=SC2086
$H upgrade $upgrade_args | sed -n 's/^REVISION: /   revision: /p; s/^STATUS: /   status: /p'

for item in $scale_state; do
  d=${item%%:*}; n=${item##*:}
  $K -n "$NS" scale "deploy/$d" --replicas="$n" >/dev/null && echo "   поднят $d (реплик: $n)"
done

# --- 3. догон FS-resize: том расширен, но ФС внутри — только после рестарта пода ---------------
# после scale-back поды монтируются заново и обычно дожимают ФС сами — даём им до 120 с
for c in prometheus loki grafana; do
  pvc="$RELEASE-$c"
  $K -n "$NS" get pvc "$pvc" >/dev/null 2>&1 || continue
  want=$($K -n "$NS" get pvc "$pvc" -o jsonpath='{.spec.resources.requests.storage}')
  i=0
  while [ "$i" -lt 24 ]; do
    have=$($K -n "$NS" get pvc "$pvc" -o jsonpath='{.status.capacity.storage}')
    [ "$want" = "$have" ] && break
    sleep 5; i=$((i+1))
  done
done

restarted=""
for c in prometheus loki grafana; do
  deploy="$RELEASE-$c"
  $K -n "$NS" get deploy "$deploy" >/dev/null 2>&1 || continue
  pvc=$($K -n "$NS" get deploy "$deploy" -o jsonpath='{.spec.template.spec.volumes[?(@.persistentVolumeClaim)].persistentVolumeClaim.claimName}' 2>/dev/null || true)
  [ -n "$pvc" ] || continue
  want=$($K -n "$NS" get pvc "$pvc" -o jsonpath='{.spec.resources.requests.storage}')
  have=$($K -n "$NS" get pvc "$pvc" -o jsonpath='{.status.capacity.storage}')
  need=$($K -n "$NS" get pvc "$pvc" -o jsonpath='{range .status.conditions[?(@.type=="FileSystemResizePending")]}yes{end}')
  if [ "$want" != "$have" ] || [ -n "$need" ]; then
    echo "   $pvc: request=$want capacity=$have → рестарт $deploy досжимает ФС"
    $K -n "$NS" rollout restart "deploy/$deploy" >/dev/null
    restarted="$restarted $deploy"
  fi
done

for d in $restarted; do $K -n "$NS" rollout status "deploy/$d" --timeout=180s >/dev/null && echo "   $d: rollout ok"; done

# --- 4. итог ---------------------------------------------------------------------------------
echo "== состояние"
$K -n "$NS" get pvc --no-headers -o custom-columns='NAME:.metadata.name,REQ:.spec.resources.requests.storage,CAP:.status.capacity.storage' \
  2>/dev/null | grep -E "higress-console-(prometheus|loki|grafana)" | sed 's/^/   /' || true
$K -n "$NS" get pods --no-headers 2>/dev/null \
  | grep -E "higress-console-(prometheus|loki|grafana)-" | awk '{print "   "$1, $2, $3, "restarts="$4}' || true
echo "== готово (значения — $VALUES; секреты релиза сохранены --reuse-values)"
