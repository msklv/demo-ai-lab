#!/usr/bin/env bash
# K1 — Secret'ы Keycloak в ns `keycloak` из приватных файлов репозитория.
#
# Источник: keycloak-admin.local.md (gitignored, 0600).
#
# Запускать ДО первого sync'а Argo (иначе под Keycloak в CrashLoop на подключении к БД)
# и повторно после каждой ротации пароля (спека §7.3).
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=keycloak
SRC=keycloak-admin.local.md

sc_need_file "$SRC" "секреты не из чего собрать"

db_name=$(sc_val db-name "$SRC")
db_user=$(sc_val db-username "$SRC")
db_pass=$(sc_val db-password "$SRC")
adm_user=$(sc_val bootstrap-admin-username "$SRC")
adm_pass=$(sc_val bootstrap-admin-password "$SRC")

for n in db_name db_user db_pass adm_user adm_pass; do
  sc_need_nonempty "$n" "${!n}" "в $SRC пустое поле: %s"
done

sc_ensure_ns "$NS" --echo-create
sc_apply "$NS" keycloak-db \
  "db-name=$db_name" "db-username=$db_user" "db-password=$db_pass"
sc_apply "$NS" keycloak-bootstrap \
  "username=$adm_user" "password=$adm_pass"

unset db_pass adm_pass
echo "ns/$NS: secret'ы keycloak-db и keycloak-bootstrap применены (значения не выводились)"
