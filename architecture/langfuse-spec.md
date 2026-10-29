# Langfuse (`lng.demo-ai-lab.ru`) — LLM-наблюдаемость, шаг 2 демо

> **Версия:** v1.0 (2026-10-29) · **Статус:** **спека, не установлено** (пины и рендер сверены живьём 2026-10-29).
> **Цель:** шаг 2 демо — **трейсы LLM-вызовов** (промпты, ответы, задержки, стоимость/токены, оценки)
> на своём стеке, с одного адреса и через SSO стенда.
> **Внешнее имя:** `lng.demo-ai-lab.ru` (короткое имя `lng`, клиент Keycloak — `lng`).
> **Механизм развёртывания:** Argo CD, каталог `gitops/infra-apps/langfuse/` (plain-манифесты, чарт
> рендерится локально); ClusterIP-стек внутри ns `langfuse`, Secret — до первого синка, в git не попадает.
> **Требование владельца:** Langfuse переносится из «опционально шаг 3, если останется RAM» в **шаг 2**
> (`README.md`, `references/demo-plan.md`).

Стиль-образцы: `k8s-install-spec.md` (F\*), `keycloak-spec.md` (K\*), `mcp-registry-spec.md` (M\*),
`ysearch-spec.md` (Y\*). Эта спека занимает букву **L**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Приложение | **Langfuse OSS** (MIT) **v4.70.1** — чарт `langfuse` **2.1.7** (appVersion 4.70.1), OCI `ghcr.io/langfuse/langfuse-k8s/charts/langfuse` (дайджест чарта `sha256:8833cd38…`) | LTS-соответствие чарт↔приложение; свежий релиз 4.71.0 не берём — чарт тестирован на 4.70.1 |
| Образы | web `docker.io/langfuse/langfuse:4.70.1` — индекс `sha256:71b04842…`, amd64 `sha256:047d9fba…`, 288,5 MiB/17 слоёв; worker `docker.io/langfuse/langfuse-worker:4.70.1` — индекс `sha256:3976a73d…`, amd64 `sha256:f0e5a5bf…`, 351,3 MiB/7 слоёв | `crane digest/manifest`, 2026-10-29. `docker.langfuse.com/*` — **это редирект на Docker Hub** (307 → `registry-1.docker.io`), пины берём с `docker.io` |
| Namespace | `langfuse` (каталог `gitops/infra-apps/langfuse/`) | сервис с собственными БД/хранилищами → `infra-apps`, не `apps/` (правило скилла/`gitops/README.md`) |
| Состав | Deployment `langfuse-web`, Deployment `langfuse-worker`, PostgreSQL 18 (subchart, StatefulSet ×1), Valkey 8 (subchart, Deployment ×1), SeaweedFS 4.23 all-in-one (subchart, Deployment ×1 + PVC), **ClickHouse 26.4 — свой StatefulSet ×1** | состав чарта; ClickHouse выносим из оператора (ниже) |
| **ClickHouse** | **свой single-node STS** (`clickhouse/clickhouse-server:26.4`, amd64 `sha256:10c8dfc3…`, 245,5 MiB/11 слоёв), `clickhouse.deploy=false`, `clickhouse.host=langfuse-clickhouse`, `clickhouse.cluster.enabled=false` | штатный путь чарта 2.x — `ClickHouseCluster`/`KeeperCluster` через **cluster-wide оператор** (`oci://ghcr.io/clickhouse/clickhouse-operator-helm` 0.0.8) + CRD + cert-manager-webhook: ещё одна cluster-scoped установка вне Argo и CR в git, которые оператор мутирует (selfHeal → вечный OutOfSync). Чарт официально поддерживает внешний некластерный CH; v4 требует CH ≥ 25.12 (26.4 — рекомендованная) |
| Размещение | **k8s-01**, `nodeAffinity.preferred` (weight 100, `kubernetes.io/hostname In [k8s-01]`) — hard-pin не ставим | 30,5 GiB allocatable, занято 5,8 Gi — единственный узел с запасом (02/03: 46 %/64 %); §5 `ARCHITECTURE.md` уже отводит Langfuse на k8s-01. k8s-01 вне пула Longhorn → тома создаются на 02/03/04 |
| Ресурсы | web/worker req `200m/512Mi`, lim `1536Mi`; PostgreSQL req `100m/256Mi`, lim `1Gi`; Valkey req `50m/128Mi`, lim `512Mi`; SeaweedFS req `100m/256Mi`, lim `2 CPU`/`1Gi`; ClickHouse req `500m/1Gi`, lim `2Gi` | сумма req ≈ 2,7 Gi, lim ≈ 7,6 Gi (на k8s-01 это нормально); `resources` у чарта по умолчанию пустые → уехали бы в BestEffort |
| Тома (Longhorn, r=2) | PG `8Gi`, Valkey `1Gi`, SeaweedFS `5Gi`, ClickHouse `20Gi` = **34Gi** → ~68Gi в пуле | дефолты чарта 20+8+50=78Gi (×2 = 156Gi) — избыточно; свободно ~241 GiB на каждом из 02/03/04 |
| PriorityClass | `demo-stand-critical` (web, worker, ClickHouse) | объект уже создан каталогом `keycloak`, свой не дублируем (Argo-конфликт на кластерном объекте) |
| TLS / Ingress | `Certificate lng-demo-tls` + `Ingress lng` **в ns `langfuse`**, класс `higress`, `/` → `langfuse-web:3000` | правило E-серии: серт живёт в ns Ingress'а; чартовый Ingress не включаем (`langfuse.ingress.enabled=false`) |
| Публичность | весь хост, данные — за логином Langfuse; **SSO без EE-лицензии** | SSO на демо — обязательное требование владельца; см. §5 |
| SSO | **нативный OIDC-провайдер `keycloak`** чарта (`langfuse.auth.providers.keycloak` → `AUTH_KEYCLOAK_*`), клиент Keycloak `lng` (confidential, standard flow, redirect `https://lng.demo-ai-lab.ru/api/auth/callback/keycloak`, PKCE S256) | сверено по исходникам v4.71.0 (`web/src/server/auth.ts`, `getSignInPageServerSideProps.ts`): провайдер регистрируется по наличию env, **без проверки лицензии**; отдельный «EE-адаптер» не нужен |
| Локальный вход | **оставлен** (`disableUsernamePassword: false`) — запасной путь, как у `spk` | решение владельца по `spk` 28.10.2026: если IdP лёг, демо не встаёт |
| Bootstrap | `LANGFUSE_INIT_*` (org `demo`, project `demo`/`step2-tracing`, ключи `pk-lf-…`/`sk-lf-…`, админ `admin@demo-ai-lab.ru`) из Secret через `langfuse.additionalEnv` | без UI-мастеров и без ручных кликов на сцене; работает и при выключенной регистрации |
| Секреты | один Secret `langfuse-secrets` (19 ключей, см. §3); создаёт `scripts/langfuse_secrets.sh`; приватный файл `langfuse-admin.local.md` | все `existingSecret`/`secretKeyRef` → в git только имена ключей |
| Деплой | локальный рендер в plain-манифесты + **пост-фильтр** (§4: 3 объекта удалить, Job → PostSync), деплой — Argo CD | у ApplicationSet `apps`/`infra-apps` нет helm-источника; `lookup` в `helm template` не работает → все креды пиннятся (иначе соль/ключи менялись бы на каждом синке) |
| S3 | встроенный SeaweedFS all-in-one, бакет `langfuse` | v4 пишет входящие события **сначала в S3**, потом worker разбирает их в ClickHouse — S3 не опция, а рабочая зависимость |
| Бэкап | PostgreSQL — `pg_dump` вне репо; ClickHouse/PV — снапшот Longhorn перед апгрейдом | трейсы демо регенерируемы, состояние аккаунтов — в PostgreSQL |

