#!/usr/bin/env bash
# C2 — Secret стека Firecrawl (ns `fc`) из приватного файла репозитория.
#
# Источник: firecrawl.local.md (gitignored, 0600).
#
#   ./scripts/firecrawl_secrets.sh --init   # один раз: создать файл с СГЕНЕРИРОВАННЫМИ значениями
#   ./scripts/firecrawl_secrets.sh          # создать/обновить Secret fc-secrets до синка Argo
#
# Пароли БД/очереди и ключ Bull генерируются — их никто не выдаёт, ротация = перезапуск
# `--init` в новый файл (или ручная правка) + этот же скрипт + rollout restart подов.
set -euo pipefail
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS='fc'
SRC=firecrawl.local.md

if [ "${1:-}" = "--init" ]; then
  sc_init_guard "$SRC"
  {
    echo "# Firecrawl self-host стенда demo-ai-lab (не коммитить; см. architecture/specs/firecrawl-spec.md)"
    echo "# Ключи ниже никем не выдаются: сгенерированы при --init, ротация — новым значением."
    echo "# postgres-password — POSTGRES_PASSWORD у nuq-postgres и в api"
    echo "postgres-password: $(sc_rand_hex 24)"
    echo "# rabbitmq-user / rabbitmq-password — RABBITMQ_DEFAULT_USER/PASS и NUQ_RABBITMQ_URL"
    echo "rabbitmq-user: firecrawl"
    echo "rabbitmq-password: $(sc_rand_hex 24)"
    echo "# bull-auth-key — BULL_AUTH_KEY очереди (внутренний, наружу не публикуется)"
    echo "bull-auth-key: $(sc_rand_hex 24)"
  } > "$SRC"
  sc_seal "$SRC"
  echo "$SRC создан (0600) со сгенерированными значениями. Значения не печатались." >&2
  exit 0
fi

sc_need_file "$SRC" "создайте: ./scripts/firecrawl_secrets.sh --init"

pg_pass=$(sc_val postgres-password "$SRC")
mq_user=$(sc_val rabbitmq-user "$SRC")
mq_pass=$(sc_val rabbitmq-password "$SRC")
bull_key=$(sc_val bull-auth-key "$SRC")

sc_need_nonempty postgres-password "$pg_pass" "в $SRC пустое поле: %s"
sc_need_nonempty rabbitmq-user "$mq_user" "в $SRC пустое поле: %s"
sc_need_nonempty rabbitmq-password "$mq_pass" "в $SRC пустое поле: %s"
sc_need_nonempty bull-auth-key "$bull_key" "в $SRC пустое поле: %s"

sc_ensure_ns "$NS"
sc_apply "$NS" fc-secrets \
  "postgres-password=$pg_pass" \
  "rabbitmq-user=$mq_user" \
  "rabbitmq-password=$mq_pass" \
  "bull-auth-key=$bull_key"

unset pg_pass mq_pass bull_key
echo "ns/$NS: secret fc-secrets применён (значения не выводились)"
echo "после смены значений: kubectl --context $CTX -n $NS rollout restart deploy/nuq-postgres deploy/rabbitmq deploy/firecrawl-api"
