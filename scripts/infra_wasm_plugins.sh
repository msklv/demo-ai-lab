#!/usr/bin/env bash
# Заливка wasm-плагинов инфраструктурных хостов в том `wasm-store` (ns higress-system).
#
# Зачем: allowlist служебных UI (`argo.`, `hgc.`, `lng.`, `mon.`, админ-пути `auth.`) и Basic Auth
# Longhorn UI — плагины Higress; официальные плагины лежат в OCI-реестре Higress под закрытым путём
# `higress/plugins/*` (анонимный pull → 401, проверено 2026-11-04), поэтому плагины собираются
# из исходников тега `v2.1.9` официальным способом (`plugins/wasm-go/Dockerfile`:
# `GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared`) и кладутся в том, который
# раздаёт nginx `wasm-store` (`gitops/infra-apps/infra/wasm-store.yaml`).
#
# Набор: `ip-restriction` (allowlist — `gitops/infra-apps/infra/lan-only-ui.yaml`) и `basic-auth`
# (логин Longhorn UI — `scripts/longhorn_ui_auth.sh`).
#
# Использование:
#   scripts/infra_wasm_plugins.sh           # собрать (если нужно) и залить весь набор
#   scripts/infra_wasm_plugins.sh --check   # только проверить: файлы в томе + отдача по spec.url
#   scripts/infra_wasm_plugins.sh --dry-run # собрать в $TMPDIR, ничего не заливать
#
# Требования: go 1.24+ (wasip1), git, kubectl, ssh не нужен.
# Context по умолчанию `demo-ai-lab` (env DEMO_KUBE_CONTEXT).
#
# После заливки: `kubectl -n higress-system apply -f gitops/infra-apps/infra/lan-only-ui.yaml`
# и `scripts/longhorn_ui_auth.sh`. Envoy подхватывает wasm по `spec.url` сам; если плагин уже был
# загружен с ошибкой — рестарт gateway-пода не нужен (повторные попытки), см. `references/health-runbook.md`.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
HIGRESS_TAG="v2.1.9"
# plugin:version — версия из plugins/wasm-go/extensions/<plugin>/VERSION в теге v2.1.9
PLUGINS="ip-restriction:1.0.0 basic-auth:1.0.0"
NS="higress-system"
CTX="${DEMO_KUBE_CONTEXT:-demo-ai-lab}"
KUBECTL=(kubectl --context "$CTX")
SRC="${TMPDIR:-/tmp}/higress-src-${HIGRESS_TAG}"

MODE="apply"
case "${1:-}" in
  --check)   MODE="check" ;;
  --dry-run) MODE="dry" ;;
  "")        ;;
  *) echo "usage: $0 [--check|--dry-run]" >&2; exit 2 ;;
esac

say() { printf '%s\n' "$*" >&2; }
store_dir() { printf '/usr/share/nginx/html/wasm-plugins/%s/%s' "$1" "$2"; }
store_url() { printf 'http://wasm-store.%s.svc.cluster.local:8080/wasm-plugins/%s/%s/plugin.wasm' "$NS" "$1" "$2"; }
store_pod() { "${KUBECTL[@]}" -n "$NS" get pod -l app=wasm-store -o name 2>/dev/null | head -1; }
gateway_pod() { "${KUBECTL[@]}" -n "$NS" get pod -l app=higress-gateway -o name 2>/dev/null | head -1; }

# --- проверка без сборки ------------------------------------------------------
if [ "$MODE" = "check" ]; then
  pod=$(store_pod)
  if [ -z "$pod" ]; then
    say "FAIL: под wasm-store в ns ${NS} не найден"
    exit 1
  fi
  gw=$(gateway_pod)
  rc=0
  for spec in $PLUGINS; do
    name=${spec%%:*}; ver=${spec##*:}; dir=$(store_dir "$name" "$ver")
    size=$("${KUBECTL[@]}" -n "$NS" exec "${pod#pod/}" -- sh -c "wc -c < ${dir}/plugin.wasm" 2>/dev/null | tr -d ' ' || true)
    if [ -z "$size" ]; then
      say "FAIL: ${dir}/plugin.wasm нет в томе — запустить $0 без флагов"
      rc=1; continue
    fi
    code=""
    if [ -n "$gw" ]; then
      code=$("${KUBECTL[@]}" -n "$NS" exec "${gw#pod/}" -- curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$(store_url "$name" "$ver")" 2>/dev/null || true)
    fi
    say "ok: ${name} ${ver} — ${size} Б в томе, spec.url из gateway → ${code:-n/a}"
    [ "${code:-}" = "200" ] || rc=1
  done
  exit $rc
fi

# --- 1. сборка ---------------------------------------------------------------
if [ ! -d "$SRC/plugins/wasm-go/extensions" ]; then
  say "клонирую higress ${HIGRESS_TAG} → ${SRC}"
  rm -rf "$SRC"
  git clone --depth 1 --branch "$HIGRESS_TAG" https://github.com/alibaba/higress.git "$SRC" >/dev/null 2>&1
fi

for spec in $PLUGINS; do
  name=${spec%%:*}; ver=${spec##*:}
  wasm="${SRC}/plugins/wasm-go/extensions/${name}/plugin.wasm"
  rm -f "$wasm"
  say "собираю ${name} ${ver} (${HIGRESS_TAG})"
  ( cd "${SRC}/plugins/wasm-go/extensions/${name}" \
    && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o plugin.wasm . )
  sha=$(shasum -a 256 "$wasm" | cut -d' ' -f1)
  say "ok: ${wasm} ($(wc -c < "$wasm" | tr -d ' ') Б, sha256 ${sha:0:16}…)"
done

if [ "$MODE" = "dry" ]; then
  say "dry-run: в кластер ничего не заливаю"
  exit 0
fi

# --- 2. заливка в том --------------------------------------------------------
pod=$(store_pod)
if [ -z "$pod" ]; then
  say "FAIL: под wasm-store не найден — сначала применить gitops/infra-apps/infra/wasm-store.yaml"
  exit 1
fi
for spec in $PLUGINS; do
  name=${spec%%:*}; ver=${spec##*:}
  dir=$(store_dir "$name" "$ver")
  wasm="${SRC}/plugins/wasm-go/extensions/${name}/plugin.wasm"
  "${KUBECTL[@]}" -n "$NS" exec "${pod#pod/}" -- mkdir -p "$dir"
  "${KUBECTL[@]}" -n "$NS" cp "$wasm" "${NS}/${pod#pod/}:${dir}/plugin.wasm"
  size=$("${KUBECTL[@]}" -n "$NS" exec "${pod#pod/}" -- sh -c "wc -c < ${dir}/plugin.wasm" | tr -d ' ')
  say "ok: залито в ${pod#pod/}:${dir}/plugin.wasm (${size} Б)"
done

# --- 3. самопроверка ---------------------------------------------------------
"$0" --check
