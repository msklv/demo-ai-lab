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
- `apps/` — сервисы демо-шагов (пока пусто).
- `infra-apps/keycloak/` — **план** (`architecture/keycloak-spec.md`, K1–K7): Keycloak + PostgreSQL,
  ns `keycloak`, secret'ы `keycloak-db`/`keycloak-bootstrap` создаются вне Argo (в git паролей нет).
- Секреты в git не кладём: в манифестах только ссылки на Secret in-cluster
  (`AGENTS.md`, спека §8).
- `git pull --ff-only` перед push; статус проверять по живым подам, не по «Synced».