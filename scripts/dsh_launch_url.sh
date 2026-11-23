#!/usr/bin/env bash
# Печатает вход в dsh: публичную страницу `/launch` (её отдаёт сайдкар из launch-URL пода)
# или сырой launch-URL с токеном.
#
# У dsh нет OIDC: вход — токен, который процесс печатает при старте
# (`dsh web: https://dsh.demo-ai-lab.ru/?token=…` → cookie). Токен живёт до перезапуска пода,
# поэтому в git/манифест не кладётся. Страница `/launch` собирает его в поде и отдаётся через
# тот же SSO-гейт `oauth2-proxy` — человеку не нужно каждый раз лезть в `kubectl logs`.
# За корнем без cookie dsh отдаёт `dsh web authentication required; reopen the URL printed by dsh web`
# — это не поломка, а вторые ворота (одна учётка, dsh-spec §0).
#
#   ./scripts/dsh_launch_url.sh          # https://dsh.demo-ai-lab.ru/launch (после SSO)
#   ./scripts/dsh_launch_url.sh --open   # то же + открыть в браузере (macOS)
#   ./scripts/dsh_launch_url.sh --token  # сырой launch-URL с токеном (диагностика)
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/demo-ai-lab.conf}"
NS=dsh
PUBLIC="${DSH_PUBLIC_URL:-https://dsh.demo-ai-lab.ru}"
MODE="${1:-}"

URL="$PUBLIC/launch"

if [ "$MODE" = "--token" ]; then
  URL=$(kubectl -n "$NS" logs deploy/dsh -c dsh --tail=500 2>/dev/null \
        | grep -oE 'https://[^ ]*\?token=[A-Za-z0-9_-]+' | tail -1 || true)
  if [ -z "$URL" ]; then
    echo "launch-URL в логе не найден: kubectl -n $NS logs deploy/dsh | grep 'dsh web:'" >&2
    exit 1
  fi
fi

printf '%s\n' "$URL"
[ "$MODE" = "--open" ] && open "$URL"
exit 0