## 2. Предпосылки — проверено 2026-10-29

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl version -o json | jq -r .serverVersion.gitVersion   # v1.35.9
helm version --short                                        # v4.1.3+gc94d381
kubectl get crd | grep -c clickhouse                        # 0 (оператор не нужен — своё решение)
kubectl get nodes -o custom-columns='NODE:.metadata.name,RAM:.status.allocatable.memory'
kubectl top nodes
kubectl get sc,ingressclass,priorityclass
kubectl -n longhorn-system get nodes.longhorn.io -o json     # свободно по ~241 GiB на 02/03/04, 01 — SCHED=false
crane digest docker.io/langfuse/langfuse:4.70.1
crane digest --platform linux/amd64 clickhouse/clickhouse-server:26.4
helm template langfuse <chart> -n langfuse -f values.yaml    # рендер дважды → побайтово одинаков после фильтра
```

| Факт | Значение (замер) |
|---|---|
| Кластер | Kubernetes **v1.35.9** (чарту нужно ≥ 1.28), helm **v4.1.3** — **рендер чарта 2.1.7 проходит без ошибок** (в отличие от `gpustack-chart`, где совместимость с helm 4 не заявлена) |
| cert-manager | CRD `certificates.cert-manager.io`/`issuers.cert-manager.io` есть, 3 пода Running — нужны только если пойдём путём clickhouse-operator (не наш путь) |
| ClickHouse CRD | отсутствуют (`grep clickhouse` = 0) — наш путь от них не зависит |
| Ноды | 01: 30,5 GiB allocatable / 5,8 Gi занято · 02: 14,8/7,0 · 03: 14,8/9,7 (64 %) · 04: 29,5/12,9 |
| StorageClass | `longhorn` (default, r=2); k8s-01 `allowScheduling=false` |
| IngressClass / PriorityClass | `higress`; `demo-stand-critical` (100000) |
| Образы (вес) | langfuse 288,5 MiB · worker 351,3 MiB · clickhouse-server 245,5 MiB · postgres:18 155 MiB · valkey:8.0 41,7 MiB · seaweedfs:4.23 95,9 MiB ≈ **1,18 GiB** → на канале 2–5 МБ/с 4–10 мин |
| Реестр | с k8s-01: `https://docker.langfuse.com/v2/` → **307 → `registry-1.docker.io`** (образы живут на Docker Hub), `ghcr.io` → 401 (доступен) |
| Рендер | `helm template` даёт 28 документов: 2 — комментарии без объектов, 2 Secret'а (`langfuse-s3-sftp-secret`, пустой `langfuse-app`) и test-под убираем → **23 объекта**: Deployment ×4, StatefulSet ×1 (PostgreSQL), PVC ×2 (Valkey 1Gi, SeaweedFS 5Gi), Service ×4, ConfigMap ×4, ClusterRole+Binding (SeaweedFS), SA ×3, PDB ×2, Job ×1 (бакет) |
| Детерминизм | два прогона `helm template` **побайтово равны** после удаления двух объектов (`langfuse-s3-sftp-secret`, пустой `langfuse-app`) — это и есть проверка, что `lookup`-креды не «поплывут» в Argo |
| Env пода web (рендер) | `AUTH_KEYCLOAK_{CLIENT_ID,CLIENT_SECRET,ISSUER,ID_TOKEN,SCOPE,NAME}` · `CLICKHOUSE_URL=http://langfuse-clickhouse:8123` · `CLICKHOUSE_MIGRATION_URL=clickhouse://langfuse-clickhouse:9000/default` (креды — из `CLICKHOUSE_USER/PASSWORD`, как в штатном рендере с оператором) · `CLICKHOUSE_CLUSTER_ENABLED=false` · `NEXTAUTH_URL=https://lng.demo-ai-lab.ru` |
| Требования продукта | PG ≥ 15 (рекомендовано 16; чарт ставит `postgres:18`) · ClickHouse ≥ 25.12 (26.4) · Redis ≥ 7 (Valkey 8) |
| SSO в OSS | проверено по исходникам **v4.71.0**: `web/src/server/auth.ts` регистрирует `KeycloakProvider` при наличии `AUTH_KEYCLOAK_CLIENT_ID/SECRET/ISSUER` без проверки лицензии; в списке EE-фич (`self-hosting/license-key`) SSO **отсутствует**; EE = project-RBAC, retention, audit logs, server-side masking, UI-кастомизация, `allowedOrganizationCreators`, multi-tenant SSO (домен→IdP) |
| Грабля регистрации SSO | `AUTH_DISABLE_SIGNUP=true` (или `signUpDisabled: true`) ломает **и** SSO-вход нового пользователя: адаптер `createUser` бросает `Sign up is disabled.` → на демо регистрацию оставляем включённой |
| Грабля Keycloak в адаптере | стирание `refresh_expires_in`/`not-before-policy` перед записью account — в коде есть (`auth.ts`, `linkAccount`), спец-обход не нужен |

