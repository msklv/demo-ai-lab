#!/usr/bin/env bash
# Basic Auth для Longhorn UI (`lng.demo-ai-lab.ru`) на Higress.
#
# Решение владельца 2026-11-04 (`architecture/specs/external-access-spec.md` E9.3): сетевой
# allowlist остаётся первым гейтом, логин — вторым. Плагин `basic-auth` (исходники Higress
# `v2.1.9`, отдаётся из тома `wasm-store`), шаблон — `gitops/infra-apps/infra/templates/
# longhorn-ui-basic-auth.yaml.tpl`.
#
# Почему скрипт, а не Argo: `credential` живёт инлайном в `WasmPlugin.spec.defaultConfig`
# (`secretRef` в Higress нет), поэтому объект `longhorn-ui-basic-auth` создаётся здесь — как
# `llm-jwt-auth`/`llm-key-auth` в `gitops/apps/llm/`. В git только шаблон.
#
# Хранилище кредов: `lng-admin.local.md` (gitignored, `*.local.md`).
#
# Использование:
#   scripts/longhorn_ui_auth.sh              # создать креды, если их нет, отрендерить и применить
#   scripts/longhorn_ui_auth.sh --dry-run     # только отрендерить (пароль замаскирован) в stdout
#   scripts/longhorn_ui_auth.sh --rotate      # новый пароль (старый перестаёт работать сразу)
#   scripts/longhorn_ui_auth.sh --check       # проверить: из LAN `lng.` → 401, с кредами → 200
#
# Зависимости: kubectl, curl; context по умолчанию `demo-ai-lab` (env DEMO_KUBE_CONTEXT).
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
TPL="$REPO/gitops/infra-apps/infra/templates/longhorn-ui-basic-auth.yaml.tpl"
STORE="$REPO/lng-admin.local.md"
HOST="lng.demo-ai-lab.ru"
VIP="192.168.10.230"
CTX="${DEMO_KUBE_CONTEXT:-demo-ai-lab}"
KUBECTL=(kubectl --context "$CTX")

MODE="apply"
case "${1:-}" in
  --dry-run) MODE="dry" ;;
  --rotate)  MODE="rotate" ;;
  --check)   MODE="check" ;;
  "")        ;;
  *) echo "usage: $0 [--dry-run|--rotate|--check]" >&2; exit 2 ;;
esac

say() { printf '%s\n' "$*" >&2; }

read_cred() { # read_cred <key>
  [ -f "$STORE" ] || return 0
  local line value
  line=$(grep -m1 "^$1:" "$STORE" 2>/dev/null || true)
  [ -n "$line" ] || return 0
  value=${line#*:}
  value=${value#"${value%%[! ]*}"}          # снять ведущие пробелы (bash 3.2-совместимо)
  printf '%s' "$value" | tr -d '«»"'"'"'\r'
}

# 32 hex-символа: без ':' и кавычек — нечего экранировать в YAML и в `credential`.
new_password() { openssl rand -hex 16; }

LOGIN=$(read_cred login)
PASS=$(read_cred password)

if [ "$MODE" = "check" ]; then
  rc=0
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --resolve "$HOST:443:$VIP" "https://$HOST/" || true)
  say "без кредов: ${code:-n/a} (ожидается 401)"
  [ "$code" = "401" ] || rc=1
  if [ -n "$LOGIN" ] && [ -n "$PASS" ]; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -u "$LOGIN:$PASS" --resolve "$HOST:443:$VIP" "https://$HOST/" || true)
    say "с кредами: ${code:-n/a} (ожидается 200)"
    [ "$code" = "200" ] || rc=1
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 -u "$LOGIN:$PASS" --resolve "$HOST:443:$VIP" "https://$HOST/v1/volumes" || true)
    say "API /v1/volumes с кредами: ${code:-n/a} (ожидается 200)"
    [ "$code" = "200" ] || rc=1
  else
    say "FAIL: в $STORE нет login/password — запустить $0 без флагов"
    rc=1
  fi
  exit $rc
fi

# --- 1. креды ----------------------------------------------------------------
if [ "$MODE" = "rotate" ] || [ -z "$LOGIN" ] || [ -z "$PASS" ]; then
  [ -n "$LOGIN" ] || LOGIN="admin"
  PASS=$(new_password)
  umask 077
  cat > "$STORE" <<EOF
# Basic Auth служебных UI на Higress — Longhorn UI (\`lng.demo-ai-lab.ru\`).
# Живёт вне git (\`*.local.md\`). Кто читает: \`scripts/longhorn_ui_auth.sh\` (рендер WasmPlugin
# \`longhorn-ui-basic-auth\`), \`scripts/k8s_health.py\` (проба 401 без кредов).
# Смена пароля: \`scripts/longhorn_ui_auth.sh --rotate\`.
login: $LOGIN
password: $PASS
EOF
  chmod 600 "$STORE"
  say "ok: креды записаны в lng-admin.local.md (пароль не печатается)"
else
  say "ok: креды взяты из lng-admin.local.md"
fi

# --- 2. рендер ---------------------------------------------------------------
CRED="$LOGIN:$PASS"
case "$CRED" in *"'"*|*'"'*|*'\'*) echo "FAIL: логин/пароль содержат кавычки или бэкслеш" >&2; exit 1;; esac
RENDERED=$(mktemp)
sed "s|<<CREDENTIAL>>|'$CRED'|" "$TPL" > "$RENDERED"

if [ "$MODE" = "dry" ]; then
  sed "s|'$LOGIN:[^']*'|'$LOGIN:«redacted»'|" "$RENDERED"
  rm -f "$RENDERED"
  exit 0
fi

# --- 3. применение -----------------------------------------------------------
"${KUBECTL[@]}" apply -f "$RENDERED" >/dev/null
rm -f "$RENDERED"
say "ok: WasmPlugin longhorn-ui-basic-auth применён"

# --- 4. самопроверка ---------------------------------------------------------
"$0" --check
