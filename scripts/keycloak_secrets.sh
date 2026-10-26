#!/usr/bin/env bash
# K1 — Secret'ы Keycloak в ns `keycloak` из приватных файлов репозитория.
#
# Источник: keycloak-admin.local.md (корень репо, gitignored, 0600). Значения НЕ печатаются:
# скрипт идемпотентен (`--dry-run=client | kubectl apply`) и выводит только статус объектов.
#
# Запускать ДО первого sync'а Argo (иначе под Keycloak в CrashLoop на подключении к БД)
# и повторно после каждой ротации пароля (спека §7.3).
set -euo pipefail
cd "$(dirname "$0")/.."

NS=keycloak
SRC=keycloak-admin.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

[ -f "$SRC" ] || { echo "нет $SRC — секреты не из чего собрать" >&2; exit 1; }

# формат файла: `ключ: значение` (см. спеку §3.1); пустые строки и комментарии пропускаем
val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }

db_name=$(val db-name)
db_user=$(val db-username)
db_pass=$(val db-password)
adm_user=$(val bootstrap-admin-username)
adm_pass=$(val bootstrap-admin-password)

for n in db_name db_user db_pass adm_user adm_pass; do
  if [ -z "${!n}" ]; then echo "в $SRC пустое поле: $n" >&2; exit 1; fi
done

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS"

$K -n "$NS" create secret generic keycloak-db \
  --from-literal=db-name="$db_name" \
  --from-literal=db-username="$db_user" \
  --from-literal=db-password="$db_pass" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

$K -n "$NS" create secret generic keycloak-bootstrap \
  --from-literal=username="$adm_user" \
  --from-literal=password="$adm_pass" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

unset db_pass adm_pass
echo "ns/$NS: secret'ы keycloak-db и keycloak-bootstrap применены (значения не выводились)"