## 3. Секреты

| Приватный файл (вне git, `0600`) | Что внутри | Кто читает |
|---|---|---|
| `langfuse-admin.local.md` | `admin-email`, `admin-password`, `project-public-key` (`pk-lf-…`), `project-secret-key` (`sk-lf-…`), `keycloak-client-secret` | `scripts/langfuse_secrets.sh`, приёмка L7 |

- `.gitignore`: широкое правило `*.local.md` покрывает; приёмка — `git check-ignore -v langfuse-admin.local.md`.
- `scripts/langfuse_secrets.sh` (`--init` создаёт шаблон, значения не печатает) создаёт ns `langfuse` и **один**
  Secret `langfuse-secrets` — этого требует чарт («один Secret для Langfuse и всех sub-chart'ов»,
  `examples/minimal-installation/secret.yaml`):

| Ключ | Для чего |
|---|---|
| `salt`, `encryption-key` (`openssl rand -hex 32`), `nextauth-secret` | приложение (`langfuse.salt`/`encryptionKey`/`nextauth.secret`) — **не ротировать**: меняет хеши API-ключей и делает расшифровку старых данных невозможной |
| `postgresql-password`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `USERDB_USER`, `USERDB_PASSWORD` | Langfuse + `groundhog2k/postgres` (одна и та же БД) |
| `clickhouse-password` | свой STS ClickHouse + `clickhouse.auth.existingSecret` |
| `redis-password`, `default` | Langfuse + Valkey ACL (ключ = имя ACL-пользователя) |
| `s3-user`, `s3-password`, `seaweedfs_s3_config` (IAM-JSON) | SeaweedFS-шлюз и Langfuse (`LANGFUSE_S3_*`) |
| `keycloak-client-secret` | секрет клиента `lng` (значение берётся из `keycloak-clients.local.md` после сида) |
| `init-public-key`, `init-secret-key`, `admin-password` | `LANGFUSE_INIT_*` (проект + админ) |

- Скрипт пишет сгенерированные значения в `langfuse-admin.local.md`, `secret apply` — из файла
  (`kubectl -n langfuse create secret generic langfuse-secrets --from-env-file=… --dry-run=client -o yaml | kubectl apply -f -`).
- Ротация: `postgresql/redis/clickhouse/s3` — обновить ключ в файле → скрипт → рестарт подов;
  `salt`/`encryption-key`/`nextauth-secret` — **не ротировать на демо** (последствие: все API-ключи и
  зашифрованные поля инвалидируются).

## 4. Развёртывание (`gitops/infra-apps/langfuse/`)

| Файл | Содержимое |
|---|---|
| `10-clickhouse.yaml` | StatefulSet `langfuse-clickhouse` (образ `clickhouse/clickhouse-server:26.4` по digest, 1 реплика, `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1`, пароль из Secret, PVC 20Gi `/var/lib/clickhouse`, пробы `GET /ping`) + Service `langfuse-clickhouse` 8123/9000 + PriorityClass/affinity |
| `20-langfuse.yaml` | результат `helm template` чарта 2.1.7 по `gitops/values/langfuse.yaml` **после пост-фильтра** (см. ниже): web, worker, PostgreSQL, Valkey, SeaweedFS, ConfigMap'ы, PDB |
| `30-ingress.yaml` | `Certificate lng-demo-tls` (ClusterIssuer `letsencrypt-wildcard`) + `Ingress lng` (`/` → `langfuse-web:3000`) |
| `README.md` | runbook каталога: порядок, волны, пост-фильтр, смоук, откат (обязателен по правилу класса) |
| `gitops/values/langfuse.yaml` | values чарта (источник рендера; в каталог приложения **не** кладём — Argo применит их как объект) |

