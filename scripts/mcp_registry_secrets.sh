#!/usr/bin/env bash
# M1 — Secret'ы каталога MCP-серверов в ns `mcp-registry` из приватного файла репозитория.
#
# Источник: mcp-registry.local.md (корень репо, gitignored, 0600). Значения НЕ печатаются:
# скрипт идемпотентен (`create --dry-run=client | apply`) и выводит только имена объектов.
#
#   ./scripts/mcp_registry_secrets.sh --init   # один раз: сгенерировать файл (openssl rand)
#   ./scripts/mcp_registry_secrets.sh          # создать/обновить Secret'ы из файла
#
# Запускать ДО первого sync'а Argo: иначе под висит в CreateContainerConfigError
# («реестр не стартует», а не «сломан Argo»). Повторять после ротации пароля или JWT seed.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=mcp-registry
SRC=mcp-registry.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

# --- --init: файл с секретами создаётся один раз и больше не перезаписывается -------------
if [ "${1:-}" = "--init" ]; then
  [ -f "$SRC" ] && { echo "$SRC уже есть — не перезаписываю" >&2; exit 1; }
  umask 077
  # jwt-private-key — это seed Ed25519 (32 байта в hex), НЕ PEM: с PEM реестр падает на подписи JWT
  {
    echo "# MCP Registry — приватные значения (в git не попадает: *.local.md в .gitignore)"
    echo "db-name: mcp-registry"
    echo "db-username: mcpregistry"
    echo "db-password: $(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)"
    echo "jwt-private-key: $(openssl rand -hex 32)"
  } > "$SRC"
  chmod 600 "$SRC"
  echo "$SRC создан (0600). Значения не печатались." >&2
  exit 0
fi

[ -f "$SRC" ] || { echo "нет $SRC — создайте его: ./scripts/mcp_registry_secrets.sh --init" >&2; exit 1; }

# формат файла: `ключ: значение`; пустые строки и комментарии пропускаем
val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }

db_name=$(val db-name)
db_user=$(val db-username)
db_pass=$(val db-password)
jwt_seed=$(val jwt-private-key)

for n in db_name db_user db_pass jwt_seed; do
  if [ -z "${!n}" ]; then echo "в $SRC пустое поле: $n" >&2; exit 1; fi
done

case "$jwt_seed" in
  *"PRIVATE KEY"*) echo "jwt-private-key выглядит как PEM — нужен hex-seed (openssl rand -hex 32)" >&2; exit 1 ;;
esac

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS" >/dev/null

# url собирается здесь же: реестр читает один DSN, пароль в манифест не попадает
url="postgres://${db_user}:${db_pass}@postgres.${NS}.svc:5432/${db_name}?sslmode=disable"

$K -n "$NS" create secret generic mcp-registry-db \
  --from-literal=db-name="$db_name" \
  --from-literal=db-username="$db_user" \
  --from-literal=db-password="$db_pass" \
  --from-literal=url="$url" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

$K -n "$NS" create secret generic mcp-registry \
  --from-literal=jwt-private-key="$jwt_seed" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

unset db_pass url jwt_seed
echo "ns/$NS: secret'ы mcp-registry-db и mcp-registry применены (значения не выводились)"
