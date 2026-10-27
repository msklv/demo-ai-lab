# Open WebUI (`owu.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/owu-spec.md` (фазы O1–O6). Каталог раскатывает ApplicationSet `apps`
(`gitops/root/applicationsets.yaml`) как **plain-манифесты** в ns `owu`.

| Файл | Что |
|---|---|
| `20-open-webui.yaml` | **отрендеренный** чарт `open-webui` 17.0.0 (appVersion 0.12.0): StatefulSet `owu-open-webui`, Service (80→8080), PVC 5Gi `longhorn`, ServiceAccount. Источник рендера — `gitops/values/owu.yaml` |
| `30-ingress.yaml` | `Certificate owu-demo-tls` + `Ingress owu` (class `higress`) |

Секретов в каталоге нет — они создаются **до** первого синка (в git только ссылки):

| Secret (ns `owu`) | Ключи | Откуда |
|---|---|---|
| `owu-secrets` | `WEBUI_SECRET_KEY`, `OPENAI_API_KEY` | `owu-admin.local.md`; ключ модели — `gpustack-admin.local.md` |
| `owu-oidc` | `OAUTH_CLIENT_ID=owu`, `OAUTH_CLIENT_SECRET` | `scripts/keycloak_seed.py` → `keycloak-clients.local.md` |

## Почему рендер в файл, а не helm-source

ApplicationSet `apps` генерирует Application с одним `source.path` (directory) — helm-источника
и `valueFiles` у него нет, а менять генератор ради одного сервиса нельзя. Поэтому чарт
рендерится локально, а values лежат рядом в `gitops/values/owu.yaml` (вне `gitops/apps/*`,
чтобы Argo не пытался применить values как объект).

## Перерендер (апгрейд чарта/образа)

```bash
helm repo add open-webui https://open-webui.github.io/helm-charts
helm repo update open-webui
helm template owu open-webui/open-webui --version 17.0.0 --namespace owu \
  -f gitops/values/owu.yaml > /tmp/owu.yaml      # + шапка-комментарий
```

Отличия от спеки, зафиксированные по факту рендера:

- Service публикуется на порту **80** (`targetPort: http` = 8080), не 8080 — Ingress ссылается на 80.
- При `persistence.enabled` чарт создаёт **StatefulSet**, а не Deployment; имя объекта то же —
  `owu-open-webui` (в командax спеки `deploy/owu-open-webui` → фактически `sts/owu-open-webui`).
- Init-контейнер `copy-app-data` копирует запечённое содержимое `/app/backend/data` в PVC.
