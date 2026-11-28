#!/usr/bin/env bash
# M1 — Secret'ы каталога MCP-серверов в ns `mcp-registry` из приватного файла репозитория.
#
# Источник: mcp-registry.local.md (gitignored, 0600).
#
#   ./scripts/mcp_registry_secrets.sh --init   # один раз: сгенерировать файл (openssl rand)
#   ./scripts/mcp_registry_secrets.sh          # создать/обновить Secret'ы из файла
#
# Запускать ДО первого sync'а Argo: иначе под висит в CreateContainerConfigError
# («реестр не стартует», а не «сломан Argo»). Повторять после ротации пароля или JWT seed.
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=mcp-registry
SRC=mcp-registry.local.md

# --- --init: файл с секретами создаётся один раз и больше не перезаписывается -------------
if [ "${1:-}" = "--init" ]; then
  sc_init_guard "$SRC"
  # jwt-private-key — это seed Ed25519 (32 байта в hex), НЕ PEM: с PEM реестр падает на подписи JWT
  {
    echo "# MCP Registry — приватные значения (в git не попадает: *.local.md в .gitignore)"
    echo "db-name: mcp-registry"
    echo "db-username: mcpregistry"
    echo "db-password: $(sc_rand_safe 24 28)"
    echo "jwt-private-key: $(sc_rand_hex 32)"
  } > "$SRC"
  sc_seal "$SRC"
  echo "$SRC создан (0600). Значения не печатались." >&2
  exit 0
fi

sc_need_file "$SRC" "создайте его: ./scripts/mcp_registry_secrets.sh --init"

db_name=$(sc_val db-name "$SRC")
db_user=$(sc_val db-username "$SRC")
db_pass=$(sc_val db-password "$SRC")
jwt_seed=$(sc_val jwt-private-key "$SRC")

for n in db_name db_user db_pass jwt_seed; do
  sc_need_nonempty "$n" "${!n}" "в $SRC пустое поле: %s"
done

case "$jwt_seed" in
  *"PRIVATE KEY"*) echo "jwt-private-key выглядит как PEM — нужен hex-seed (openssl rand -hex 32)" >&2; exit 1 ;;
esac

sc_ensure_ns "$NS"
# url собирается здесь же: реестр читает один DSN; пароль едет значением Secret, в манифест не попадает
url="postgres://${db_user}:${db_pass}@postgres.${NS}.svc:5432/${db_name}?sslmode=disable"

sc_apply "$NS" mcp-registry-db \
  "db-name=$db_name" "db-username=$db_user" "db-password=$db_pass" "url=$url"
sc_apply "$NS" mcp-registry "jwt-private-key=$jwt_seed"

unset db_pass url jwt_seed
echo "ns/$NS: secret'ы mcp-registry-db и mcp-registry применены (значения не выводились)"
