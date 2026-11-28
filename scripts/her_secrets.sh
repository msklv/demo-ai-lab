#!/usr/bin/env bash
# H2 — Secret `her-secrets` (ns her) из приватных файлов репозитория.
#
# Источники (оба gitignored):
#   llm.local.md  — `svc_api_key`: статический ключ llm-svc. (Bearer → consumer llm-svc-bearer)
#   her.local.md  — пароль/секрет переходного входа в панель (basic auth) и, позже, ключ GPUStack
#
#   ./scripts/her_secrets.sh --init   # один раз: дописать в her.local.md недостающие значения
#   ./scripts/her_secrets.sh          # создать/обновить Secret и вывести только имена ключей
#
# Запускать ДО первого sync'а: без Secret под висит в CreateContainerConfigError.
# `llm_svc_key` заводится отдельным потребителем `llm-svc-her` (спека §3) — до его появления берём
# существующий ключ `llm-svc.`, чтобы не блокировать деплой.
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_kubeconfig

NS=her
SECRET=her-secrets
SRC=her.local.md
LLM=llm.local.md

put_if_absent() { # put_if_absent <файл> <ключ> <значение> — уже есть — не трогаем
  [ -n "$(sc_val "$2" "$1")" ] && return 0
  printf '%s: %s\n' "$2" "$3" >> "$1"
}

if [ "${1:-}" = "--init" ]; then
  sc_need_file "$SRC" "он создаётся вместе со спекой"
  umask 077
  # Панель на не-loopback bind не стартует без провайдера входа: до заведения SSO-клиента
  # держим пароль (снимается в H6). Пароль — 24 символа без спецсимволов, чтобы не ломать env.
  put_if_absent "$SRC" dashboard_basic_username demo
  put_if_absent "$SRC" dashboard_basic_password "$(sc_rand_safe 24 24)"
  put_if_absent "$SRC" dashboard_basic_secret "$(sc_rand_b64 32)"
  sc_seal "$SRC"
  echo "$SRC: значения на месте (0600). Значения не печатались." >&2
  exit 0
fi

sc_need_file "$SRC"
sc_need_file "$LLM"

llm_key=$(sc_val_eq svc_api_key "$LLM")
basic_user=$(sc_val dashboard_basic_username "$SRC")
basic_pass=$(sc_val dashboard_basic_password "$SRC")
basic_secret=$(sc_val dashboard_basic_secret "$SRC")
gpustack_key=$(sc_val gpustack_key "$SRC")
github_pat=$(sc_val github_pat "$SRC")

sc_need "svc_api_key(llm.local.md)" "$llm_key" 'пустое значение: %s (./scripts/her_secrets.sh --init)'
sc_need dashboard_basic_username "$basic_user" 'пустое значение: %s (./scripts/her_secrets.sh --init)'
sc_need dashboard_basic_password "$basic_pass" 'пустое значение: %s (./scripts/her_secrets.sh --init)'
sc_need dashboard_basic_secret "$basic_secret" 'пустое значение: %s (./scripts/her_secrets.sh --init)'

sc_ensure_ns "$NS"

args=(
  "HER_LLM_SVC_KEY=$llm_key"
  "HERMES_DASHBOARD_BASIC_AUTH_USERNAME=$basic_user"
  "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD=$basic_pass"
  "HERMES_DASHBOARD_BASIC_AUTH_SECRET=$basic_secret"
)
# Ключ GPUStack появится после заведения `her-27b` (H3) — до тех пор Secret живёт без него.
case "$gpustack_key" in
  ""|TBD) echo "HER_GPUSTACK_KEY пропущен: gpustack_key ещё TBD (H3)" >&2 ;;
  *)      args+=("HER_GPUSTACK_KEY=$gpustack_key") ;;
esac
# GitHub PAT (fine-grained, read-only) — нужен только GitHub MCP (§7.1): уходит заголовком
# Authorization per-request, под `github-mcp` секретов не получает. Нет ключа — Secret без него.
case "$github_pat" in
  ""|TBD) echo "HER_GITHUB_PAT пропущен: github_pat ещё не заведён (§7.1)" >&2 ;;
  *)      args+=("HER_GITHUB_PAT=$github_pat") ;;
esac

sc_apply "$NS" "$SECRET" "${args[@]}"

echo "Secret $NS/$SECRET обновлён. Ключи:"
# shellcheck disable=SC2016  # go-template раскрывает kubectl, не bash
sc_k -n "$NS" get secret "$SECRET" -o go-template='{{range $k,$v := .data}}  {{$k}}{{"\n"}}{{end}}'
