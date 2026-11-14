# `gpustack` — инференс (GPUStack 2.2.3) под Argo CD

Application `gpustack` (ApplicationSet `infra-apps`, git-directory generator, `prune+selfHeal`) —
ns `gpustack`. Спека: `architecture/specs/gpustack-spec.md`; миграция и замеры:
`architecture/specs/gpustack-argocd-migration.md`; решение — ADR-0011.

## Из чего состоит каталог

| Файл | Что это |
|---|---|
| `kustomization.yaml` | инflирует OCI-чарт `gpustack-chart` 2.2.3 + патчи (см. ниже) + `30-ingress.yaml` |
| `30-ingress.yaml` | `Certificate gpustack-tls` + `Ingress gpustack-api` (`api.demo-ai-lab.ru`, TLS из своего серта: PEM в values чарта = серт в git) |
| `values-gpustack.yaml` | values релиза (единственный источник правды, `helmCharts.valuesFile`; лежит внутри каталога, потому что kustomize не пускает `valuesFile` за его пределы) |

Чарт **не форкается и не вендорится**: kustomize тянет его из `oci://registry-1.docker.io/gpustack`
при рендере и кэширует в `charts/` этого каталога (в git не попадает, `.gitignore`).
Для рендера нужен `--enable-helm`: в кластере включено глобально в `argocd-cm`
(`kustomize.buildOptions: --enable-helm`) — настройка **вне git**, команда — в шапке `kustomization.yaml`.

## Патчи (то, чего чарт не умеет)

| Объект | Патч | Зачем |
|---|---|---|
| `Secret registration-token`, `Secret gpustack-jwt-key` | `$patch: delete` | шаблоны чарта делают `lookup`+`randAlphaNum`: в `helm template` кластера нет → новое значение на каждом рендере (вечный `OutOfSync`, ротация JWT/registration-токена). Секреты создаёт `scripts/gpustack_secrets.sh` |
| `sts/gpustack-server` | `envFrom/-: gpustack-oidc` | SSO: секрет OIDC-клиента не проходит через values (в git нельзя), а `envFrom` в чарте захардкожен |
| `sts/gpustack-server` | `securityContext.capabilities` | embedded PostgreSQL (`su postgres`) без `SETUID/SETGID/CHOWN/DAC_OVERRIDE/FOWNER` падает `su: cannot set groups` |
| `ds/gpustack-worker` | `nodeSelector: k8s-01` | CPU-воркер под bge-модели 780M: селектор чарта (`acceleratable=false`) на k8s-01 не срабатывает (спека §4.7) |

Патчи — только `add`/`replace` конкретных полей: замена целого `securityContext` или `nodeSelector`
даёт лишний роллаут (проверено `kubectl diff`).

## Апгрейд

1. В `kustomization.yaml` — `helmCharts[0].version`, в `gitops/values/gpustack.yaml` — `image.tag`
   (образы предтянуть на k8s-04: без предтяжки апгрейд встанет на pull — спека §7).
2. Прогнать рендер и сравнить с живым состоянием **до** пуша:
   ```bash
   kustomize build --enable-helm gitops/infra-apps/gpustack > /tmp/gpustack.yaml
   kubectl diff -n gpustack -f /tmp/gpustack.yaml
   ```
3. Push → Argo sync → дождаться миграции БД GPUStack (`/healthz` 200), модели `running`.

`helm upgrade` для релиза `gpustack` **запрещён**: helm-запись (`sh.helm.release.v1.gpustack.*`)
осталась от консольной установки, и `helm upgrade`/`uninstall` начнут воевать с Argo за те же поля.
Записи удаляются после обкатки — см. миграционную спеку и ADR-0011.

## Откат

`git revert` **не** откат: прежняя ревизия без `helmCharts` заставит Argo заprune'ить все объекты
чарта (StatefulSet, Services, Secret'ы). Безопасно:

```bash
argocd app set gpustack --sync-policy none          # снять automated
argocd app rollback gpustack <revision>             # или argocd app history gpustack
```

Аварийный выход из Argo с сохранением объектов — `argocd app delete gpustack --cascade=orphan`,
дальше объекты остаются в кластере (и снова под helm-записью, если её не удаляли).

## Проверка после sync

- `kubectl -n gpustack get sts gpustack-server -o jsonpath='{.metadata.generation}'` — не растёт,
  если менялись только значения; поды не пересоздаются.
- SSO: вход в `https://api.demo-ai-lab.ru` через Keycloak (клиент `gps`), `/v1/models` → 200.
- `kubectl -n gpustack get pods` — сервер `Running`, воркеры на `k8s-04` (nvidia) и `k8s-01` (CPU).
