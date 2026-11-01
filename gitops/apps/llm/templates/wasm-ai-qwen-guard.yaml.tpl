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
        - llm-svc.demo-ai-lab.ru
      config:
        serviceName: guard.dns
        servicePort: 443
        serviceHost: api.demo-ai-lab.ru
        path: /v1/chat/completions
        # Имя модели в API GPUStack — с заглавными (`Qwen3Guard-Gen-4B`); served-name на инстансе
        # (`qwen3guard-gen-4b`) через API даёт 404. Ключ `guard` обязан иметь доступ к этой модели,
        # иначе 403 "Not allowed to access model" → fail-closed.
        model: Qwen3Guard-Gen-4B
        apiKey: <<GUARD_KEY>>
        checkRequest: true
        requestJsonPath: "messages.@reverse.0.content"
        blockLevels: ["unsafe"]
        # ПДн НЕ блокируем: их закрывает DLP-маскирование (999-й шаг, до стража). Проверено на
        # стенде: после маскирования страж видит `<PHONE> <EMAIL>` и сам ставит `Controversial/PII`,
        # то есть блокировка по категории `pii` отменяла бы работу DLP и резала обычные запросы
        # с телефоном. Блок — только `Unsafe` (уровень) и `Jailbreak` (категория), как в спеке P5.
        blockCategories: ["jailbreak"]
        failOpen: false
        denyCode: 403
        timeout: 8000
        maxTokens: 64
