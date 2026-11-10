# Каталог скиллов SkillHub с SSO Keycloak (`skh.demo-ai-lab.ru`)

> **Версия:** v1.0 (2026-11-10) · **Статус:** **спека, не установлено** — ни ns `skillhub`, ни клиента
> Keycloak `skh` на стенде нет (замер 2026-11-10, §2).
> **Цель:** шаг 2 демо — **приватный каталог агентских скиллов** (формат SKILL.md): публикация пакетов,
> версии, namespaces с ролями, поиск и установка в агента одной командой; вход — SSO Keycloak,
> пароли и самостоятельная регистрация выключены.
> **Внешнее имя:** `skh.demo-ai-lab.ru` (LAN — split-DNS на `.230`, снаружи — Cloudflare Tunnel).
> **Механизм развёртывания:** Argo CD, каталог `gitops/infra-apps/skillhub/` (plain-манифесты, как
> `mcp-registry/`); Secret'ы создаются **до** первого синка и в git не попадают.
> **Что НЕ делаем:** вызовы скиллов реестр не исполняет (скилл — инструкция + скрипты, которые агент
> запускает у себя), внешние LLM-сканеры скиллов на этом стенде не включаем (§1, R-T6), публичное
> наполнение из интернета не тянем.

Стиль-образцы: `architecture/specs/k8s-install-spec.md` (F\*), `architecture/specs/external-access-spec.md` (E\*),
`architecture/specs/keycloak-spec.md` (K\*), `architecture/specs/mcp-registry-spec.md` (M\*),
`architecture/specs/hermes-spec.md` (H\*). Эта спека занимает букву **T**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Продукт | **SkillHub** `iflytek/skillhub` **v0.2.26** (релиз 2026-11-06, Apache-2.0), self-hosted реестр агентских скиллов | единственный зрелый OSS-реестр формата SKILL.md с RBAC/аудитом и поставкой в K8s; сравнение вариантов — §9 T-O1 |
| Образ server | `ghcr.io/iflytek/skillhub-server:0.2.26` — индекс `sha256:4eeadcfd95375648f23451a47f3351b40b047bd81fcaa3ed2e8e3b1b8e9e97cb`, amd64 `sha256:3a78a95bdf12fc32c87c077a745f7aefe2720270a567dd34ec59082b186bd3dd`, **307 MiB / 9 слоёв** | `crane digest`/`crane manifest --platform linux/amd64`, 2026-11-10; теги `0.2.26` и `v0.2.26` — пин по digest |
| Образ web | `ghcr.io/iflytek/skillhub-web:0.2.26` — amd64 `sha256:571e56f03a4aa87aea62c42600e99f8b423f5e2f5b069323c19a56dfdbd209d9`, **29,1 MiB / 18 слоёв** | UI — отдельный nginx-контейнер, проксирует `/api` на server |
| PostgreSQL | `postgres:16-alpine` — amd64 `sha256:ac838714b7d794185a866e5a6b479b954e7d8a070568aa0acac6fe07c3070bf5`, 110,7 MiB | версия из upstream `compose.release.yml`; тег плавающий — пин по digest на дату установки |
| Redis | `redis:7-alpine` — amd64 `sha256:e4ee3e03ce8f75471f40937a7c6b2b0e500390b6812fcdf5cb32c01295ded446`, 15,7 MiB | сессии (`spring.session`), без PVC: потеря = повторный вход |
| Namespace | `skillhub` (создаёт ApplicationSet `infra-apps` по имени каталога) | один ns на сервис, TLS-секрет в своём ns |
| Состав | Deployment `server` + Deployment `web` + StatefulSet `postgres` + Deployment `redis` + 4 Service + Ingress + Certificate + 2 PVC | состояние — PG + FS-том пакетов; scanner и github-sync **не ставим** |
| Реплики | по **1** на компонент | демо; JVM+PG — SPOF принят (R-T2), как у Keycloak/MCP |
| Размещение | `nodeAffinity.preferred` (weight 100) `demo-ai-lab/role=ingress` → пара k8s-02/03 | ADR-0003: ingress + лёгкие сервисы; свободно 5,4–5,8 GiB на каждой (§2). k8s-05 свободнее, но без role-метки и вне Longhorn-пула — кандидат в T-O4 |
| Ресурсы | server requests `250m/640Mi`, limits `1000m/1536Mi`; web `20m/32Mi` → `200m/128Mi`; PG `100m/256Mi` → `500m/768Mi`; Redis `20m/32Mi` → `200m/128Mi` | образ server — `eclipse-temurin:21-jre`, ENTRYPOINT уже `-XX:MaxRAMPercentage=75` → 1,5 GiB limit = ~1,1 GiB heap; цифры правятся замером `kubectl top` в T4 |
| PriorityClass | `demo-stand-critical` (**существующий**, не создавать) | объект кластерный, дубль в новом каталоге даст конфликт Argo |
| Хранилище пакетов | PVC **5 Gi** `longhorn` (r=2) → `/var/lib/skillhub/storage`, `SKILLHUB_STORAGE_PROVIDER=local` | пакеты скиллов — килобайты–мегабайты; S3/MinIO не заводим (R-T7) |
| БД | PVC **8 Gi** `longhorn`, `PGDATA=/var/lib/postgresql/data/pgdata`, Service **ClusterIP** | подкаталог обязателен (`lost+found` в корне тома), headless даёт «no such host» на первом синке |
| TLS | `Certificate skh-demo-tls` (ClusterIssuer `letsencrypt-wildcard`) в ns `skillhub` | правило E-серии: серт живёт в ns Ingress'а, wildcard из `demo-test` не переиспользуется |
| Ingress | один `Ingress` класс `higress`, host `skh.demo-ai-lab.ru`, path `/` → `web:80` | server:8080 наружу **не публикуем**: единственный вход — web (он же прокси `/api`) |
| Публичность | **весь хост** (как `mcp.`/`doc.`): чтение каталога и UI — публично, запись — только SSO | демо-витрина; админские пути — открытый вопрос T-O2 |
| SSO | Keycloak realm `dev`, клиент **`skh`** (confidential, standard flow), registration id **`keycloak`** | `provider_code` в `identity_binding` = registration id; id `keycloak` даёт брендированную иконку (в образе есть `keycloak-logo.svg`) |
| Допуск в систему | `PROVIDER_ALLOWLIST=keycloak` (только SSO-вход), `password-login=false`, `self-registration=false`, bootstrap-админ **выключен** | закрытый стенд: локальных паролей и регистрации нет; первый админ — грант роли по email (§5.3) |
| Сканер скиллов | `SKILLHUB_SECURITY_SCANNER_ENABLED=false`, контейнер `skillhub-scanner` **не разворачиваем** | сканеру нужен LLM-провайдер (`SKILL_SCANNER_LLM_*`), на стенде это внешний API; включать только с локальной моделью GPUStack — T-O3, R-T6 |
| Built-in скиллы | `SKILLHUB_BUILTIN_SKILLS_ENABLED=true` | каталог не пустой сразу после установки — есть что показать до своей публикации |
| Деплой | Argo CD (`gitops/infra-apps/skillhub/`), волны `-1` (PG, Redis) → `0` (server, web, Ingress, Certificate) | паттерн `mcp-registry/`; Argo не создаёт и не удаляет Secret'ы |
| Шаги демо | часть 2 (простые сервисы), порядок показа — `cases/README.md` | вставка в сценарий — отдельное решение владельца (T-O5) |

