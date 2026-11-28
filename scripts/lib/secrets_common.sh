#!/usr/bin/env bash
# scripts/lib/secrets_common.sh — общий каркас scripts/*_secrets.sh; только `source`, не запуск:
#   . "$(dirname "$0")/lib/secrets_common.sh"    # до `cd` в корень: $0 ещё разрешается от cwd
#
# Здесь в одном месте держатся инварианты AGENTS.md/HYGIENE.md: в коде только ИМЕНА ресурсов и
# ключей, значения не печатаются ни в stdout, ни в stderr; приватный *.local.md читается построчно
# и имеет права 0600; применение идемпотентно (`create --dry-run=client | apply`); значения
# генерируются только в `--init`; подключение — именованный контекст demo-ai-lab либо kubeconfig.

# --- кластер -----------------------------------------------------------------------------
sc_context()    { CTX=${KUBE_CONTEXT:-demo-ai-lab}; }   # контекст по умолчанию, флаг --context
sc_kubeconfig() {                                        # то же через KUBECONFIG (dsh, her)
  export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/demo-ai-lab.conf}"
  CTX=
}
sc_k() { # обёртка kubectl: без слова из переменной, поэтому без SC2086
  if [ -n "${CTX:-}" ]; then kubectl --context "$CTX" "$@"; else kubectl "$@"; fi
}

sc_ensure_ns() { # sc_ensure_ns <ns> [--echo-create]
  sc_k get ns "$1" >/dev/null 2>&1 && return 0
  if [ "${2:-}" = "--echo-create" ]; then sc_k create ns "$1"; else sc_k create ns "$1" >/dev/null; fi
}

# --- Secret'ы ----------------------------------------------------------------------------
sc_apply() { # sc_apply <ns> <secret> <ключ=значение>... — значения в вывод не попадают
  local ns=$1 name=$2 kv
  local args=()
  shift 2
  for kv in "$@"; do args+=(--from-literal="$kv"); done
  sc_k -n "$ns" create secret generic "$name" "${args[@]}" \
    --dry-run=client -o yaml | sc_k apply -f - >/dev/null
}

sc_secret_has() { # sc_secret_has <ns> <secret> <ключ> — есть ли ключ (значение не печатается)
  sc_k -n "$1" get secret "$2" -o "jsonpath={.data.$3}" 2>/dev/null | grep -q .
}

sc_ensure_rand() { # sc_ensure_rand <ns> <secret> <ключ> — создать, если ключа нет; ротация вручную
  local ns=$1 name=$2 key=$3
  sc_secret_has "$ns" "$name" "$key" && { echo "== Secret/$name: уже есть, не трогаю"; return 0; }
  sc_apply "$ns" "$name" "$key=$(sc_rand_hex 32)"
  echo "== Secret/$name: создан"
}

# --- приватный файл ----------------------------------------------------------------------
sc_val()    { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$2"; }   # формат `ключ: значение`
sc_val_eq() { awk -F'= ' -v k="$1" '$1==k{print $2; exit}' "$2"; }   # формат `ключ= значение`

sc_seal() { chmod 600 "$1"; }                                        # права приватного файла

sc_need_file() { # sc_need_file <файл> [<что делать>] — файла нет: сообщение и выход 1
  [ -f "$1" ] || { echo "нет $1${2:+ — $2}" >&2; exit 1; }
}

sc_init_guard() { # sc_init_guard <файл> — --init, пишущий файл целиком, чужой файл не затирает
  [ -f "$1" ] && { echo "$1 уже есть — не перезаписываю" >&2; exit 1; }
  umask 077
}

sc_missing() { # внутреннее: сообщение о незаполненном поле (само значение не печатается)
  # shellcheck disable=SC2059  # формат — литерал из скрипта, подстановка одна (%s → label)
  printf "${2:-пустое значение: %s}\n" "$1" >&2
  exit 1
}

sc_need() { # sc_need <label> <значение> [<формат>] — пусто/TBD/change_me = не заполнено
  case "${2:-}" in
    ""|TBD|change_me) sc_missing "$1" "${3:-}" ;;
  esac
}

sc_need_nonempty() { # sc_need_nonempty <label> <значение> [<формат>] — только пустое значение
  [ -n "${2:-}" ] || sc_missing "$1" "${3:-}"
}

# --- генерация значений (только --init) --------------------------------------------------
sc_rand_hex()  { openssl rand -hex "$1"; }                                # 2n hex-символов
sc_rand_b64()  { openssl rand -base64 "$1" | tr -d '\n'; }                # base64 одной строкой
sc_rand_safe() { openssl rand -base64 "$1" | tr -d '/+=\n' | cut -c1-"$2"; }  # [A-Za-z0-9], длина $2
