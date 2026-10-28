# gitops/ — единственная точка деплоя (F6)

- `root/root-app.yaml` — app-of-apps; его применяет человек один раз
  (`kubectl apply -f gitops/root/root-app.yaml`). Дальше всё по git push.
- `root/applicationsets.yaml` — наблюдатели: каждый каталог `infra-apps/<имя>` и
  `apps/<имя>` становится Application с automated prune+selfHeal;
  `<имя>` = namespace назначения.
- `infra-apps/infra/` — живые объекты инфраструктуры: ClusterIssuer `letsencrypt-wildcard` (F5)
  и NodeFeatureRule `nvidia-gpu-label` (F4). Оба кластерные, поэтому namespace назначения
  приложения (`infra`) создаётся ApplicationSet'ом, но остаётся пустым. Состояние живьём
  (2026-10-24): приложения `infra` и `root-app` — Synced/Healthy.
  Helm-релизы (F2–F5, F8) управляются helm'ом напрямую; перевод их под Argo (включая metrics-server
  F10, поставленный helm'ом 2026-10-24) — отдельный план (adoption), спека §7 F6.
- `apps/` — сервисы демо-шагов: `owu/`, `spk/`, `doc/` (шаг 2, живут с 2026-10-28 под Argo CD).
- `infra-apps/keycloak/` — **живёт с 2026-10-27** (`architecture/keycloak-spec.md`, K1–K7 закрыты):
  `00-priorityclass.yaml` (ClusterPriorityClass `demo-stand-critical`), `10-postgres.yaml`
  (PostgreSQL 17.11, STS ×1 + PVC 8Gi Longhorn), `20-keycloak.yaml` (Keycloak 26.8.1 ×2 на паре
  k8s-02/03, `jdbc-ping`), `30-ingress.yaml` (`Certificate auth-demo-tls` + Ingress
  `auth.demo-ai-lab.ru`). Secret'ы `keycloak-db`/`keycloak-bootstrap` — вне Argo, их создаёт
  `scripts/keycloak_secrets.sh` до первого sync'а (в git паролей нет).
- `infra-apps/mcp-registry/` — **применены вручную 2026-10-28** (`kubectl -n mcp-registry apply -f`,
  Application в Argo ещё нет: каталог не в git → после push ApplicationSet создаст его и объекты
  перейдут под selfHeal)
  (`architecture/mcp-registry-spec.md`, приёмка M1–M8; runbook —
  `infra-apps/mcp-registry/README.md`): `10-postgres.yaml` (PostgreSQL 16-alpine, STS ×1 + PVC 8Gi,
  wave `-1`), `20-registry.yaml` (`modelcontextprotocol/registry` 1.8.6, wave `0`),
  `30-ingress.yaml` (`Certificate` + `Ingress` `mcp.demo-ai-lab.ru`). Secret'ы
  `mcp-registry-db`/`mcp-registry` создаёт `scripts/mcp_registry_secrets.sh` до синка
  (`--init` один раз генерирует `mcp-registry.local.md`, gitignored).
- `infra-apps/gpustack/` — **план** (`architecture/gpustack-spec.md`, G0–G8): сам релиз GPUStack ставится
  helm'ом с консоли (values — `ansible/values-gpustack.yaml`), в каталоге лежат только объекты под Argo:
  Ingress `api.demo-ai-lab.ru` и `Certificate` в ns `gpustack`. `RuntimeClass nvidia` — в
  `infra-apps/infra/` (объект кластерный).
- `mcp-servers/<svc>/server.json` — манифест публикации сервера в каталоге MCP (`mcp.demo-ai-lab.ru`),
  по одному каталогу на сервис (`mcp-servers/docling/`). Лежит **вне** `apps/*` и `infra-apps/*`
  намеренно: ApplicationSet читает все файлы каталога приложения, и JSON без `kind` ломает рендер.
  Каталог реестра — копия, источник истины — git (R-M1).
- Секреты в git не кладём: в манифестах только ссылки на Secret in-cluster
  (`AGENTS.md`, спека §8).
- `git pull --ff-only` перед push; статус проверять по живым подам, не по «Synced».