**Пост-фильтр рендера (обязателен, иначе Argo «пилит» кластер):**

| Объект из `helm template` | Что делаем | Почему |
|---|---|---|
| `Secret langfuse-s3-sftp-secret` | **удалить** | рендерится при `allInOne.enabled` даже при выключенном SFTP; пароли + SSH-ключ генерируются `lookup`'ом → новые на каждом синке |
| `Secret langfuse-app` | **удалить** (в рендере пустой `data:`) | все три ключа пиннятся на `langfuse-secrets` |
| `Pod langfuse-redis-test-auth-existing` | **удалить** | helm-test-хук (`helm.sh/hook: test`), Argo создаст его как обычный под |
| `Job langfuse-bucket-hook` | аннотации `helm.sh/hook` → `argocd.argoproj.io/hook: PostSync` + `hook-delete-policy: HookSucceeded` | Argo не понимает `helm.sh/hook`; без правки Job пытается создать бакет до готовности SeaweedFS |

Ключевые фрагменты:

```yaml
# gitops/values/langfuse.yaml — существенное (значения сверены рендером в §2)
langfuse:
  image: {tag: "4.70.1", pullPolicy: IfNotPresent}
  nextauth: {url: https://lng.demo-ai-lab.ru,
             secret: {secretKeyRef: {name: langfuse-secrets, key: nextauth-secret}}}
  salt:          {secretKeyRef: {name: langfuse-secrets, key: salt}}
  encryptionKey: {secretKeyRef: {name: langfuse-secrets, key: encryption-key}}
  features: {telemetryEnabled: false, signUpDisabled: false}   # signup=false ломает вход новых SSO-юзеров
  auth:
    disableUsernamePassword: false                              # запасной локальный вход (как spk)
    providers:
      keycloak:
        clientId: lng
        clientSecret: {secretKeyRef: {name: langfuse-secrets, key: keycloak-client-secret}}
        issuer: https://auth.demo-ai-lab.ru/realms/dev
        name: Keycloak
        idToken: "true"                # дефолт env.mjs; явно — чтобы не зависеть от версии
        scope: "openid email profile"
        allowAccountLinking: "true"     # иначе вход под email, созданным через LANGFUSE_INIT_*
        clientAuthMethod: client_secret_post
  resources: {requests: {cpu: 200m, memory: 512Mi}, limits: {memory: 1536Mi}}
  priorityClassName: demo-stand-critical
  affinity: {nodeAffinity: {preferredDuringSchedulingIgnoredDuringExecution:
    [{weight: 100, preference: {matchExpressions:
      [{key: kubernetes.io/hostname, operator: In, values: [k8s-01]}]}}]}}
  additionalEnv:   # bootstrap без UI
    - {name: LANGFUSE_INIT_ORG_ID, value: demo}
    - {name: LANGFUSE_INIT_ORG_NAME, value: "Demo AI Lab"}
    - {name: LANGFUSE_INIT_PROJECT_ID, value: demo}
    - {name: LANGFUSE_INIT_PROJECT_NAME, value: "step2-tracing"}
    - {name: LANGFUSE_INIT_PROJECT_PUBLIC_KEY, valueFrom: {secretKeyRef: {name: langfuse-secrets, key: init-public-key}}}
    - {name: LANGFUSE_INIT_PROJECT_SECRET_KEY, valueFrom: {secretKeyRef: {name: langfuse-secrets, key: init-secret-key}}}
    - {name: LANGFUSE_INIT_USER_EMAIL, value: admin@demo-ai-lab.ru}
    - {name: LANGFUSE_INIT_USER_NAME, value: "Demo Admin"}
    - {name: LANGFUSE_INIT_USER_PASSWORD, valueFrom: {secretKeyRef: {name: langfuse-secrets, key: admin-password}}}
  web: {deployment: {strategy: {type: Recreate}}}
  worker: {replicas: 1}

postgresql:
  deploy: true
  auth: {existingSecret: langfuse-secrets,
         secretKeys: {userPasswordKey: postgresql-password, adminPasswordKey: postgresql-password}}
  settings:     {existingSecret: langfuse-secrets}   # POSTGRES_* — иначе валидация чарта падает
  userDatabase: {existingSecret: langfuse-secrets}   # USERDB_*
  image: {tag: "18"}
  storage: {requestedSize: 8Gi}

redis:
  deploy: true
  auth: {existingSecret: langfuse-secrets, existingSecretPasswordKey: redis-password,
         usersExistingSecret: langfuse-secrets}     # ACL: ключ = имя пользователя (`default`)
  dataStorage: {requestedSize: 1Gi}

clickhouse:
  deploy: false                                     # свой STS, без clickhouse-operator
  host: langfuse-clickhouse
  database: default
  auth: {username: langfuse, existingSecret: langfuse-secrets, existingSecretKey: clickhouse-password}
  migration: {url: "clickhouse://langfuse-clickhouse:9000/default"}   # креды берутся из CLICKHOUSE_USER/PASSWORD
  cluster: {enabled: false}
  keeper: {enabled: false}

s3:
  deploy: true
  bucket: langfuse
  auth: {existingSecret: langfuse-secrets, rootUserSecretKey: s3-user, rootPasswordSecretKey: s3-password}
  allInOne:
    data: {size: 5Gi}
    resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 1Gi}}
    s3: {existingConfigSecret: langfuse-secrets}     # IAM-JSON под ключом seaweedfs_s3_config
```

