# gitops/ — единственная точка деплоя (F6, паттерн home-lab)

- `root/root-app.yaml` — app-of-apps; его применяет человек один раз
  (`kubectl apply -f gitops/root/root-app.yaml`). Дальше всё по git push.
- `root/applicationsets.yaml` — наблюдатели: каждый каталог `infra-apps/<имя>` и
  `apps/<имя>` становится Application с automated prune+selfHeal;
  `<имя>` = namespace назначения.
- `infra-apps/infra/` — живые объекты инфраструктуры (сейчас ClusterIssuer F5).
  Helm-релизы (F2–F5, F8) управляются helm'ом напрямую; перевод их под Argo —
  отдельный план (adoption), спека §7 F6.
- `apps/` — сервисы демо-шагов (пока пусто).
- Секреты в git не кладём: в манифестах только ссылки на Secret in-cluster
  (`AGENTS.md`, спека §8).
- `git pull --ff-only` перед push; статус проверять по живым подам, не по «Synced».