**Короткое имя `skh.` — предложение, а не факт.** По правилу `architecture/endpoints.md` имена 3–4 символа;
альтернатива — `skl.`. Имя фиксируется до первого `apply`: переименование после деплоя тянет Ingress +
Certificate + клиента Keycloak + redirect URI.

## 2. Предпосылки — проверено 2026-11-10

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass; kubectl get priorityclass
kubectl get nodes -L demo-ai-lab/role -o custom-columns='N:.metadata.name,RAM:.status.allocatable.memory,ROLE:.metadata.labels.demo-ai-lab/role'
kubectl top nodes
kubectl get ns --no-headers -o custom-columns=:metadata.name | tr '\n' ' '
kubectl get certificate -A | grep -E 'mcp|auth|hm|mon'
dig +short @192.168.10.1 skh.demo-ai-lab.ru                 # → 192.168.10.230 (wildcard split-DNS)
curl -s --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
  https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration | jq -r '.issuer'
crane digest ghcr.io/iflytek/skillhub-server:0.2.26
crane digest --platform linux/amd64 ghcr.io/iflytek/skillhub-web:0.2.26
```

| Факт | Значение (замер) |
|---|---|
| StorageClass / Ingress | `longhorn` default (r=2), `longhorn-static`; `higress` (VIP `192.168.10.230`) |
| Ноды (allocatable) | 01 — 23,2 GiB / 16 CPU; 02 — 14,8 GiB / 12; 03 — 14,8 GiB / 12; 04 — 30,6 GiB / 16; 05 — 14,8 GiB / 16 |
| Занято (`top nodes`) | 01 — 15 873 Mi; 02 — 9 493 Mi; 03 — 9 900 Mi; 04 — 11 908 Mi; 05 — 1 366 Mi |
| Свободно на паре 02/03 | ≈ 5,8 / 5,4 GiB RAM; CPU 2 %; места под новые PVC — Longhorn-пул 02/03/04 |
| Longhorn на k8s-05 | `allowScheduling=false` (нода вне пула реплик) → PVC SkillHub встанут только на 02/03/04 |
| Метки размещения | `demo-ai-lab/role=ingress` — только 02 и 03; у k8s-05 метки роли нет |
| PriorityClass | `demo-stand-critical` (100000) существует (каталог `keycloak`) |
| TLS | ClusterIssuer `letsencrypt-wildcard`; `mcp-demo-tls`/`auth-demo-tls`/`hm`/`mon-demo-tls` — Ready |
| Namespace | `skillhub` **отсутствует** (есть: argocd, cert-manager, demo-test, doc, gpustack, her, higress-system, infra, keycloak, llm, longhorn-system, mcp-registry, monitoring, owu, rag, spk, ysrch, kube-\*) |
| DNS | `skh.demo-ai-lab.ru` уже резолвится в `192.168.10.230` из LAN (regexp-wildcard MikroTik) и проксируется Cloudflare — **правок в DNS/туннеле не требуется** |
| Keycloak | `https://auth.demo-ai-lab.ru/realms/dev`, discovery 200, issuer совпадает с `auth.`; `code_challenge_methods_supported: [plain, S256]` |
| Клиенты realm `dev` | `gps`, `hm`, `mcp`, `owu`, `spk`, `lng`, `agent-runtime`, `smoke-cli`, `llm-*`; **`skh` отсутствует** |
| Пользователи realm `dev` | 22 учётки, **`emailVerified=true` у всех** (в т.ч. `admin-test`, `user-test`, `devrel01…20`) — грабля «SkillHub обнуляет email при `email_verified != true`» на этом realm не срабатывает |
| Образы | server amd64 307,3 MiB / 9 слоёв; web 29,1 MiB / 18 слоёв; PG 110,7 MiB (11 слоёв); Redis 15,7 MiB (7 слоёв) → суммарный pull ≈ 463 MiB, на канале 2–5 МБ/с это 3–4 мин на ноду |
| API/поведение (сверено с v0.2.26) | `GET /api/v1/auth/{methods,providers,me}`, `POST /api/v1/auth/logout`; `/actuator/health` (server:8080), `/nginx-health` (web:80); вход — `authN` через `oauth2Login` + `CustomOidcUserService`; таблицы Flyway (`flyway_schema_history`) |

