#!/usr/bin/env bash
# Секреты GPUStack (ns `gpustack`) — вне Argo CD (ADR-0011).
#
# Зачем скрипт: три Secret'а не могут рендериться чартом под Argo —
#   registration-token  (GPUSTACK_TOKEN)             — шаблон чарта: lookup+randAlphaNum;
#   gpustack-jwt-key    (GPUSTACK_JWT_SECRET_KEY)    — то же: новое значение на каждом рендере;
#   gpustack-oidc       (GPUSTACK_OIDC_CLIENT_SECRET) — секрет клиента Keycloak `gps`, в git нельзя.
# Шаблоны первых двух удалены из рендера kustomize-патчем (`$patch: delete`), поэтому Argo их не
# создаёт, не обновляет и не prune'ит — создаёт этот скрипт. Порядок: секреты → sync Argo.
#
# Без флага — только проверка (ничего не пишет). `--init` — создать недостающие Secret'ы
# (значения генерируются) и применить `gpustack-oidc` из источника. Существующие
# registration-token/jwt-key не трогаются: ротация — только явным удалением (см. «Ротация»).
#
# OIDC-секрет берётся из окружения GPUSTACK_OIDC_CLIENT_SECRET, иначе из приватного файла
# keycloak-clients.local.md (поле gps-client-secret, gitignored). Без источника `--init` падает:
# без SSO сервер поднимется, но вход в UI не работает.
#
# Ротация:
#   registration-token: удалить Secret и перезапустить воркеры (токен читается при старте):
#     kubectl -n gpustack delete secret registration-token && scripts/gpustack_secrets.sh --init
#     kubectl -n gpustack rollout restart ds/gpustack-worker ds/gpustack-worker-nvidia
#   gpustack-jwt-key: удалить Secret + перезапустить sts/gpustack-server (выданные ключи API
#     перестанут проверяться — делать только осознанно).
set -euo pipefail
cd "$(dirname "$0")/.."

NS=gpustack
CTX=${KUBE_CONTEXT:-demo-ai-lab}
SRC=keycloak-clients.local.md
K="kubectl --context $CTX"

# has_key <secret> <key> — есть ли ключ в Secret (значение не печатается)
has_key() {
  $K -n "$NS" get secret "$1" -o "jsonpath={.data.$2}" 2>/dev/null | grep -q .
}

ensure_rand() { # <secret> <key>
  local name=$1 key=$2
  if has_key "$name" "$key"; then
    echo "== Secret/$name: уже есть, не трогаю"
    return 0
  fi
  $K -n "$NS" create secret generic "$name" \
    --from-literal="$key=$(openssl rand -hex 32)" \
    --dry-run=client -o yaml | $K apply -f - >/dev/null
  echo "== Secret/$name: создан"
}

oidc_secret=${GPUSTACK_OIDC_CLIENT_SECRET:-}
if [ -z "$oidc_secret" ] && [ -f "$SRC" ]; then
  oidc_secret=$(awk -F': ' '$1=="gps-client-secret"{print $2; exit}' "$SRC")
fi

if [ "${1:-}" = "--init" ]; then
  $K get ns "$NS" -o name >/dev/null 2>&1 || $K create ns "$NS" >/dev/null
  ensure_rand registration-token GPUSTACK_TOKEN
  ensure_rand gpustack-jwt-key GPUSTACK_JWT_SECRET_KEY
  if [ -n "$oidc_secret" ]; then
    $K -n "$NS" create secret generic gpustack-oidc \
      --from-literal=GPUSTACK_OIDC_CLIENT_SECRET="$oidc_secret" \
      --dry-run=client -o yaml | $K apply -f - >/dev/null
    echo "== Secret/gpustack-oidc: применён из источника"
  elif has_key gpustack-oidc GPUSTACK_OIDC_CLIENT_SECRET; then
    echo "== Secret/gpustack-oidc: источник не найден, оставляю текущий"
  else
    echo "нет gpustack-oidc и нет источника (env GPUSTACK_OIDC_CLIENT_SECRET / $SRC)" >&2
    exit 1
  fi
fi

# Проверка (и для --init тоже): без любого из трёх сервер/воркеры поднимутся не полностью.
missing=0
for pair in registration-token:GPUSTACK_TOKEN gpustack-jwt-key:GPUSTACK_JWT_SECRET_KEY gpustack-oidc:GPUSTACK_OIDC_CLIENT_SECRET; do
  name=${pair%%:*}; key=${pair##*:}
  if has_key "$name" "$key"; then
    echo "== OK Secret/$name"
  else
    echo "== НЕТ Secret/$name (ключ $key) — запустите --init" >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1
