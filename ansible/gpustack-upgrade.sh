#!/usr/bin/env bash
# Апгрейд релиза GPUStack + подмешивание Secret'а с OIDC-секретом (G7).
#
# Зачем обёртка: чарт 2.2.3 рендерит `server.environmentConfig` только литералами в ConfigMap
# `server-config`, а `envFrom` сервера захардкожен (`registration-token`, `gpustack-jwt-key`,
# ConfigMap). Секрет OIDC-клиента в values/git попасть не может, поэтому после `helm upgrade`
# скрипт добавляет в StatefulSet `envFrom.secretRef: gpustack-oidc` — идемпотентно.
# `helm upgrade` напрямую (без этого скрипта) затрёт envFrom и SSO молча отвалится.
set -euo pipefail

RELEASE=${RELEASE:-gpustack}
NS=${NS:-gpustack}
CONTEXT=${CONTEXT:-demo-ai-lab}
SECRET=${SECRET:-gpustack-oidc}
CHART=${CHART:-oci://registry-1.docker.io/gpustack/gpustack-chart}
VERSION=${VERSION:-2.2.3}
VALUES=${VALUES:-ansible/values-gpustack.yaml}

cd "$(dirname "$0")/.."

echo "== helm upgrade $RELEASE ($VERSION)"
# --force-conflicts: envFrom сервера правится нашим patch'ем ниже (поле принадлежит kubectl-patch),
# и без этого флага server-side apply Helm 4 падает на конфликте полей.
helm upgrade "$RELEASE" "$CHART" --version "$VERSION" -n "$NS" --kube-context "$CONTEXT" \
  -f "$VALUES" --force-conflicts "$@"

have=$(kubectl --context "$CONTEXT" -n "$NS" get sts "$RELEASE-server" \
  -o jsonpath='{.spec.template.spec.containers[0].envFrom[*].secretRef.name}' 2>/dev/null || true)
if [[ " $have " == *" $SECRET "* ]]; then
  echo "== envFrom/$SECRET уже в StatefulSet"
else
  echo "== добавляю envFrom/$SECRET в StatefulSet"
  kubectl --context "$CONTEXT" -n "$NS" patch sts "$RELEASE-server" --type=json -p \
    "[{\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/envFrom/-\",\"value\":{\"secretRef\":{\"name\":\"$SECRET\",\"optional\":false}}}]"
fi

# --- securityContext сервера -------------------------------------------------
# Чарт 2.2.3 жёстко рендерит `allowPrivilegeEscalation: false` без capabilities, а образ поднимает
# embedded PostgreSQL и переключается на пользователя `postgres` (`su`). В контейнере без
# CAP_SETUID/CAP_SETGID это `su: cannot set groups: Operation not permitted`, postgres не стартует,
# сервер остаётся NotReady. Патч идемпотентен и обязателен после каждого `helm upgrade`.
caps=$(kubectl --context "$CONTEXT" -n "$NS" get sts "$RELEASE-server" \
  -o jsonpath='{.spec.template.spec.containers[0].securityContext.capabilities.add[*]}' 2>/dev/null || true)
if [[ " $caps " == *" SETUID "* ]]; then
  echo "== securityContext сервера уже с capabilities"
else
  echo "== добавляю capabilities (SETUID SETGID CHOWN DAC_OVERRIDE FOWNER) серверу"
  kubectl --context "$CONTEXT" -n "$NS" patch sts "$RELEASE-server" --type=json -p \
    "[{\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/securityContext/capabilities\",\"value\":{\"add\":[\"SETUID\",\"SETGID\",\"CHOWN\",\"DAC_OVERRIDE\",\"FOWNER\"]}},
      {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/securityContext/allowPrivilegeEscalation\",\"value\":true}]"
fi

kubectl --context "$CONTEXT" -n "$NS" rollout status sts/"$RELEASE-server" --timeout=300s

echo "== проверка окружения в поде"
kubectl --context "$CONTEXT" -n "$NS" exec "$RELEASE-server-0" -- env 2>/dev/null \
  | grep -E '^GPUSTACK_(OIDC_[A-Z_]+|EXTERNAL_AUTH_DEFAULT_INACTIVE)=' \
  | sed -E 's/^(GPUSTACK_OIDC_CLIENT_SECRET=).*/\1***/'