## 3. Секреты

| Приватный файл (вне git, `0600`) | Что внутри | Кто читает |
|---|---|---|
| skillhub.local.md (создаётся в T2) | `db-name`, `db-username`, `db-password`, `download-anon-cookie-secret` (32 байта), `keycloak-client-secret` | `scripts/skillhub_secrets.sh` |
| `keycloak-clients.local.md` (общий, уже есть) | добавляется `skh-client-secret` | `scripts/keycloak_seed.py` |

- `.gitignore`: правило `*.local.md` покрывает оба файла; приёмка — `git check-ignore -v skillhub.local.md`.
- `scripts/skillhub_secrets.sh` (значения не печатает) создаёт в ns `skillhub`:
  - `Secret skillhub-db` — ключи `db-name`, `db-username`, `db-password` (те же значения уходят в
    `POSTGRES_*` StatefulSet'а и в `SPRING_DATASOURCE_*` server'а);
  - `Secret skillhub-secrets` — ключи `download-anon-cookie-secret`, `keycloak-client-secret`.
- Генерация: `openssl rand -base64 32` (cookie secret) и `openssl rand -hex 24` (клиент Keycloak —
  значение задаётся в Keycloak при создании клиента, в файл пишется то, что выдал сид).
- Ротация cookie secret инвалидирует анонимные download-cookie (каталог цел); ротация клиентского
  секрета требует синхронной правки в Keycloak и в Secret + `rollout restart deploy/server`.
- Гигиена: скрипт идемпотентен, печатает только имена ключей; значения не попадают ни в логи Argo,
  ни в `kubectl describe`.

## 4. Развёртывание (`gitops/infra-apps/skillhub/`)

| Файл | Содержимое | sync-wave |
|---|---|---|
| `10-postgres.yaml` | Service ClusterIP `postgres` + StatefulSet (PG 16-alpine, PVC 8Gi, `PGDATA` подкаталог, `POSTGRES_INITDB_ARGS=--data-checksums`, exec-пробы `pg_isready`) | `-1` |
| `15-redis.yaml` | Deployment `redis` + Service :6379 (`--save ''`, без PVC, `emptyDir` для `/data`) | `-1` |
| `20-server.yaml` | Deployment `server` + Service :8080 + PVC 5Gi → `/var/lib/skillhub/storage` | `0` |
| `30-web.yaml` | Deployment `web` + Service :80 | `0` |
| `40-ingress.yaml` | `Certificate skh-demo-tls` + `Ingress skh` (`skh.demo-ai-lab.ru` → `web:80`) | `0` |
| `README.md` | runbook: файлы/волны, порядок, смоук, грабли, откат | — |

Ключевые фрагменты (полные манифесты — в gitops, здесь — решения):

