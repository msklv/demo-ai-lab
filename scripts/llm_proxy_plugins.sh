#!/usr/bin/env bash
# Рендер и применение Wasm-плагинов маршрута `llm.`, конфиг которых содержит секреты
# (спека architecture/specs/llm-proxy-spec.md §5.1, ADR-0008).
#
# Почему скрипт, а не Argo: `WasmPlugin.spec.config` в Higress не умеет `secretRef` — ключ провайдера и
# ключ модели стража попадают в объект только инлайном. В git лежат шаблоны с плейсхолдерами
# (`gitops/apps/llm/templates/*.tpl`), объекты живут вне Argo (как `higress-console`/`gpustack`).
#
# Что делает:
#   1) Secret llm-deepseek (ns llm) из `llm.local.md` — ключ провайдера, не печатается;
#   2) inline JWKS из Keycloak (публичные ключи realm) → WasmPlugin llm-jwt-auth;
#   3) apiTokens (массив: текущий ключ(и) через запятую) → WasmPlugin llm-ai-proxy;
#   4) ключ модели стража из `gpustack-admin.local.md` → WasmPlugin llm-qwen-guard.
#
# Использование:
#   scripts/llm_proxy_plugins.sh              # применить
#   scripts/llm_proxy_plugins.sh --dry-run    # только отрендерить (в stdout), ничего не применять
#
# Ротация ключа провайдера (спека §5.1): DEEPSEEK_EXTRA_KEY=<новый ключ> scripts/llm_proxy_plugins.sh
# — в apiTokens окажутся оба, `failover` выведет мёртвый; затем удалить старый в платформе и
# перерендерить без EXTRA.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
TPL="$REPO/gitops/apps/llm/templates"
REALM_ISSUER="https://auth.demo-ai-lab.ru/realms/dev"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# --- 1. ключ провайдера --------------------------------------------------------
DEEPSEEK_KEY=$(sed -n 's/^deepseek_api_key= *//p' "$REPO/llm.local.md" | tr -d ' «»"'"'" | tr -d '\n')
if [ -z "$DEEPSEEK_KEY" ]; then
  echo "FAIL: deepseek_api_key не найден в llm.local.md" >&2
  exit 1
fi

# массив токенов: текущий + опциональный новый (ротация перекрытием)
TOKENS="              - '$DEEPSEEK_KEY'"
if [ -n "${DEEPSEEK_EXTRA_KEY:-}" ]; then
  TOKENS="$TOKENS
              - '$DEEPSEEK_EXTRA_KEY'"
fi

# --- 1b. регистры Higress (McpBridge default) -----------------------------------
# Кластеров для сервисов, не привязанных к маршруту, на стенде нет: wasm-вызов падает
# `bad argument`. Регистры живут в GPUStack-овом McpBridge `higress-system/default` (свой объект
# контроллер не разбирает) — поэтому merge идемпотентный и повторяется после деплоя модели.
if [ "$DRY_RUN" = 1 ]; then
  echo "dry-run: регистры McpBridge default не меняю (см. gitops/apps/llm/40-registries.yaml)" >&2
else
  PATCH=$(mktemp)
  python3 - "$REPO/gitops/apps/llm/40-registries.yaml" > "$PATCH" <<'PYEOF'
import json, subprocess, sys, yaml
wanted = yaml.safe_load(open(sys.argv[1]))["registries"]
cur = json.loads(subprocess.check_output(
    ["kubectl", "-n", "higress-system", "get", "mcpbridge", "default", "-o", "json"]))["spec"]["registries"]
have = {r["name"]: r for r in cur}
for r in wanted:
    have[r["name"]] = r          # перезапись: адрес регистра — часть желаемого состояния
print(json.dumps({"spec": {"registries": list(have.values())}}))
PYEOF
  kubectl patch mcpbridge default -n higress-system --type=merge -p "$(cat "$PATCH")" >/dev/null
  rm -f "$PATCH"
  echo "ok: регистры McpBridge default"
fi

