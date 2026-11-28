#!/usr/bin/env bash
# Y1 — Secret MCP-сервера Yandex Search в ns `ysrch` из приватного файла репозитория.
#
# Источник: yandex-search.local.md (gitignored, 0600).
#
#   ./scripts/yandex_search_secrets.sh --init   # один раз: создать шаблон файла
#   ./scripts/yandex_search_secrets.sh          # создать/обновить Secret до синка Argo
#
# Ключ берётся в консоли Yandex AI Studio (Search API v2), не генерируется: сервис-аккаунт
# и его Api-Key выдаёт владелец. Скрипт только раскладывает значение в кластер.
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=ysrch
SRC=yandex-search.local.md

if [ "${1:-}" = "--init" ]; then
  sc_init_guard "$SRC"
  {
    echo "# Yandex Search API для MCP-сервера стенда (не коммитить)"
    echo "# api-key — Api-Key сервис-аккаунта Yandex Cloud (консоль AI Studio → Search API v2)"
    echo "api-key: "
    echo "# folder-id — каталог Yandex Cloud; нужен gen_search, для web_search необязателен"
    echo "folder-id: "
  } > "$SRC"
  sc_seal "$SRC"
  echo "$SRC создан (0600): заполните api-key и folder-id. Значения не печатались." >&2
  exit 0
fi

sc_need_file "$SRC" "создайте: ./scripts/yandex_search_secrets.sh --init"

api_key=$(sc_val api-key "$SRC")
folder_id=$(sc_val folder-id "$SRC")

sc_need_nonempty api-key "$api_key" "в $SRC пустое поле: %s"

sc_ensure_ns "$NS"
# Secret один: folder-id может быть пустым — сервис стартует и без него (только web/image без gen_search)
sc_apply "$NS" yandex-search "api-key=$api_key" "folder-id=$folder_id"

unset api_key
echo "ns/$NS: secret yandex-search применён (значения не выводились)"