```yaml
# 10-clickhouse.yaml — суть
kind: StatefulSet
spec:
  replicas: 1
  template:
    spec:
      priorityClassName: demo-stand-critical
      containers:
        - name: clickhouse
          image: clickhouse/clickhouse-server:26.4@sha256:10c8dfc3…   # amd64
          env:
            - {name: CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT, value: "1"}
            - {name: CLICKHOUSE_SKIP_USER_SETUP, value: "0"}
            - name: CLICKHOUSE_PASSWORD
              valueFrom: {secretKeyRef: {name: langfuse-secrets, key: clickhouse-password}}
          readinessProbe: {httpGet: {path: /ping, port: http}}
          volumeMounts: [{name: data, mountPath: /var/lib/clickhouse}]
  volumeClaimTemplates: [{metadata: {name: data}, spec: {storageClassName: longhorn,
                          resources: {requests: {storage: 20Gi}}}}]
```

- **Почему без оператора.** Чарт 2.x штатно ставит `ClickHouseCluster`/`KeeperCluster` через cluster-wide
  оператор (+CRD, +cert-manager webhook). Для стенда это: установка вне Argo, CR в git, которые оператор
  мутирует (finalizers/status) → при selfHeal без `ignoreDifferences` (у ApplicationSet их задать негде)
  получим вечный OutOfSync, плюс лишняя ось апгрейда. Наш STS — 30 строк, один под, без Keeper: Langfuse
  официально поддерживает внешний некластерный CH (`clickhouse.cluster.enabled=false`), а
  `LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED=false` оставляет миграции схемы на старте web.
- **Почему `migration.url` без пароля.** Креды миграций Langfuse берёт из `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD`
  (так же устроен штатный рендер с оператором: `clickhouse://…-headless:9000` без кредов); вписать пароль в URL
  в values нельзя — уехал бы в git. Переопределять `CLICKHOUSE_MIGRATION_URL` через `additionalEnv` **нельзя**:
  чарт валидирует «одно из двух» и падает на рендере.
- **Секрет до первого синка**, иначе под висит в `CreateContainerConfigError` и это читается как «не стартует».
- Рендер: `helm template langfuse oci://ghcr.io/langfuse/langfuse-k8s/charts/langfuse --version 2.1.7 -n langfuse -f gitops/values/langfuse.yaml > 20-langfuse.yaml`
  (с `--api-versions` не нужно: `clickhouse.deploy=false`).

## 5. Домен, SSO и учётные записи

**Клиент Keycloak `lng`** — уже заведён в `scripts/keycloak_seed.py` (`client_payloads()`, create-or-update;
накатывается прогоном сида на L5, секрет попадает в `keycloak-clients.local.md`):

```python
{
    "clientId": "lng",
    "name": "Langfuse (шаг 2, SSO)",
    "publicClient": False,
    "standardFlowEnabled": True,
    "directAccessGrantsEnabled": False,
    "serviceAccountsEnabled": False,
    "protocol": "openid-connect",
    "redirectUris": ["https://lng.demo-ai-lab.ru/api/auth/callback/keycloak"],
    "webOrigins": ["https://lng.demo-ai-lab.ru"],
    "attributes": {"pkce.code.challenge.method": "S256"},
}
```

| Что | Значение / правило |
|---|---|
| Redirect URI | `/api/auth/callback/keycloak` — путь next-auth для провайдера `keycloak` (не угадывать: после смены версии сверить `GET /api/auth/providers`) |
| PKCE | next-auth по умолчанию шлёт `checks=["pkce","state"]`; клиент создаём с `pkce.code.challenge.method=S256`. Если Keycloak ответит ошибкой по `code_challenge` — запасной вариант `AUTH_KEYCLOAK_CHECKS=state` в values |
| Issuer | `https://auth.demo-ai-lab.ru/realms/dev` — **внешний URL**, а не кластерный: `iss` в токенах Keycloak считается от hostname. Из пода discovery-документ доступен через Higress (так же работает `owu`) |
| `clientAuthMethod` | `client_secret_post` (явно; Keycloak принимает и `basic`) |
| Секрет клиента | из `keycloak-clients.local.md` (создаёт сид) → в `langfuse-secrets:keycloak-client-secret` |
| Выход | локальный (next-auth чистит cookie); `post.logout.redirect.uris` клиенту не нужен — в отличие от `gps` |
| Новые пользователи | первый вход через SSO создаёт аккаунт **только если** `signUpDisabled: false`. Орг-приглашения нет — новый SSO-пользователь получает свою организацию; для демо достаточно входить админом/`admin-test` |
| Связка с bootstrap-админом | если SSO-email совпадает с `LANGFUSE_INIT_USER_EMAIL`, нужен `allowAccountLinking: "true"`, иначе next-auth отдаст `OAuthAccountNotLinked` |
| Роли | владелец/админ/участник организации — OSS; **project-RBAC, retention, audit logs, masking, UI-кастомизация — только EE-лицензия** (на демо не нужны, ключ не вводим) |

