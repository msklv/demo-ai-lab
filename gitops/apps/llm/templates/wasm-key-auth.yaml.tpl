# ШАБЛОН (не применять напрямую): рендерится `scripts/llm_proxy_plugins.sh`.
# Статический API-key для сервисов/интеграций — дополнительно к JWT Keycloak (ADR-0008), не вместо.
#
# Как это работает в цепочке:
#   opa 225 (allow, если JWT с `aud=llm`/ролью ИЛИ `x-api-key` из Secret `llm-apikey`)
#   → key-auth 310 (проверяет тот же ключ, ставит `X-Mse-Consumer: llm-svc`)
# ВАЖНО (проверено на стенде): на ОДНОМ домене два auth-плагина не сосуществуют — Higress требует
# обоих, а при смешении ответы конкурируют по фазам (то `401 jwt-auth.token_missing`, то запрос
# доходил до стража). Поэтому статический ключ живёт на отдельном хосте `llm-svc.demo-ai-lab.ru`
# (51-ingress-svc.yaml), а `llm.` остаётся чисто JWT. DLP/страж/квоты/ai-proxy привязаны к обоим
# доменам, так что защита одинаковая.
# Порядок на сервисном хосте: key-auth 310 (единственный чек: `60-wasm-opa.yaml` привязан только к `llm.`)
# → DLP 991 → страж 992 → квоты → ai-proxy.
#
# Ключ живёт в Secret `llm-apikey` / приватном `llm.local.md`, в git — только плейсхолдер.
# `in_query: false` — ключ не принимается из URL (иначе утекает в логи/историю).
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: llm-key-auth
  namespace: higress-system
spec:
  url: http://plugin-server.llm.svc.cluster.local:8080/wasm-plugins/key-auth/plugin.wasm
  phase: AUTHN
  priority: 310
  failStrategy: FAIL_CLOSE
  defaultConfig:
    global_auth: false
    consumers:
      - name: llm-svc
        credential: <<SVC_API_KEY>>
    keys:
      - x-api-key
    in_header: true
    in_query: false
  matchRules:
    - configDisable: false
      domain:
        - llm-svc.demo-ai-lab.ru
      config:
        allow:
          - llm-svc