```yaml
# 20-server.yaml — существенное
spec:
  replicas: 1
  strategy: {type: Recreate}          # одна миграция Flyway за раз
  template:
    spec:
      priorityClassName: demo-stand-critical
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - {key: demo-ai-lab/role, operator: In, values: [ingress]}
      securityContext: {runAsUser: 100, runAsGroup: 101, fsGroup: 101,
                        fsGroupChangePolicy: OnRootMismatch, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: server
          image: ghcr.io/iflytek/skillhub-server:0.2.26@sha256:4eeadcfd95375648f23451a47f3351b40b047bd81fcaa3ed2e8e3b1b8e9e97cb
          ports: [{name: http, containerPort: 8080}]
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true,
                            capabilities: {drop: [ALL]}}
          volumeMounts:
            - {name: storage, mountPath: /var/lib/skillhub/storage}
            - {name: tmp, mountPath: /tmp}          # Tomcat/Spring temp при read-only rootfs
          env:
            - {name: SPRING_PROFILES_ACTIVE, value: "docker"}
            - {name: SPRING_DATASOURCE_URL, value: "jdbc:postgresql://postgres.skillhub.svc:5432/skillhub"}
            - {name: SPRING_DATA_REDIS_HOST, value: "redis.skillhub.svc"}
            - {name: SPRING_DATA_REDIS_PORT, value: "6379"}
            - {name: SKILLHUB_PUBLIC_BASE_URL, value: "https://skh.demo-ai-lab.ru"}
            - {name: SESSION_COOKIE_SECURE, value: "true"}
            - {name: SKILLHUB_ACTUATOR_EXPOSURE_INCLUDE, value: "health,info"}
            - {name: SKILLHUB_STORAGE_PROVIDER, value: "local"}
            - {name: SKILLHUB_AUTH_INITIAL_PASSWORD_LOGIN_ENABLED, value: "false"}
            - {name: SKILLHUB_AUTH_INITIAL_SELF_REGISTRATION_ENABLED, value: "false"}
            - {name: SKILLHUB_ACCESS_POLICY_MODE, value: "PROVIDER_ALLOWLIST"}
            - {name: SKILLHUB_ACCESS_POLICY_ALLOWED_PROVIDERS, value: "keycloak"}
            - {name: SKILLHUB_SECURITY_SCANNER_ENABLED, value: "false"}
            - {name: SKILLHUB_BUILTIN_SKILLS_ENABLED, value: "true"}
            - {name: BOOTSTRAP_ADMIN_ENABLED, value: "false"}
            # --- SSO Keycloak (§5.2) ---
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_CLIENT_ID, value: "skh"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_PROVIDER, value: "keycloak"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_CLIENT_NAME, value: "Keycloak"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_AUTHORIZATION_GRANT_TYPE, value: "authorization_code"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_SCOPE, value: "openid,profile,email"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_KEYCLOAK_REDIRECT_URI, value: "{baseUrl}/login/oauth2/code/{registrationId}"}
            - {name: SPRING_SECURITY_OAUTH2_CLIENT_PROVIDER_KEYCLOAK_ISSUER_URI, value: "https://auth.demo-ai-lab.ru/realms/dev"}
          # shell в образе есть (temurin noble + wget), но пробы — httpGet: короче и без exec-оверхеда
          startupProbe:   {httpGet: {path: /actuator/health, port: http}, periodSeconds: 5, failureThreshold: 60}
          readinessProbe: {httpGet: {path: /actuator/health, port: http}, periodSeconds: 10}
          livenessProbe:  {httpGet: {path: /actuator/health, port: http}, periodSeconds: 20, failureThreshold: 5}
          resources:
            requests: {cpu: 250m, memory: 640Mi}
            limits:   {cpu: "1",  memory: 1536Mi}
      volumes:
        - name: storage
          persistentVolumeClaim: {claimName: skillhub-storage}
        - {name: tmp, emptyDir: {sizeLimit: 512Mi}}
```

```yaml
# 30-web.yaml — существенное
      containers:
        - name: web
          image: ghcr.io/iflytek/skillhub-web:0.2.26@sha256:571e56f03a4aa87aea62c42600e99f8b423f5e2f5b069323c19a56dfdbd209d9
          ports: [{name: http, containerPort: 80}]
          env:
            - {name: SKILLHUB_API_UPSTREAM, value: "http://server.skillhub.svc:8080"}
            - {name: SKILLHUB_TRUST_FORWARDED_PROTO, value: "true"}   # за Higress TLS терминируется на шлюзе
            - {name: SKILLHUB_PUBLIC_BASE_URL, value: "https://skh.demo-ai-lab.ru"}
          readinessProbe: {httpGet: {path: /nginx-health, port: http}, periodSeconds: 10}
          livenessProbe:  {httpGet: {path: /nginx-health, port: http}, periodSeconds: 20, failureThreshold: 5}
          resources:
            requests: {cpu: 20m,  memory: 32Mi}
            limits:   {cpu: 200m, memory: 128Mi}
```

- **Порядок и отказы.** Flyway-миграции применяет сам server на старте; при недоступной БД под падает и
  перезапускается — `startupProbe` с `failureThreshold: 60` (5 мин) это переживает. `Recreate` исключает
  две миграции одновременно.
- **Secret'ы — до первого синка**, иначе под висит в `CreateContainerConfigError` (симптом «server не
  стартует», а не «сломан Argo»).
- **`readOnlyRootFilesystem: false` у web**: entrypoint генерирует `/etc/nginx/conf.d/default.conf` и
  `runtime-config.js` из шаблонов, плюс nginx пишет `/var/cache/nginx` и `/var/run`. Включать read-only
  только с набором `emptyDir` — отдельная правка, не блокер установки.
- **Загрузка пакетов идёт через web → server**: большие пакеты (лимит сканера 105 МБ, у нас сканер выключен)
  упираются в таймауты буферизации Higress/nginx — проверяется в T6 пакетом ~10 МБ, при провале —
  аннотация таймаута на Ingress (R-T5).

## 5. SSO через Keycloak

### 5.1 Клиент в Keycloak