Приёмка SSO — без браузера, на уровне API:

```bash
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s https://lng.demo-ai-lab.ru/api/auth/providers \
  | python3 -m json.tool          # должен быть провайдер "keycloak" с callbackUrl .../api/auth/callback/keycloak
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s -o /dev/null -w '%{http_code}\n' \
  https://lng.demo-ai-lab.ru/api/auth/signin    # 200 — страница входа с кнопкой «Sign in with Keycloak»
```

### 5.1 Трассы из Open WebUI (`owu`) — то, что показываем

Канонический источник трасс на сцене — **Filter Function `Langfuse`** в Open WebUI (дока OWU,
`tutorials/integrations/monitoring/langfuse`): фильтр в `inlet` открывает generation, в `outlet`
закрывает его с токенами и латентностью; вход/выход, пользователь и чат уходят в Langfuse.

| Что | Значение |
|---|---|
| Установка | Admin Panel → Functions → New Function → вставить код фильтра → Save (OWU сам ставит `langfuse~=3.11` из frontmatter-requirements) |
| Valves | `public_key` = `pk-lf-…`, `secret_key` = `sk-lf-…` (из `langfuse-admin.local.md`), `host` = `https://lng.demo-ai-lab.ru` |
| Сеть | под `owu` ходит на `lng.` через Higress/ingress-VIP (как на `auth.`), отдельный egress не нужен |
| Если pip отключён | `ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false`/`OFFLINE_MODE` → пакет `langfuse` ставить в окружение OWU заранее (правка образа/values — отдельная задача `owu-spec.md`) |
| Приёмка | один чат в OWU → в Langfuse появляется trace с generation, токенами и латентностью; при отсутствии — смотреть лог фильтра в OWU и `/api/public/traces` |

Запасные пути (если фильтр недоступен): SDK-скрипт `scripts/langfuse_smoke.py` (L7) и OTLP-эндпоинт
`/api/public/otel/v1/traces` (требует агента с семантическими конвенциями).

## 6. Фазы L1–L7 (каждая — приёмка командами)

### L1 — секреты и namespace

```bash
./scripts/langfuse_secrets.sh --init     # langfuse-admin.local.md (0600)
# заполнить keycloak-client-secret (из keycloak-clients.local.md), сгенерировать pk-lf-/sk-lf-
./scripts/langfuse_secrets.sh            # ns langfuse + Secret langfuse-secrets (19 ключей)
kubectl -n langfuse get secret langfuse-secrets -o jsonpath='{.data}' | python3 -c 'import json,sys;print(sorted(json.load(sys.stdin)))'
```
Ожидаемо: 19 ключей (`admin-password`, `clickhouse-password`, `default`, `encryption-key`,
`init-public-key`, `init-secret-key`, `keycloak-client-secret`, `nextauth-secret`, `postgresql-password`,
`redis-password`, `salt`, `s3-password`, `s3-user`, `seaweedfs_s3_config`, `POSTGRES_DB`, `POSTGRES_PASSWORD`,
`POSTGRES_USER`, `USERDB_PASSWORD`, `USERDB_USER`), значений в выводе нет.

### L2 — ClickHouse

```bash
kubectl -n langfuse apply -f gitops/infra-apps/langfuse/10-clickhouse.yaml
kubectl -n langfuse rollout status sts/langfuse-clickhouse --timeout=300s
kubectl -n langfuse exec sts/langfuse-clickhouse -- clickhouse-client -q 'SELECT version()'
kubectl -n langfuse run chprobe --rm -it --restart=Never --image=curlimages/curl -- \
  curl -s http://langfuse-clickhouse:8123/ping
```
Ожидаемо: `26.4.x…`, `/ping` → `Ok.`

### L3 — рендер и деплой стека

```bash
helm template langfuse oci://ghcr.io/langfuse/langfuse-k8s/charts/langfuse --version 2.1.7 \
  -n langfuse -f gitops/values/langfuse.yaml > gitops/infra-apps/langfuse/20-langfuse.yaml
# пост-фильтр: удалить Secret langfuse-s3-sftp-secret и langfuse-app, Pod redis-test; Job → argocd.argoproj.io/hook: PostSync
kubectl -n langfuse apply -f gitops/infra-apps/langfuse/     # либо git push → Application langfuse
kubectl -n langfuse get pods,sts,pvc
```
Ожидаемо: `langfuse-web` `1/1 Running`, `langfuse-worker` `1/1`, `langfuse-postgresql-0` `1/1`,
`langfuse-redis` и `langfuse-s3-all-in-one` `1/1`; PVC Bound (8/1/5/20 Gi).

### L4 — миграции, бакет, bootstrap

