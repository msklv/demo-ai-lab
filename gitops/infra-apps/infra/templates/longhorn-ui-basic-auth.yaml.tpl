# Basic Auth для Longhorn UI — ШАБЛОН, не применять как есть.
#
# Рендерит `scripts/longhorn_ui_auth.sh` из локального приватного хранилища (`lng-admin.local.md`,
# gitignored) и применяет через `kubectl`, минуя Argo: креды (`login:password`) живут внутри
# `WasmPlugin.spec.defaultConfig`, а `secretRef` в Higress не поддерживается — тот же приём, что у
# `llm-jwt-auth` / `llm-key-auth` (`gitops/apps/llm/README.md`). В git остаётся только этот шаблон.
#
# Назначение (решение владельца 2026-11-04, `architecture/specs/external-access-spec.md` E9.3):
# у Longhorn UI нет собственной авторизации, а `/v1/*` — это полный контроль дискового слоя
# (тома, ноды, backup target с кредами, registry secrets). Сетевой allowlist (`lan-only-ui`,
# priority 400/401) остаётся первым гейтом; логин — второй, для любой машины ВНУТРИ LAN/VPN.
#
# Особенности конфига плагина `basic-auth` (README тега v2.1.9):
#   * `consumers` — ТОЛЬКО на уровне инстанса (`defaultConfig`), `credential` = `login:password`;
#   * `allow` — на уровне правила (`matchRules[].config`), аутентификация и авторизация в одном
#     правиле не сосуществуют;
#   * `global_auth: false` — плагин действует только на перечисленные домены/маршруты.
#     (В отличие от `ip-restriction`, здесь `defaultConfig` НЕ отключаем: в нём живут потребители.)
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  name: longhorn-ui-basic-auth
  namespace: higress-system
spec:
  phase: AUTHN
  priority: 320
  failStrategy: FAIL_CLOSE
  url: http://wasm-store.higress-system.svc.cluster.local:8080/wasm-plugins/basic-auth/1.0.0/plugin.wasm
  defaultConfig:
    global_auth: false
    consumers:
      - name: admin
        credential: <<CREDENTIAL>>
  matchRules:
    - configDisable: false
      domain:
        - lng.demo-ai-lab.ru
      config:
        allow:
          - admin