| Параметр | Значение |
|---|---|
| clientId | `skh` (короткое имя хоста — правило §5.3 `keycloak-spec.md`) |
| Тип | **confidential**, `client_secret_basic` (SkillHub — серверное приложение, PKCE не нужен) |
| Flow | Standard flow **on**, Direct access grants **off**, Service accounts **off** |
| Valid redirect URIs | `https://skh.demo-ai-lab.ru/login/oauth2/code/keycloak` (ровно; `localhost` не добавляем) |
| Valid post logout redirect URIs | `https://skh.demo-ai-lab.ru/*` |
| Scopes | `openid`, `profile`, `email` (default client scopes) |
| Секрет | сид пишет в `keycloak-clients.local.md` ключ `skh-client-secret`, в кластер — Secret `skillhub-secrets` |

Клиент добавляется в `scripts/keycloak_seed.py` (idempotent seed — единственный источник правды для
realm/clients, §5.4 `keycloak-spec.md`), таблица §5.3 там же получает строку `skh`. Ручное создание в
Admin Console допустимо только как временная мера — при следующем прогоне сида клиент должен совпасть.

### 5.2 Регистрация OIDC в SkillHub

Отдельного «Keycloak-адаптера» не нужно: SkillHub использует Spring Security OAuth2 Client, а
`CustomOidcUserService` (`server/skillhub-auth/.../oauth/CustomOidcUserService.java`, v0.2.26) —
универсальная OIDC-ветка. Registration id **`keycloak`** (имя в env-переменных — uppercase `KEYCLOAK`,
как предписывает комментарий в `.env.release.example`: «Replace `OIDC` in variable names with your
registration id»). Этот же id становится `identity_binding.provider_code`.

Маппинг claims (проверено по коду):

| Claim Keycloak | Куда | Замечание |
|---|---|---|
| `sub` | `identity_binding.subject` | обязателен; без него вход падает `missing_sub` |
| `preferred_username` → `name` → `email` → `sub` | `identity_binding.login_name` | порядок фиксирован в `toOAuthClaims` |
| `email` | профиль пользователя | **обнуляется, если `email_verified != true`** — на realm `dev` у всех учёток `true` (§2), но новым пользователям ставить галочку «Email verified» обязательно |
| `picture` | `avatar_url` | опционально |

- `issuer-uri` = `https://auth.demo-ai-lab.ru/realms/dev` — Spring сам тянет discovery и JWKS; при
  недоступном Keycloak server падает на старте (проверять на T4 порядок «Keycloak жив → server стартует»).
- Провайдер попадает в UI автоматически: `AuthMethodCatalog.listOAuthProviders()` перечисляет все
  registrations с непустым `clientId`, `/api/v1/auth/methods` отдаёт их список, иконка — `keycloak-logo.svg`.
- Пароли: `password-login=false` + `BOOTSTRAP_ADMIN_ENABLED=false` → локальной формы входа нет вообще
  (проверяется в T5: `/api/v1/auth/methods` не содержит `PASSWORD`).

### 5.3 Первый администратор и политика допуска

- **Bootstrap-админ не включается** (в образе дефолт `admin` / `ChangeMe!2026` — в стенд не тащим).
- Первый супер-админ выдаётся грантом при пустой БД:
  `SKILLHUB_AUTH_INITIAL_ROLE_GRANTS_JSON=[{"provider":"keycloak","email":"<admin>@demo-ai-lab.ru","role":"SUPER_ADMIN"}]`
  (chart: «used only while the database is empty»; повторно не применяется, дальше роли выдаются в UI).
  `provider` — это registration id (`keycloak`), `email` — из ID-token (нужен `email_verified=true`).
- Допуск: `AccessPolicy` в v0.2.26 поддерживает `OPEN` / `EMAIL_DOMAIN` / `PROVIDER_ALLOWLIST` /
  `SUBJECT_WHITELIST`. Ставим `PROVIDER_ALLOWLIST=keycloak`: в систему попадает любой пользователь,
  вошедший через Keycloak (22 учётки realm `dev` — все наши). Ужесточение до `SUBJECT_WHITELIST` —
  одна env-переменная, если понадобится (T-O2).
- Роли SkillHub (`USER` по умолчанию, `SUPER_ADMIN`) живут **внутри** SkillHub: группы Keycloak в роли не
  маппятся — этого в v0.2.26 нет (R-T4).

### 5.4 Чего в этой версии нет (не обещать на демо)

- Несколько IdP и per-organization OIDC (админ-UI «Login connections», JIT, отзыв сессий по членству) —
  это change `enterprise-identity-platform` в апстриме: в v0.2.26 есть только联邦-ядро и таблицы
  (`V62__external_identity_v2_foundation.sql`), флаги `SKILLHUB_ENTERPRISE_OIDC_*` в коде релиза
  отсутствуют. Приедет — отдельная ревизия спеки.
- SAML, LDAP/AD-bind, SCIM — нет в продукте вообще.
- Logout локальный: `/api/v1/auth/logout` чистит сессию SkillHub, SSO-сессия Keycloak остаётся
  (RP-initiated logout не реализован) — R-T3.

## 6. Фазы T1–T8 (каждая — приёмка командами)

### T1 — клиент Keycloak `skh`

