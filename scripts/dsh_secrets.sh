#!/usr/bin/env bash
# W1 — Secret'ы ns dsh до первого синка (по образцу scripts/her_secrets.sh).
#
#   ./scripts/dsh_secrets.sh --init   # один раз: завести dsh.local.md с cookie_secret
#   ./scripts/dsh_secrets.sh          # создать/обновить Secret'ы, напечатать только имена ключей
#
# Источники (все gitignored):
#   dsh.local.md             — cookie_secret (oauth2-proxy), gpustack_key (ключ GPUStack `dsh`)
#   keycloak-clients.local.md — dsh-client-secret (клиент `dsh`, SSO-гейт)
#   llm.local.md             — svc_api_key (статический ключ llm-svc., общий для стенда)
#   kuvasz.local.md          — admin-mcp-api-key (X-API-KEY для MCP Kuvasz)
#   her.local.md             — github_pat (fine-grained read-only PAT для MCP github; необязателен)
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_kubeconfig

NS=dsh
SRC=dsh.local.md
KC=keycloak-clients.local.md
LLM=llm.local.md
KUV=kuvasz.local.md
HER=her.local.md

if [ "${1:-}" = "--init" ]; then
  umask 077
  [ -f "$SRC" ] || : > "$SRC"
  if [ -z "$(sc_val cookie_secret "$SRC")" ]; then
    # oauth2-proxy требует ровно 16/24/32 байта: `openssl rand -base64 32` даёт 44 ASCII-символа
    # и падает `cookie_secret must be 16, 24, or 32 bytes` (проверено W1). Берём 32 символа без
    # спецсимволов, чтобы значение жило и в env, и в cookie без экранирования.
    printf 'cookie_secret: %s\n' "$(sc_rand_safe 48 32)" >> "$SRC"
  fi
  sc_seal "$SRC"
  echo "$SRC: значения на месте (0600). Значения не печатались." >&2
  echo "осталось: gpustack_key — POST /v2/api-keys под admin, allowed_model_names: [Qwen3.8-27B-UD]" >&2
  exit 0
fi

for f in "$SRC" "$KC" "$LLM" "$KUV"; do
  [ -f "$f" ] || { echo "нет $f (для $SRC — ./scripts/dsh_secrets.sh --init)" >&2; exit 1; }
done

client_secret=$(sc_val dsh-client-secret "$KC")
cookie_secret=$(sc_val cookie_secret "$SRC")
gpustack_key=$(sc_val gpustack_key "$SRC")
llm_key=$(sc_val_eq svc_api_key "$LLM")   # llm.local.md исторически в формате `ключ= значение`
kuvasz_key=$(sc_val admin-mcp-api-key "$KUV")

sc_need dsh-client-secret "$client_secret"
sc_need cookie_secret "$cookie_secret"
sc_need gpustack_key "$gpustack_key"
sc_need svc_api_key "$llm_key"

apply_secret() { # apply_secret <имя> <ключ=значение>... — значение в вывод не попадает
  local name=$1
  shift
  sc_apply "$NS" "$name" "$@"
  echo "Secret $NS/$name: $# ключ(ей)" >&2
}

apply_secret dsh-oidc \
  "OAUTH2_PROXY_CLIENT_SECRET=$client_secret" \
  "OAUTH2_PROXY_COOKIE_SECRET=$cookie_secret"
apply_secret dsh-models \
  "GPUSTACK_API_KEY=$gpustack_key" \
  "LLM_SVC_API_KEY=$llm_key"
mcp_args=("KUVASZ_MCP_KEY=$kuvasz_key")
# GitHub PAT — необязательный: без него MCP `github` отвечает 401, остальное работает.
# В кластер идёт двумя ключами: GITHUB_PAT (сырой) и GITHUB_AUTH (`Bearer …`) — оверлей dsh
# вычисляет только простое выражение `!!js process.env.GITHUB_AUTH`, конкатенацию не умеет.
github_pat=$(sc_val github_pat "$HER" 2>/dev/null || true)
case "$github_pat" in
  ""|TBD) echo "GITHUB_PAT/GITHUB_AUTH пропущены: github_pat в $HER не заведён (hermes-spec §7.1)" >&2 ;;
  *)      mcp_args+=("GITHUB_PAT=$github_pat" "GITHUB_AUTH=Bearer $github_pat") ;;
esac
apply_secret dsh-mcp "${mcp_args[@]}"

echo "готово: Secret'ы dsh-oidc/dsh-models/dsh-mcp (dsh-oidc — envFrom для oauth2-proxy)" >&2
