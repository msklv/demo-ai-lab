#!/usr/bin/env bash
# Y1 — Secret MCP-сервера Yandex Search в ns `ysrch` из приватного файла репозитория.
#
# Источник: yandex-search.local.md (корень репо, gitignored, 0600). Значения НЕ печатаются:
# скрипт идемпотентен (`create --dry-run=client | apply`) и выводит только имена объектов.
#
#   ./scripts/yandex_search_secrets.sh --init   # один раз: создать шаблон файла
#   ./scripts/yandex_search_secrets.sh          # создать/обновить Secret до синка Argo
#
# Ключ берётся в консоли Yandex AI Studio (Search API v2), не генерируется: сервис-аккаунт
# и его Api-Key выдаёт владелец. Скрипт только раскладывает значение в кластер.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=ysrch
SRC=yandex-search.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

if [ "${1:-}" = "--init" ]; then
  [ -f "$SRC" ] && { echo "$SRC уже есть — не перезаписываю" >&2; exit 1; }
  umask 077
  {
    echo "# Yandex Search API для MCP-сервера стенда (не коммитить)"
    echo "# api-key — Api-Key сервис-аккаунта Yandex Cloud (консоль AI Studio → Search API v2)"
    echo "api-key: "
    echo "# folder-id — каталог Yandex Cloud; нужен gen_search, для web_search необязателен"
    echo "folder-id: "
  } > "$SRC"
  chmod 600 "$SRC"
  echo "$SRC создан (0600): заполните api-key и folder-id. Значения не печатались." >&2
  exit 0
fi

[ -f "$SRC" ] || { echo "нет $SRC — создайте: ./scripts/yandex_search_secrets.sh --init" >&2; exit 1; }

val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }

api_key=$(val api-key)
folder_id=$(val folder-id)

[ -n "$api_key" ] || { echo "в $SRC пустое поле: api-key" >&2; exit 1; }

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS" >/dev/null

# Secret один: folder-id может быть пустым — сервис стартует и без него (только web/image без gen_search)
$K -n "$NS" create secret generic yandex-search \
  --from-literal=api-key="$api_key" \
  --from-literal=folder-id="$folder_id" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

unset api_key
echo "ns/$NS: secret yandex-search применён (значения не выводились)"
