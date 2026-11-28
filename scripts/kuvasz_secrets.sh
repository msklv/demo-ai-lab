#!/usr/bin/env bash
# M0 — Секреты Kuvasz в ns `monitoring` из приватного файла репозитория (ADR-0009).
#
# Источник: kuvasz.local.md (gitignored, 0600).
#
# --init: разовая установка — сгенерировать значения для полей change_me/пустых
# (ADR-0009: «значения заполняются при установке»). Уже заполненные поля не трогаются.
#
# Запускать ДО первого sync'а Argo (иначе под Kuvasz в CrashLoop на подключении к БД)
# и повторно после каждой ротации ключей.
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=monitoring
SRC=kuvasz.local.md

sc_need_file "$SRC" "секреты не из чего собрать"

if [ "${1:-}" = "--init" ]; then
  init_field() { # пустое или change_me — сгенерировать; заполненное не трогать
    local v
    v=$(sc_val "$1" "$SRC")
    if [ -z "$v" ] || [ "$v" = "change_me" ]; then
      sed -i.bak "s|^$1: .*|$1: $(sc_rand_b64 24)|" "$SRC"
      rm -f "$SRC.bak"
    fi
  }
  init_field admin-password
  init_field admin-api-key
  init_field admin-mcp-api-key
  init_field db-password
  sc_seal "$SRC"
  echo "$SRC: сгенерированы значения для пустых полей (значения не выводились)"
fi

adm_user=$(sc_val admin-user "$SRC")
adm_pass=$(sc_val admin-password "$SRC")
api_key=$(sc_val admin-api-key "$SRC")
mcp_key=$(sc_val admin-mcp-api-key "$SRC")
db_name=$(sc_val db-name "$SRC")
db_user=$(sc_val db-username "$SRC")
db_pass=$(sc_val db-password "$SRC")

for n in adm_user adm_pass api_key mcp_key db_name db_user db_pass; do
  sc_need "$n" "${!n}" "в $SRC пустое или change_me поле: %s — сначала запустите --init"
done

sc_ensure_ns "$NS" --echo-create
sc_apply "$NS" kuvasz-db \
  "db-name=$db_name" "db-username=$db_user" "db-password=$db_pass"
sc_apply "$NS" kuvasz-api-key \
  "admin-user=$adm_user" "admin-password=$adm_pass" \
  "admin-api-key=$api_key" "admin-mcp-api-key=$mcp_key"

unset adm_pass api_key mcp_key db_pass
echo "ns/$NS: secret'ы kuvasz-db и kuvasz-api-key применены (значения не выводились)"
