# ШАБЛОН (не применять напрямую): рендерится `scripts/llm_proxy_plugins.sh`.
# Причина вне-Argo та же, что у ai-proxy: ключ модели стража (GPUStack API key `guard`) не кладётся в git.
#
# Страж на `llm.` — fail-closed (ADR-0008 п.2): нет ответа стража → запрос наружу не уходит.
# Уровень/категории — вывод Qwen3Guard-Gen (`Safety: …`, `Categories: …`); `Unsafe` блокируется всегда,
# `Controversial` пропускается (решение по умолчанию; менять здесь, а не в коде плагина).
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: llm-qwen-guard
  namespace: higress-system
spec:
  url: http://plugin-server.llm.svc.cluster.local:8080/wasm-plugins/ai-qwen-guard/plugin.wasm
  phase: AUTHN
  priority: 992
  failStrategy: FAIL_CLOSE
  defaultConfigDisable: true
  matchRules:
    - configDisable: false
      domain:
        - llm.demo-ai-lab.ru
      config:
        serviceName: guard.dns
        servicePort: 40000
        serviceHost: qwen3guard.gpustack.svc.cluster.local
        path: /v1/chat/completions
        model: qwen3guard-gen-4b
        apiKey: <<GUARD_KEY>>
        checkRequest: true
        requestJsonPath: "messages.@reverse.0.content"
        blockLevels: ["unsafe"]
        blockCategories: ["jailbreak", "pii"]
        failOpen: false
        denyCode: 403
        timeout: 8000
        maxTokens: 64
