#!/usr/bin/env bash
# D7 — Secret VLM-пути Docling (ns `doc`) из приватного файла репозитория.
#
# Источник: docling.local.md (корень репо, gitignored, 0600), поле `gpustack_key` — API-ключ GPUStack
# `docling-glm-ocr` с `allowed_model_names: [GLM-OCR]`. Значение НЕ печатается: скрипт идемпотентен
# (`create --dry-run=client | apply`) и выводит только имя объекта.
#
#   ./scripts/docling_secrets.sh          # создать/обновить Secret docling-ocr до синка Argo
#
# Ключ выдаётся GPUStack'ом, а не генерируется здесь (в отличие от fc-secrets):
#   curl -b <cookie после POST /auth/login> -X POST https://api.demo-ai-lab.ru/v2/api-keys \
#     -H 'Content-Type: application/json' \
#     -d '{"name":"docling-glm-ocr","description":"Docling VLM-путь (кейс 04)","allowed_model_names":["GLM-OCR"]}'
# Значение из ответа (`value`) кладётся в docling.local.md как `gpustack_key: <value>`.
# Ротация = новый ключ тем же POST + этот скрипт + `kubectl -n doc rollout restart deploy/docling`.
set -euo pipefail
cd "$(dirname "$0")/.."

NS=doc
SRC=docling.local.md
CTX=${KUBE_CONTEXT:-demo-ai-lab}
K="kubectl --context $CTX"

[ -f "$SRC" ] || { echo "нет $SRC: положите gpustack_key (ключ GPUStack с доступом к GLM-OCR)" >&2; exit 1; }
chmod 600 "$SRC"

val() { awk -F': ' -v k="$1" '$1==k{print $2; exit}' "$SRC"; }
key=$(val gpustack_key)
[ -n "$key" ] || { echo "в $SRC пустое поле: gpustack_key" >&2; exit 1; }

$K get ns "$NS" >/dev/null 2>&1 || $K create ns "$NS" >/dev/null

$K -n "$NS" create secret generic docling-ocr \
  --from-literal=GLM_OCR_API_KEY="$key" \
  --dry-run=client -o yaml | $K apply -f - >/dev/null

echo "Secret $NS/docling-ocr применён (ключ GLM_OCR_API_KEY). Значения не печатались."
