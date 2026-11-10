# gitops/ — единственная точка деплоя (F6)

- `root/root-app.yaml` — app-of-apps; его применяет человек один раз
  (`kubectl apply -f gitops/root/root-app.yaml`). Дальше всё по git push.
- `root/applicationsets.yaml` — наблюдатели: каждый каталог `infra-apps/<имя>` и
  `apps/<имя>` становится Application с automated prune+selfHeal;
  `<имя>` = namespace назначения.
- `infra-apps/infra/` — живые объекты инфраструктуры: ClusterIssuer `letsencrypt-wildcard` (F5),
  NodeFeatureRule `nvidia-gpu-label` (F4) (оба кластерные — namespace приложения `infra`
  создаётся ApplicationSet'ом и остаётся пустым), публикация консоли Higress
  (`higress-console-ingress.yaml`), а с 2026-11-04 — гейт служебных UI и его обвязка:
  `wasm-store.yaml` (том + nginx, раздача wasm изнутри кластера), `lan-only-ui.yaml` (два
  `WasmPlugin` `ip-restriction`: `argo.`/`hgc.`/`lng.`/`mon.` только из LAN),
  `longhorn-ui-ingress.yaml` (`Certificate longhorn-demo-tls` + Ingress `lng.demo-ai-lab.ru`).
  Логин Longhorn UI — `WasmPlugin basic-auth` **вне Argo** (креды инлайном, `secretRef` в Higress нет):
  шаблон в `infra/templates/longhorn-ui-basic-auth.yaml.tpl` (подкаталог Argo не читает), рендер и
  применение — `scripts/longhorn_ui_auth.sh`, креды — `lng-admin.local.md` (gitignored).
  Плагин собирается и заливается `scripts/infra_wasm_plugins.sh`; решения и замеры —
  `architecture/specs/external-access-spec.md` E9.2. Состояние живьём (2026-10-24): приложения
  `infra` и `root-app` — Synced/Healthy.
  Helm-релизы (F2–F5, F8) управляются helm'ом напрямую; перевод их под Argo (включая metrics-server
  F10, поставленный helm'ом 2026-10-24) — отдельный план (adoption), спека §7 F6.
- `apps/` — сервисы демо-шагов: `owu/`, `spk/`, `doc/`, `ysrch/` (шаг 2; `ysrch` — Yandex Search MCP:
  Deployment + Service + ConfigMap-обёртка + Ingress, `gitops/apps/ysrch/README.md`).
- `apps/fc/` — **план** (`architecture/specs/firecrawl-spec.md`, C1–C6): извлечение веб-страниц в кластер
  (Firecrawl `2.10.19-production` + `playwright-service` + RabbitMQ + nuq-postgres + Redis, ns `fc`,
  **ClusterIP-only** — Ingress и MCP-обёртка в фазе C6). Secret `fc-secrets` создаёт
  `scripts/firecrawl_secrets.sh` до первого синка (`--init` один раз заполняет `firecrawl.local.md`,
  gitignored).
- `infra-apps/keycloak/` — **живёт с 2026-10-27** (`architecture/specs/keycloak-spec.md`, K1–K7 закрыты):
  `00-priorityclass.yaml` (ClusterPriorityClass `demo-stand-critical`), `10-postgres.yaml`
  (PostgreSQL 17.11, STS ×1 + PVC 8Gi Longhorn), `20-keycloak.yaml` (Keycloak 26.8.1 ×2 на паре
  k8s-02/03, `jdbc-ping`), `30-ingress.yaml` (`Certificate auth-demo-tls` + Ingress
  `auth.demo-ai-lab.ru`). Secret'ы `keycloak-db`/`keycloak-bootstrap` — вне Argo, их создаёт
  `scripts/keycloak_secrets.sh` до первого sync'а (в git паролей нет).
- `infra-apps/mcp-registry/` — применены вручную 2026-10-28 (`kubectl -n mcp-registry apply -f`);
  после push манифестов ApplicationSet создал Application `mcp-registry` — Synced/Healthy,
  объекты adopt'нуты (selfHeal; замер 02.11)
  (`architecture/specs/mcp-registry-spec.md`, приёмка M1–M8; runbook —
  `infra-apps/mcp-registry/README.md`): `10-postgres.yaml` (PostgreSQL 16-alpine, STS ×1 + PVC 8Gi,
  wave `-1`), `20-registry.yaml` (`modelcontextprotocol/registry` 1.8.6, wave `0`),
  `30-ingress.yaml` (`Certificate` + `Ingress` `mcp.demo-ai-lab.ru`). Secret'ы
  `mcp-registry-db`/`mcp-registry` создаёт `scripts/mcp_registry_secrets.sh` до синка
  (`--init` один раз генерирует `mcp-registry.local.md`, gitignored).
- `infra-apps/monitoring/` — Kuvasz 4.6.0 + PostgreSQL 17, `mon.demo-ai-lab.ru`
  (ADR-0009, развёрнут 2026-11-09): `10-postgres.yaml` (STS ×1 + PVC 8Gi Longhorn,
  wave `-1`), `20-kuvasz.yaml` (Deployment ×1, MCP-сервер включён, wave `0`),
  `30-ingress.yaml` (`Certificate mon-demo-tls` + Ingress `mon.demo-ai-lab.ru`).
  Размещение — k8s-05 (nodeAffinity preferred). Secret'ы `kuvasz-db`/`kuvasz-api-key`
  создаёт `scripts/kuvasz_secrets.sh` до первого синка (`--init` один раз заполняет
  `kuvasz.local.md`, gitignored). Доступ к UI — только из LAN (WasmPlugin
  `lan-only-ui`, `lan-only-ui-lan-source`).
- `infra-apps/gpustack/` — **план** (`architecture/specs/gpustack-spec.md`, G0–G8): сам релиз GPUStack ставится
  helm'ом с консоли (values — `ansible/values-gpustack.yaml`), в каталоге лежит только `30-ingress.yaml` (под Argo): `Certificate` `gpustack-tls`
  и Ingress `api.demo-ai-lab.ru` в ns `gpustack`. `RuntimeClass nvidia` — в
  `infra-apps/infra/` (объект кластерный).
- `mcp-servers/<svc>/server.json` — манифест публикации сервера в каталоге MCP (`mcp.demo-ai-lab.ru`),
  по одному каталогу на сервис (`mcp-servers/docling/`). Лежит **вне** `apps/*` и `infra-apps/*`
  намеренно: ApplicationSet читает все файлы каталога приложения, и JSON без `kind` ломает рендер.
  Каталог реестра — копия, источник истины — git (R-M1).
- Секреты в git не кладём: в манифестах только ссылки на Secret in-cluster
  (`AGENTS.md`, спека §8).
- `git pull --ff-only` перед push; статус проверять по живым подам, не по «Synced».