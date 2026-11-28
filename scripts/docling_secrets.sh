#!/usr/bin/env bash
# D7 — Secret VLM-пути Docling (ns `doc`) из приватного файла репозитория.
#
# Источник: docling.local.md (gitignored, 0600), поле `gpustack_key` — API-ключ GPUStack
# `docling-glm-ocr` с `allowed_model_names: [GLM-OCR]`.
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
# shellcheck disable=SC1091  # путь к библиотеке динамический: $0
. "$(dirname "$0")/lib/secrets_common.sh"
cd "$(dirname "$0")/.."
sc_context

NS=doc
SRC=docling.local.md

[ -f "$SRC" ] || { echo "нет $SRC: положите gpustack_key (ключ GPUStack с доступом к GLM-OCR)" >&2; exit 1; }
sc_seal "$SRC"

key=$(sc_val gpustack_key "$SRC")
sc_need_nonempty gpustack_key "$key" "в $SRC пустое поле: %s"

sc_ensure_ns "$NS"
sc_apply "$NS" docling-ocr "GLM_OCR_API_KEY=$key"

echo "Secret $NS/docling-ocr применён (ключ GLM_OCR_API_KEY). Значения не печатались."