```bash
# 1) строка клиента в scripts/keycloak_seed.py (§5.3 keycloak-spec.md), прогон сида
python3 scripts/keycloak_seed.py
# 2) сверка через Admin API (креды — из приватного хранилища, не печатать)
curl -s --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
  -H "Authorization: Bearer $KC_TOKEN" \
  'https://auth.demo-ai-lab.ru/admin/realms/dev/clients?clientId=skh' | jq -r '.[0] | {clientId, publicClient, redirectUris}'
```

Ожидаемо: `clientId=skh`, `publicClient=false`, `redirectUris=["https://skh.demo-ai-lab.ru/login/oauth2/code/keycloak"]`;
секрет появился в `keycloak-clients.local.md` (`git check-ignore -v keycloak-clients.local.md` → правило `*.local.md`).

### T2 — секреты

```bash
bash scripts/skillhub_secrets.sh
kubectl -n skillhub get secret skillhub-db skillhub-secrets
kubectl -n skillhub get secret skillhub-db -o jsonpath='{.data}' | tr ',' '\n' | cut -d'"' -f2
kubectl -n skillhub get secret skillhub-secrets -o jsonpath='{.data}' | tr ',' '\n' | cut -d'"' -f2
```

Ожидаемо: `skillhub-db` → ключи `db-name`, `db-username`, `db-password`; `skillhub-secrets` →
`download-anon-cookie-secret`, `keycloak-client-secret`. Значения не выводятся.

### T3 — манифесты и Argo

```bash
git add gitops/infra-apps/skillhub && git commit -m "feat(gitops): каталог скиллов SkillHub + SSO" && git push
kubectl -n argocd get application skillhub -o jsonpath='{.status.sync.status} {.status.health.status}'
kubectl -n skillhub get pods,pvc,certificate
```

Ожидаемо: `Synced Healthy`; 4 пода `Running` (server, web, postgres-0, redis); оба PVC `Bound`;
`Certificate skh-demo-tls` → `Ready` (LE `YR1`).

### T4 — health, БД, ресурсы

```bash
kubectl -n skillhub port-forward svc/server 18080:8080 & sleep 3
curl -s localhost:18080/actuator/health                        # {"status":"UP"}
curl -s -o /dev/null -w '%{http_code}\n' --resolve skh.demo-ai-lab.ru:443:192.168.10.230 https://skh.demo-ai-lab.ru/nginx-health   # 200
curl -s --resolve skh.demo-ai-lab.ru:443:192.168.10.230 https://skh.demo-ai-lab.ru/api/v1/auth/methods | jq '.data[].provider'
kubectl -n skillhub exec postgres-0 -- psql -U <db-user> -d <db-name> -c 'select count(*) from flyway_schema_history;'
kubectl -n skillhub top pods
```

Ожидаемо: `UP`; `/nginx-health` → 200; в `methods` есть `keycloak` и **нет** `PASSWORD`;
миграций > 0; `top` укладывается в requests/limits из §1 (иначе править §1 по факту).

### T5 — SSO end-to-end

```bash
# 1) браузер (LAN): https://skh.demo-ai-lab.ru/ → «Sign in with Keycloak» → форма realm dev
# 2) после входа:
curl -s -b cookies.txt https://skh.demo-ai-lab.ru/api/v1/auth/me | jq '{provider, roles}'
kubectl -n skillhub exec postgres-0 -- psql -U <db-user> -d <db-name> \
  -c "select provider_code, login_name, created_at from identity_binding;"
kubectl -n skillhub exec postgres-0 -- psql -U <db-user> -d <db-name> \
  -c "select coalesce(a.email,a.display_name) as who, r.code from user_role_binding b \
      join user_account a on a.id=b.user_id join role r on r.id=b.role_id;"
```

Ожидаемо: редирект уходит на `auth.demo-ai-lab.ru`, после возврата `provider=keycloak`; в
`identity_binding` строка `provider_code='keycloak'`; у первого пользователя роль `SUPER_ADMIN`
(грант из §5.3). Проверить, что выданный пользователь — тот, кому грант (email совпал).

### T6 — публикация скилла и установка в Hermes

```bash
# API-токен: UI → Settings → API tokens (или POST /api/v1/tokens), значение в skillhub.local.md
npm i -g @astron-team/skillhub
skillhub login --registry https://skh.demo-ai-lab.ru --token "$SKILLHUB_TOKEN"
skillhub publish ./demo-skill --namespace demo                  # пакет с корневым SKILL.md
skillhub search demo --registry https://skh.demo-ai-lab.ru
# установка в Hermes на Mac (докер-док: --dir в каталог скиллов профиля)
skillhub install demo --namespace demo --dir "$HOME/.hermes/skills/skillhub/demo" \
  --registry https://skh.demo-ai-lab.ru
hermes skills list | grep -i demo
```

Ожидаемо: `push` → версия `1.0.0`; `search` находит; в Hermes появился
~/.hermes/skills/skillhub/demo/SKILL.md и скилл виден в `hermes skills list`; загрузка через UI
пакета ~10 МБ проходит без таймаута (если нет — R-T5).

### T7 — отказ и восстановление

