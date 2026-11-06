#!/usr/bin/env bash
# H2 — Secret `her-secrets` (ns her) из приватных файлов репозитория.
#
# Источники (оба в .gitignore, значения НЕ печатаются):
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
cd "$(dirname "$0")/.."

NS=her
SECRET=her-secrets
SRC=her.local.md
LLM=llm.local.md
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/demo-ai-lab.conf}"

val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$2"; }
# llm.local.md исторически в формате `ключ= значение`
val_eq() { awk -F'= ' -v k="$1" '$1==k{print $2; exit}' "$2"; }

put_if_absent() { # put_if_absent <файл> <ключ> <значение>
  [ -n "$(val "$2" "$1")" ] && return 0
  printf '%s: %s\n' "$2" "$3" >> "$1"
}

if [ "${1:-}" = "--init" ]; then
  [ -f "$SRC" ] || { echo "нет $SRC — он создаётся вместе со спекой" >&2; exit 1; }
  umask 077
  # Панель на не-loopback bind не стартует без провайдера входа: до заведения SSO-клиента
  # держим пароль (снимается в H6). Пароль — 24 символа без спецсимволов, чтобы не ломать env.
  put_if_absent "$SRC" dashboard_basic_username demo
  put_if_absent "$SRC" dashboard_basic_password "$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  put_if_absent "$SRC" dashboard_basic_secret "$(openssl rand -base64 32 | tr -d '\n')"
  chmod 600 "$SRC"
  echo "$SRC: значения на месте (0600). Значения не печатались." >&2
  exit 0
fi

[ -f "$SRC" ] || { echo "нет $SRC" >&2; exit 1; }
[ -f "$LLM" ] || { echo "нет $LLM" >&2; exit 1; }

llm_key=$(val_eq svc_api_key "$LLM")
basic_user=$(val dashboard_basic_username "$SRC")
basic_pass=$(val dashboard_basic_password "$SRC")
basic_secret=$(val dashboard_basic_secret "$SRC")
gpustack_key=$(val gpustack_key "$SRC")

for pair in "svc_api_key(llm.local.md):$llm_key" "dashboard_basic_username:$basic_user" \
            "dashboard_basic_password:$basic_pass" "dashboard_basic_secret:$basic_secret"; do
  name=${pair%%:*}; value=${pair#*:}
  case "$value" in
    ""|TBD) echo "пустое значение: $name (./scripts/her_secrets.sh --init)" >&2; exit 1 ;;
  esac
done

kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null

args=(
  --from-literal=HER_LLM_SVC_KEY="$llm_key"
  --from-literal=HERMES_DASHBOARD_BASIC_AUTH_USERNAME="$basic_user"
  --from-literal=HERMES_DASHBOARD_BASIC_AUTH_PASSWORD="$basic_pass"
  --from-literal=HERMES_DASHBOARD_BASIC_AUTH_SECRET="$basic_secret"
)
# Ключ GPUStack появится после заведения `her-27b` (H3) — до тех пор Secret живёт без него.
case "$gpustack_key" in
  ""|TBD) echo "HER_GPUSTACK_KEY пропущен: gpustack_key ещё TBD (H3)" >&2 ;;
  *)      args+=(--from-literal=HER_GPUSTACK_KEY="$gpustack_key") ;;
esac

kubectl -n "$NS" create secret generic "$SECRET" "${args[@]}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "Secret $NS/$SECRET обновлён. Ключи:"
kubectl -n "$NS" get secret "$SECRET" -o go-template='{{range $k,$v := .data}}  {{$k}}{{"\n"}}{{end}}'