```bash
kubectl -n langfuse logs deploy/langfuse-web | grep -iE 'migrat|langfuse init|bootstrap' | tail -20
kubectl -n langfuse exec deploy/langfuse-web -- wget -qO- localhost:3000/api/public/health   # 200
kubectl -n langfuse exec deploy/langfuse-web -- wget -qO- localhost:3000/api/public/ready     # 200
kubectl -n langfuse get job langfuse-bucket-hook    # Complete (Argo: PostSync-хук)
```
Ожидаемо: миграции PostgreSQL и ClickHouse отработали без ошибок, health/ready = 200, бакет `langfuse` создан,
организация `demo` + проект `step2-tracing` + пара API-ключей существуют (проверка — L7).

### L5 — SSO: клиент `lng` и вход

```bash
python3 scripts/keycloak_seed.py                       # upsert клиента lng (PKCE S256, redirect) — клиент уже в сиде
./scripts/langfuse_secrets.sh                          # secret обновился секретом клиента
kubectl -n langfuse rollout restart deploy/langfuse-web deploy/langfuse-worker
kubectl -n langfuse exec deploy/langfuse-web -- env | grep AUTH_KEYCLOAK
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s https://lng.demo-ai-lab.ru/api/auth/providers | python3 -m json.tool
```
Ожидаемо: `AUTH_KEYCLOAK_ISSUER=https://auth.demo-ai-lab.ru/realms/dev`, в `/api/auth/providers` есть `keycloak`;
в браузере: кнопка Keycloak → форма IdP → возврат на `/` под пользователем. Локальный вход
(`admin@demo-ai-lab.ru` + пароль из `langfuse-admin.local.md`) продолжает работать.

### L6 — маршрут (LAN и edge)

```bash
kubectl -n langfuse apply -f gitops/infra-apps/langfuse/30-ingress.yaml
kubectl -n langfuse get certificate lng-demo-tls      # Ready=True
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s -o /dev/null -w '%{http_code}\n' https://lng.demo-ai-lab.ru/
curl -s -o /dev/null -w '%{http_code}\n' https://lng.demo-ai-lab.ru/     # через edge (с VM-egress/из LAN по hosts)
```
Ожидаемо: 200/307 (редирект на `/auth/sign-in`), серт LE Ready.

### L7 — сквозная приёмка (то, что показываем)

```bash
# ключи — из langfuse-admin.local.md; URL — через LAN
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s -X POST https://lng.demo-ai-lab.ru/api/public/ingestion \
  -u "pk-lf-…:sk-lf-…" -H 'Content-Type: application/json' \
  -d '{"batch":[{"id":"e1","type":"trace-create","timestamp":"2026-10-29T00:00:00Z",
       "body":{"id":"smoke-1","name":"smoke","timestamp":"2026-10-29T00:00:00Z"}}]}'
curl --resolve lng.demo-ai-lab.ru:443:192.168.10.230 -s -u "pk-lf-…:sk-lf-…" \
  'https://lng.demo-ai-lab.ru/api/public/traces?limit=5'
```
Ожидаемо: `207` (частичные ошибки — читать `errors`), затем трейс `smoke-1` виден в `/api/public/traces`
и в UI (`Traces`) после обработки worker'ом (секунды). Дополнительно: вход через SSO под `admin-test`,
проверка `kubectl -n langfuse logs deploy/langfuse-worker | grep -i ingest`.

**Сценическая приёмка:** один чат в Open WebUI с включённым фильтром Langfuse (§5.1) → trace с
generation, токенами и латентностью виден в `lng.` — это и есть сцена шага 2.

## 7. Операции

| Задача | Как |
|---|---|
| Health | `GET /api/public/health` (web), `GET /api/public/ready` (web, с проверкой зависимостей), `GET /api/health` (worker). `scripts/k8s_health.py` видит поды как обычные |
| Метрики/логи | `kubectl -n langfuse logs deploy/langfuse-web` / `deploy/langfuse-worker`; ClickHouse — `clickhouse-client -q 'SELECT count() FROM system.query_log'` |
| Ротация паролей БД/S3/CH | ключ в `langfuse-admin.local.md` → `./scripts/langfuse_secrets.sh` → `rollout restart` затронутых подов |
| Апгрейд Langfuse | поднять `--version` чарта и `langfuse.image.tag` → перерендерить `20-langfuse.yaml` → пост-фильтр → git push; **сначала** снапшот Longhorn (PG+CH) и `pg_dump` |
| Апгрейд ClickHouse | отдельный шаг: новый STS с тем же PVC (`26.4` → следующая), миграции схемы делает Langfuse при старте; откат — старый образ |
| Бэкап | `pg_dump` (вне репо) + снапшот PV; ClickHouse-историю трейсов не бэкапим (регенерируемо, демо) |
| Удаление | Argo prune снимет Deployment/PVC; Secret `langfuse-secrets` и `langfuse-admin.local.md` удалять руками (не нужны после сноса) |

## 8. Риски

