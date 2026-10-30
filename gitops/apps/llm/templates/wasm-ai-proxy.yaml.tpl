# ШАБЛОН (не применять напрямую): рендерится `scripts/llm_proxy_plugins.sh`.
# Ключ провайдера живёт в Secret `llm-deepseek`, а конфиг WasmPlugin принимает его только инлайном
# (`secretRef` в Higress нет) — поэтому объект собирается скриптом вне Argo (спека §5.1).
#
# `apiTokens` — массив: токен выбирается на запрос случайно, `failover` выводит из ротации мёртвый
# (401/429) и возвращает после health-check → ротация перекрытием без простоя и без рестарта шлюза.
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: llm-ai-proxy
  namespace: higress-system
spec:
  url: http://plugin-server.llm.svc.cluster.local:8080/wasm-plugins/ai-proxy/plugin.wasm
  phase: UNSPECIFIED_PHASE
  priority: 100
  failStrategy: FAIL_CLOSE
  defaultConfigDisable: true
  matchRules:
    - configDisable: false
      domain:
        - llm.demo-ai-lab.ru
        - llm-test.demo-ai-lab.ru
      config:
        activeProviderId: deepseek
        providers:
          - id: deepseek
            type: deepseek
            apiTokens:
<<DEEPSEEK_TOKENS>>
            failover:
              enabled: true
              failureThreshold: 3
              successThreshold: 2
              healthCheckInterval: 30s
              healthCheckTimeout: 5s
              healthCheckModel: deepseek-flash
              failoverOnStatus: ["401", "429"]
