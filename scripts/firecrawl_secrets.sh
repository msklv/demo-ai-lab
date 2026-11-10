#!/usr/bin/env bash
# C2 — Secret стека Firecrawl (ns `fc`) из приватного файла репозитория.
#
# Источник: firecrawl.local.md (корень репо, gitignored, 0600). Значения НЕ печатаются:
# скрипт идемпотентен (`create --dry-run=client | apply`) и выводит только имена объектов.
#
#   ./scripts/firecrawl_secrets.sh --init   # один раз: создать файл с СГЕНЕРИРОВАННЫМИ значениями
#   ./scripts/firecrawl_secrets.sh          # создать/обновить Secret fc-secrets до синка Argo
#
# Пароли БД/очереди и ключ Bull генерируются — их никто не выдаёт, ротация = перезапуск
# `--init` в новый файл (или ручная правка) + этот же скрипт + rollout restart подов.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=fc
SRC=firecrawl.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

gen() { openssl rand -hex 24; }

if [ "${1:-}" = "--init" ]; then
  [ -f "$SRC" ] && { echo "$SRC уже есть — не перезаписываю" >&2; exit 1; }
  umask 077
  {
    echo "# Firecrawl self-host стенда demo-ai-lab (не коммитить; см. architecture/specs/firecrawl-spec.md)"
    echo "# Ключи ниже никем не выдаются: сгенерированы при --init, ротация — новым значением."
    echo "# postgres-password — POSTGRES_PASSWORD у nuq-postgres и в api"
    echo "postgres-password: $(gen)"
    echo "# rabbitmq-user / rabbitmq-password — RABBITMQ_DEFAULT_USER/PASS и NUQ_RABBITMQ_URL"
    echo "rabbitmq-user: firecrawl"
    echo "rabbitmq-password: $(gen)"
    echo "# bull-auth-key — BULL_AUTH_KEY очереди (внутренний, наружу не публикуется)"
    echo "bull-auth-key: $(gen)"
  } > "$SRC"
  chmod 600 "$SRC"
  echo "$SRC создан (0600) со сгенерированными значениями. Значения не печатались." >&2
  exit 0
fi

[ -f "$SRC" ] || { echo "нет $SRC — создайте: ./scripts/firecrawl_secrets.sh --init" >&2; exit 1; }

val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }

pg_pass=$(val postgres-password)
mq_user=$(val rabbitmq-user)
mq_pass=$(val rabbitmq-password)
bull_key=$(val bull-auth-key)

for pair in "postgres-password:$pg_pass" "rabbitmq-user:$mq_user" \
            "rabbitmq-password:$mq_pass" "bull-auth-key:$bull_key"; do
  [ -n "${pair#*:}" ] || { echo "в $SRC пустое поле: ${pair%%:*}" >&2; exit 1; }
done

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS" >/dev/null

$K -n "$NS" create secret generic fc-secrets \
  --from-literal=postgres-password="$pg_pass" \
  --from-literal=rabbitmq-user="$mq_user" \
  --from-literal=rabbitmq-password="$mq_pass" \
  --from-literal=bull-auth-key="$bull_key" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

unset pg_pass mq_pass bull_key
echo "ns/$NS: secret fc-secrets применён (значения не выводились)"
echo "после смены значений: kubectl --context $CTX -n $NS rollout restart deploy/nuq-postgres deploy/rabbitmq deploy/firecrawl-api"