| Риск | Что делаем |
|---|---|
| **R-L1** ClickHouse без оператора — не «официальный» путь чарта | v4 не требует кластера/Keeper для одного узла (`cluster.enabled=false`); миграции проверяются в L4; при проблемах — откат к штатному пути (оператор 0.0.8 + `deploy: true`), он описан в §1 |
| **R-L2** RAM/диск: стек тянет ~2,7 Gi req, 34Gi томов | только k8s-01 с preferred-affinity; при нехватке — первым режем SeaweedFS/PG-limit, потом переносим на k8s-04 (но тогда конкуренция с GPUStack) |
| **R-L3** `lookup`-креды и `randAlphaNum` в чарте | все креды пиннятся на `langfuse-secrets` + пост-фильтр двух объектов; проверка детерминизма рендера — в приёмке (два прогона равны) |
| **R-L4** Регистрация выключена → SSO не создаёт пользователя | `signUpDisabled: false`; при решении закрыть регистрацию — заранее создать нужных пользователей (bootstrap/локальный вход), иначе вход по SSO сломается (§2) |
| **R-L5** PKCE/redirect у Keycloak | клиент создаётся сидом с `pkce.code.challenge.method=S256`; fallback `AUTH_KEYCLOAK_CHECKS=state`; redirect сверяется по `/api/auth/providers` |
| **R-L6** Docker Hub rate limit на анонимные pull (5 образов сразу) | образы предтягиваются на k8s-01 до сцены (L1/L3), теги+digest фиксированы; повторные pull'ы идут из локального кеша containerd |
| **R-L7** Job создания бакета в Argo | `argocd.argoproj.io/hook: PostSync` + `HookSucceeded`; если бакета нет — создать вручную `weed shell` |
| **R-L8** SSO-вход не проверен живьём (в отличие от `spk`/`owu`) | L5 — отдельная приёмка сквозного цикла до демо; без неё на сцене только локальный вход |
| **R-L9** EE-разделение: RBAC/retention/audit/masking недоступны | на демо не нужны; если владелец захочет «роли по проектам» — это EE-лицензия, а не настройка |

## 9. Что забывают в таких спеках + открытые вопросы

| Пункт | Как закрыто здесь |
|---|---|
| Statefull-зависимости «из коробки» чарта требуют `lookup` | один Secret + `existingSecret`/`secretKeyRef` на всё, пост-фильтр (R-L3) |
| S3 в v4 — не опция | SeaweedFS в составе, бакет `langfuse` через PostSync-хук |
| SSO «как у всех» — предположение про EE | сверено по исходникам: OIDC-провайдер OSS, EE — другие фичи (§2/§5) |
| Bootstrap без кликов | `LANGFUSE_INIT_*` + ключи в Secret |
| Порядок «сначала email, потом SSO» | `allowAccountLinking` + `signUpDisabled: false` |
| TLS/серт в чужом ns | свой `Certificate` в ns `langfuse` |
| Пробы: не httpGet на `/` | web `/api/public/health`/`/api/public/ready`, worker `/api/health`, CH `/ping` |

**Открытые вопросы:**

1. **L-O1 — источник трейсов на сцене.** Канонический путь для шага 2 — **Filter Function `Langfuse` в
   Open WebUI** (дока OWU `tutorials/integrations/monitoring/langfuse`): фильтр в `inlet` открывает
   generation, в `outlet` закрывает его с токенами/латентностью, valves — `public_key`/`secret_key`/`host`
   (`https://lng.demo-ai-lab.ru`). Требует пакета `langfuse~=3.11` внутри OWU: поставить через
   Admin Panel → Functions (pip из frontmatter-requirements) либо заранее в образ; при `OFFLINE_MODE`/
   выключенных pip-requirements — ставить пакет в окружение OWU руками. Проверить при приёмке:
   совместимость SDK 3.11 с сервером 4.x (`/api/public/ingestion` стабилен) и egress пода `owu` к `lng.`.
   Запасные пути: SDK-скрипт (`scripts/langfuse_smoke.py`, L7) и OTLP-эндпоинт Langfuse
   (`/api/public/otel/v1/traces`, требует agent'а с семантическими конвенциями) — второй не выбран.
2. **L-O2 — закрывать ли регистрацию.** `signUpDisabled: false` нужен для создания SSO-пользователей, но
   позволяет завести свою организацию любому, у кого есть аккаунт в realm `dev`. Альтернатива: `true` +
   предварительное создание пользователей.
3. **L-O3 — данные трейсов на стенде.** Retention-политики — EE; ограничение объёма — только размером
   PVC и ручной чисткой ClickHouse (`TRUNCATE`/TTL-настройка). Решаем после первых прогонов.
4. **L-O4 — публичность хоста.** По умолчанию публикуем целиком (как `owu`/`spk`); если владелец захочет
   «только LAN» — не заводить Ingress наружу (механика в `external-access-spec.md`).

## 10. Связанные документы и история версий

- `architecture/keycloak-spec.md` — SSO-периметр, realm `dev`, сид клиентов.
- `architecture/endpoints.md` — адрес `lng.demo-ai-lab.ru` и правило коротких имён.
- `references/demo-plan.md` — сценарий шага 2 и RAM/диск-бюджет (Langfuse перенесён из шага 3).
- `gitops/README.md`, `gitops/infra-apps/langfuse/README.md` — runbook деплоя (создаётся на L3).
- `references/service-spec-authoring.md`, `references/gitops-app-deploy.md` — правила класса.

История версий:

- **v1.0** (2026-10-29): первая версия. Сверено живьём: пины образов и чарта (2.1.7 / 4.70.1), детерминизм
  рендера после пост-фильтра, отсутствие гейта лицензии на OIDC-провайдер Keycloak (исходники v4.71.0),
  `AUTH_DISABLE_SIGNUP` ломает создание SSO-пользователя, `docker.langfuse.com` = редирект на Docker Hub,
  helm 4.1.3 рендерит чарт, требования CH ≥ 25.12 / PG ≥ 15.
