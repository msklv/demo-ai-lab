#!/usr/bin/env bash
# M0 — Секреты Kuvasz в ns `monitoring` из приватного файла репозитория (ADR-0009).
#
# Источник: kuvasz.local.md (корень репо, gitignored, 0600). Значения НЕ печатаются:
# скрипт идемпотентен и выводит только статус объектов.
#
# --init: разовая установка — сгенерировать значения для полей change_me/пустых
# (ADR-0009: «значения заполняются при установке»). Уже заполненные поля не трогаются.
#
# Запускать ДО первого sync'а Argo (иначе под Kuvasz в CrashLoop на подключении к БД)
# и повторно после каждой ротации ключей.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=monitoring
SRC=kuvasz.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

[ -f "$SRC" ] || { echo "нет $SRC — секреты не из чего собрать" >&2; exit 1; }

# формат файла: `ключ: значение` (см. раздел «Кластерная инстанс» в $SRC);
# пустые строки и комментарии пропускаем
val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }
set_field() { sed -i.bak "s|^$1: .*|$1: $2|" "$SRC"; rm -f "$SRC.bak"; }

if [ "${1:-}" = "--init" ]; then
  init_field() {
    local k=$1 v
    v=$(val "$1")
    if [ -z "$v" ] || [ "$v" = "change_me" ]; then
      set_field "$k" "$(openssl rand -base64 24 | tr -d '\n')"
    fi
  }
  init_field admin-password
  init_field admin-api-key
  init_field admin-mcp-api-key
  init_field db-password
  chmod 600 "$SRC"
  echo "$SRC: сгенерированы значения для пустых полей (значения не выводились)"
fi

adm_user=$(val admin-user)
adm_pass=$(val admin-password)
api_key=$(val admin-api-key)
mcp_key=$(val admin-mcp-api-key)
db_name=$(val db-name)
db_user=$(val db-username)
db_pass=$(val db-password)

for n in adm_user adm_pass api_key mcp_key db_name db_user db_pass; do
  v=${!n}
  if [ -z "$v" ] || [ "$v" = "change_me" ]; then
    echo "в $SRC пустое или change_me поле: $n — сначала запустите --init" >&2
    exit 1
  fi
done

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS"

$K -n "$NS" create secret generic kuvasz-db \
  --from-literal=db-name="$db_name" \
  --from-literal=db-username="$db_user" \
  --from-literal=db-password="$db_pass" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

$K -n "$NS" create secret generic kuvasz-api-key \
  --from-literal=admin-user="$adm_user" \
  --from-literal=admin-password="$adm_pass" \
  --from-literal=admin-api-key="$api_key" \
  --from-literal=admin-mcp-api-key="$mcp_key" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

unset adm_pass api_key mcp_key db_pass
echo "ns/$NS: secret'ы kuvasz-db и kuvasz-api-key применены (значения не выводились)"