```bash
kubectl -n skillhub delete pod -l app=skillhub-server
kubectl -n skillhub delete pod postgres-0
curl -s -o /dev/null -w '%{http_code}\n' https://skh.demo-ai-lab.ru/nginx-health
kubectl -n skillhub get pods
```

Ожидаемо: server поднимается за десятки секунд (state в PG+Redis); потеря PG — server пережидает и
возвращается после переаттача тома Longhorn (**RTO 1–3 мин**, как у Keycloak/MCP); web продолжает
отдавать статику, `/api` в это время 502–503.

### T8 — возврат (снятие сервиса)

```bash
kubectl -n argocd delete application skillhub          # или убрать каталог из git
kubectl -n skillhub scale deploy/server deploy/web redis --replicas=0   # «пауза» без удаления данных
# полное снятие — отдельной командой владельца: kubectl delete ns skillhub (PVC уйдут с ns)
# Keycloak: клиент skh → enabled=false (сид), секрет остаётся в keycloak-clients.local.md
```

Ожидаемо: после `scale 0` каталог не отдаётся, данные целы; повторный `scale 1` возвращает стенд без
повторной настройки. Полное удаление — только по явной команде (данные в PG-томе невосстановимы без
бэкапа, §7).

## 7. Операции

| Задача | Как |
|---|---|
| Health-смоук | `curl --resolve skh.demo-ai-lab.ru:443:192.168.10.230 https://skh.demo-ai-lab.ru/nginx-health` + `/actuator/health` через `port-forward`; `scripts/k8s_health.py` сервис не проверяет |
| Бэкап | `kubectl -n skillhub exec postgres-0 -- pg_dump -U <user> -Fc <db> > <вне-репо>/skillhub-<дата>.dump`; пакеты — `kubectl -n skillhub exec deploy/server -- tar czf - -C /var/lib/skillhub/storage .` (или снапшот Longhorn) |
| Восстановление | `scale deploy/server --replicas=0` → `pg_restore -c` → вернуть реплики (Argo `selfHeal`, временно снять automated) |
| Апгрейд | сменить тег+digest в `20-server.yaml`/`30-web.yaml` (обе части — одной версией!), `kubectl -n argocd annotate app skillhub argocd.argoproj.io/refresh=hard`; Flyway применит миграции сам; откат — предыдущие digest'ы (перед апгрейдом бэкап) |
| Ротация секретов | cookie secret — правка Secret + `rollout restart deploy/server`; клиент Keycloak — новый секрет в Keycloak и в Secret, рестарт server (иначе 401 на callback) |
| Админ-роли | UI → Members/Admin; грант из §5.3 применяется один раз и только на пустой БД |
| Наблюдение | `/actuator/health`, метрики Prometheus (`/actuator/prometheus` — включить `SKILLHUB_ACTUATOR_EXPOSURE_INCLUDE=health,info,prometheus`, если понадобится); логи — `kubectl logs` (JSON — `SKILLHUB_LOG_FORMAT=json`) |
| Клиентская часть | `skillhub` CLI (npm `@astron-team/skillhub`), REST API `/api/v1/*`; Hermes ставит скиллы через `--dir` |

## 8. Риски

| Риск | Что делаем |
|---|---|
| **R-T1** вендор — iFlytek (КНР), Apache-2.0; для закрытого контура нужна проверка зависимостей | пин по digest, без автообновлений, `--no-scanner`; ревью состава образов (SBOM/`crane ls`) силами ИБ до показа; версия фиксируется в §1 и в git |
| **R-T2** PostgreSQL ×1 и server ×1 — SPOF | принято для демо; `pg_dump` перед показом; RTO 1–3 мин; падение PG = каталог недоступен (Session и данные в одной БД) |
| **R-T3** logout локальный, SSO-сессия Keycloak живёт | не обещать «выход из SSO»; для выхода из Keycloak — отдельный URL realm (или вкладка «выйти везде»); при показе не демонстрировать logout как гарантию |
| **R-T4** группы Keycloak не маппятся в роли SkillHub | роли выдаются в UI SkillHub; `admin-test` — грантом §5.3; в демо не рассказывать про «роли из AD» |
| **R-T5** загрузка пакета идёт web→server через Higress: таймауты/лимиты тела | тест в T6 пакетом ~10 МБ; при провале — аннотации таймаутов (`higress.io/timeout`) и/или прямая публикация через CLI с локального хоста (не через UI) |
| **R-T6** сканер скиллов выключен → нет проверки содержимого пакетов | осознанно: сканер требует внешний LLM; на демо публикуем только свои пакеты; включение — T-O3 (локальная модель GPUStack). Скилл = доверенная инструкция: чужие пакеты в каталог не тянем |
| **R-T7** локальный FS пакетов на RWO-томе (Longhorn r=2) | одна реплика server; при масштабировании — S3/MinIO и `SKILLHUB_STORAGE_PROVIDER=s3` (переезд отдельной фазой) |
| **R-T8** PVC не встанут на k8s-05 (Longhorn `allowScheduling=false`) | размещение — preferred на пару 02/03; если 05 введут в пул, приоритет размещения пересмотреть (T-O4) |
| **R-T9** JVM 1,5 GiB limit и `MaxRAMPercentage=75` — при тяжёлом импорте/поиске возможен OOM | `startupProbe` 5 мин, замер `top` в T4; при OOM — поднять limit до 2 GiB (RAM на 02/03 есть) |
| **R-T10** админские пути (`/admin*`, ревью, токены) публичны вместе с витриной | как у `mcp.` (решение для демо); ужесточение — путь-скоуп `WasmPlugin` (T-O2), не allowlist на весь хост |
| **R-T11** часы узлов vs `exp`/`iat` ID-token | NTP проверить перед T5 (`timedatectl` на 02/03) — расхождение даёт `invalid_token` на callback |