# --- 2. публичные ключи подписи realm -----------------------------------------
JWKS=$(curl -fsS --max-time 20 "$REALM_ISSUER/protocol/openid-connect/certs")
echo "$JWKS" | python3 -c 'import json,sys; d=json.load(sys.stdin); n=len(d.get("keys") or []); assert n, "JWKS пуст"; print("jwks: %d ключ(а)" % n, file=sys.stderr)'
case "$JWKS" in *"'"*) echo "FAIL: JWKS содержит одинарную кавычку" >&2; exit 1;; esac

# --- 3. ключ модели стража ------------------------------------------------------
GUARD_KEY=$(sed -n 's/^guard-key: *//p' "$REPO/gpustack-admin.local.md" 2>/dev/null | tr -d ' \n')
if [ -z "$GUARD_KEY" ]; then
  echo "FAIL: guard-key не найден в gpustack-admin.local.md (создать POST /v2/api-keys {name: guard})" >&2
  exit 1
fi

# --- 3b. статический тестовый API-key (x-api-key) -------------------------------
# Дополнительно к JWT (ADR-0008): нужен для тестов/интеграций, где нет Keycloak-клиента.
# Значение — в приватном `llm.local.md` и в Secret `llm-apikey` (файл data.json для OPA);
# в git только плейсхолдер в шаблоне. Ключ создаётся один раз и переиспользуется.
TEST_KEY=$(sed -n 's/^test_api_key= *//p' "$REPO/llm.local.md" 2>/dev/null | tr -d ' \n')
if [ -z "$TEST_KEY" ]; then
  TEST_KEY="llm-test-$(python3 -c 'import secrets;print(secrets.token_hex(16))')"
  printf 'test_api_key= %s\n' "$TEST_KEY" >> "$REPO/llm.local.md"
  echo "ok: сгенерирован test_api_key и записан в llm.local.md"
fi

render() { # render <tpl> <placeholder> <value>
  python3 - "$1" "$2" "$3" <<'PY'
import sys, pathlib
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(path).read_text()
if key not in text:
    sys.exit(f"FAIL: плейсхолдер {key} не найден в {path}")
sys.stdout.write(text.replace(key, value))
PY
}

OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

# jwks в YAML — одинарные кавычки отключают разбор JSON-спецсимволов
render "$TPL/wasm-jwt-auth.yaml.tpl" "<<JWKS>>" "'$JWKS'" > "$OUT/10-jwt-auth.yaml"
render "$TPL/wasm-ai-proxy.yaml.tpl" "<<DEEPSEEK_TOKENS>>" "$TOKENS" > "$OUT/20-ai-proxy.yaml"
render "$TPL/wasm-ai-qwen-guard.yaml.tpl" "<<GUARD_KEY>>" "$GUARD_KEY" > "$OUT/30-guard.yaml"
render "$TPL/wasm-key-auth.yaml.tpl" "<<TEST_API_KEY>>" "$TEST_KEY" > "$OUT/40-key-auth.yaml"

if [ "$DRY_RUN" = 1 ]; then
  for f in "$OUT"/*.yaml; do
    echo "=== $f"
    sed -E "s/(apiToken|apiKey)s?:.*/\1: «redacted»/; s/^              - 'sk-[^']*'/              - '«redacted»'/; s/jwks: '.*'/jwks: '«redacted-inline-jwks»'/" "$f"
  done
  exit 0
fi

kubectl create secret generic llm-deepseek -n llm \
  --from-literal=api-token="$DEEPSEEK_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
echo "ok: Secret llm/llm-deepseek"

# тестовые API-ключи для OPA (data.json) — политика читает data.llm.api_keys
if [ "$DRY_RUN" = 0 ]; then
  TMP=$(mktemp)
  printf '{"llm":{"api_keys":["%s"]}}' "$TEST_KEY" > "$TMP"
  kubectl create secret generic llm-apikey -n llm --from-file=data.json="$TMP" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  rm -f "$TMP"
  echo "ok: Secret llm/llm-apikey"
fi



for f in "$OUT"/*.yaml; do
  kubectl apply -f "$f" >/dev/null
  echo "ok: $(grep -m1 '^  name:' "$f" | awk '{print $2}')"
done
