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
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=gpustack
SRC=keycloak-clients.local.md

oidc_secret=${GPUSTACK_OIDC_CLIENT_SECRET:-}
if [ -z "$oidc_secret" ] && [ -f "$SRC" ]; then
  oidc_secret=$(sc_val gps-client-secret "$SRC")
fi

if [ "${1:-}" = "--init" ]; then
  sc_ensure_ns "$NS"
  sc_ensure_rand "$NS" registration-token GPUSTACK_TOKEN
  sc_ensure_rand "$NS" gpustack-jwt-key GPUSTACK_JWT_SECRET_KEY
  if [ -n "$oidc_secret" ]; then
    sc_apply "$NS" gpustack-oidc "GPUSTACK_OIDC_CLIENT_SECRET=$oidc_secret"
    echo "== Secret/gpustack-oidc: применён из источника"
  elif sc_secret_has "$NS" gpustack-oidc GPUSTACK_OIDC_CLIENT_SECRET; then
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
  if sc_secret_has "$NS" "$name" "$key"; then
    echo "== OK Secret/$name"
  else
    echo "== НЕТ Secret/$name (ключ $key) — запустите --init" >&2
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1