## 9. Что забывают в таких спеках + открытые вопросы

| Пункт | Как закрыто здесь |
|---|---|
| Секреты до первого синка | T2 создаёт Secret'ы до коммита каталога |
| TLS в ns Ingress'а | `Certificate skh-demo-tls` в `skillhub`, не wildcard из `demo-test` |
| Дубль кластерного объекта | `PriorityClass` берём существующий, свой не создаём |
| Headless Service у БД | ClusterIP (иначе «no such host» на первом синке) |
| `lost+found` на томе Longhorn | `PGDATA=/var/lib/postgresql/data/pgdata` |
| Первый админ без пароля | `role-grants-json` + SSO; bootstrap выключен |
| `email_verified` в Keycloak | проверено: realm `dev` — все учётки verified (§2); новым ставить галочку |
| Две части одной версии (web+server) | апгрейд только парой тег+digest (R-T-операции §7) |
| Бэкап перед апгрейдом | `pg_dump` + tar тома вне репо |
| Лимиты LE | серт выпускается один раз; перевыпуск не в цикле |

**Открытые вопросы:**

1. **T-O1 — выбор продукта.** SkillHub взят как единственный зрелый OSS-реестр с RBAC/аудитом и
   K8s-поставкой (Apache-2.0). Альтернативы: ClawHub (MIT, но бэкенд Convex Cloud + внешние
   эмбеддинги для поиска), `npx skills`/`skilly` (реестр = git-репозиторий: нет RBAC, аудита и ревью).
   Если владелец решит закрепить выбор как архитектурное решение — это ADR, а не спека; пока это
   инженерное решение шага 2.
2. **T-O2 — публичность и админ-пути.** Оставляем весь хост публичным (как `mcp.`/`doc.`) или на время показа
   закрываем `/admin*` и `/api/v1/tokens*` путь-скоупом `WasmPlugin`? Влияет и на `PROVIDER_ALLOWLIST`
   (сейчас пускаем всех 22 учёток realm `dev`).
3. **T-O3 — сканер скиллов на локальной модели.** Включить `skillhub-scanner` с `SKILL_SCANNER_LLM_BASE_URL`
   на GPUStack (`api.demo-ai-lab.ru/v1`) — требует проверки, что сканер умеет OpenAI-совместимый протокол
   (по умолчанию `anthropic`); до проверки сканер выключен.
4. **T-O4 — размещение.** Пара 02/03 (5,4–5,8 GiB свободно) или k8s-05 после ввода в Longhorn-пул и выдачи
   role-метки? Сейчас preferred на 02/03.
5. **T-O5 — место в сценарии демо.** Показывать SkillHub в части 2 (после MCP-каталога) или как «агентский»
   сюжет части 4 вместе с Hermes-установкой скилла? Сценарий — `cases/README.md`, правится отдельной правкой.

## 10. Связанные документы и история версий

- `architecture/specs/keycloak-spec.md` §5.3/§5.4 — клиент `skh`, сид, секреты клиентов.
- `architecture/specs/hermes-spec.md` — потребитель скиллов (`hermes skills list`, каталог `$HERMES_HOME/skills`).
- `architecture/specs/mcp-registry-spec.md` — паттерн «каталог шага 2»: plain-манифесты, OIDC Keycloak, витрина на `/`.
- `architecture/specs/external-access-spec.md` §E5/§E9 — туннель, split-DNS, allowlist служебных UI.
- `architecture/endpoints.md` — адрес `skh.demo-ai-lab.ru` и правило коротких имён.
- `gitops/README.md` — паттерн `infra-apps/<имя>` → Application + ns по имени каталога.
- Апстрим: `iflytek/skillhub` v0.2.26 — `README.md`, docs/skillhub/en/guide/deployment.md, `charts/skillhub/values.yaml`,
  docs/hermes-integration-en.md, `.env.release.example` (блок OIDC), `server/skillhub-auth/.../CustomOidcUserService.java`,
  `server/skillhub-app/src/main/resources/application.yml`.

История версий:

- **v1.0** (2026-11-10): первая редакция. Пины (server/web/PG/Redis по digest), состав из 4 подов без сканера,
  SSO через Keycloak (клиент `skh`, registration id `keycloak`, `PROVIDER_ALLOWLIST`, первый админ грантом),
  предпосылки замерены живьём (ноды 01–05, Longhorn-пул, Keycloak realm `dev` и его клиенты/`emailVerified`,
  DNS wildcard, digest'ы образов), фазы T1–T8 с возвратом, риски R-T1…R-T11. Не установлено.
