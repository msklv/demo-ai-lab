# ШАБЛОН (не применять напрямую): рендерится `scripts/llm_proxy_plugins.sh` в объект WasmPlugin.
# Причина вне-Argo: `spec.config` у WasmPlugin не умеет `secretRef`, а inline JWKS меняется при ротации
# ключей подписи realm. В git — шаблон с плейсхолдером, значение — только на стенде.
#
# `jwt-auth` проверяет подпись по JWKS, `iss` и `exp`; `aud`/роли он НЕ проверяет — это делает `opa`
# (60-wasm-opa.yaml, приоритет 225 → исполняется раньше).
#
# ВАЖНО (проверено на стенде): `consumers` живут в `defaultConfig`, а в правиле задаётся только `allow`.
# Плагин парсит правило как «глобальный конфиг + allow» (`config/parser.go: ParseRuleConfig`), поэтому
# consumers внутри `matchRules[].config` игнорируются, и плагин падает в «all consumers verify failed»
# с 403 на любом запросе.
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: llm-jwt-auth
  namespace: higress-system
spec:
  url: http://plugin-server.llm.svc.cluster.local:8080/wasm-plugins/jwt-auth/plugin.wasm
  phase: AUTHN
  priority: 350
  failStrategy: FAIL_CLOSE
  defaultConfig:
    global_auth: false
    consumers:
      - name: llm-jwt
        issuer: "https://auth.demo-ai-lab.ru/realms/dev"
        jwks: <<JWKS>>
        clock_skew_seconds: 60
        claims_to_headers:
          - claim: azp
            header: x-consumer
  matchRules:
    - configDisable: false
      domain:
        - llm.demo-ai-lab.ru
      config:
        allow:
          - llm-jwt
