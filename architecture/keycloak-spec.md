# Спецификация установки Keycloak (SSO) на кластер demo-ai-lab

> **Версия 1.0** (2026-10-24), статус: **спека, не установлено**. Цель — SSO/OIDC-провайдер
> для сервисов стенда: внешнее имя **`https://auth.demo-ai-lab.ru`**, realm **`dev`** с двумя
> учётками (`user-test`, `admin-test`) для приложений шага 2/3.
> **Развёртывание — только через Argo CD** (`gitops/infra-apps/keycloak/` → ApplicationSet
> `infra-apps`): ручных `kubectl apply`/`helm install` для рабочих объектов нет, деплой = git push
> в `main`. Исключение — Secret'ы с паролями: они **не в git** (спека §3) и создаются скриптом
> из приватных файлов до первого sync'а.
> Кластер уже стоит и закрыт `k8s-install-spec.md` (F0–F10) — эта спека ставит сервис в
> существующий кластер, ни одна фаза F не пересматривается.
> Ничего секретного в этом документе нет: пароли — в `keycloak-*.local.md` (в `.gitignore`).

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Keycloak | **26.8.1**, `quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b` (JVM 21.0.12.1) | пин по digest; образ **проверен на стенде 2026-10-24** — пробный под поднялся, `kc.sh --version` → `Keycloak 26.8.1`; реестр `quay.io` с площадки доступен |
| БД | **PostgreSQL 17.11**, `postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe` | digest сверен по Docker Hub API 2026-10-24; `docker.io` тянется с площадки (спека F §9). Pull на ноде — критерий K2 |
| Namespace | `keycloak` (создаётся в K1 руками — Secret'ы нужны до первого sync'а; Argo с `CreateNamespace=true` видит существующий) | один ns на сервис — паттерн `gitops/README.md`; ApplicationSet берёт имя ns из имени каталога |
| Узлы | **пара k8s-02/03**, soft-affinity (`preferred`), **без hard-пина** на 04; k8s-04 — последний кандидат | 02/03 по ADR-0003 — «ingress + лёгкие сервисы» (по ~11 Gi свободно: allocatable 14.8 Gi, занято 3.3 Gi); 04 — двигатель демо (GPUStack + vLLM + страницы моделей), логин на сцене не должен конкурировать с инференсом и падать вместе с ним. Hard nodeSelector = нет переезда вообще — это дефект, а не «привязка к железу» (§4.0) |
| Реплики | Keycloak **×2** на разных узлах (`podAntiAffinity: preferred`), PostgreSQL ×1 | одна потерянная нода не выключает SSO; общий кэш сессий — `--cache-stack=jdbc-ping` через БД. БД остаётся SPOF: RTO 1–3 мин (том Longhorn переезжает) — цена, которую принимаем на демо (§4.0) |
| Данные | StatefulSet PG, PVC **8 Gi**, SC `longhorn` (replica=2) | r=2 переживает отказ одной ноды; бэкап — §7.2 |
| TLS | `Certificate auth-demo-tls` в ns `keycloak`, ClusterIssuer `letsencrypt-wildcard` (F5) | **Ingress читает TLS-секрет только в своём ns** — wildcard-секрет `demo-wildcard-tls` из `demo-test` переиспользовать нельзя; выпускаем отдельный серт на `auth.demo-ai-lab.ru` |
| Ingress | класс `higress`, host `auth.demo-ai-lab.ru`, TLS, `path /` | ingress-VIP `.230` + Higress (F7/F8) — единственный вход; других маршрутов не заводим |
| Публичность | `auth.*` **публикуется наружу** (исключение из правила E6), админка — гейт (§4.5) | без внешнего `auth.*` не работает SSO у внешних зрителей демо и browser-redirect'ы; HIGRESS-маршрут = автоматическая публикация через wildcard туннеля |
| Развёртывание | plain-манифесты в `gitops/infra-apps/keycloak/` под Argo CD | ApplicationSet `infra-apps` (git-directory generator, prune+selfHeal, project `infra`) уже работает: `infra` и `root-app` — Synced/Healthy. Helm-релиз вывел бы объекты из-под Argo (adoption-долг F6) — поэтому не helm |
| Секреты | `keycloak-admin.local.md`, `keycloak-users.local.md`, `keycloak-clients.local.md` в корне репо, `.gitignore: *.local.md`; в кластере — Secret `keycloak-db`, `keycloak-bootstrap` | AGENTS.md: приватные файлы в git не попадают; Secret'ы создаются скриптом, не Argo (иначе пароли в публичной истории) |
| PriorityClass | `demo-stand-critical` (value 100000) для Keycloak и PG | GPUStack/инференс на том же узле: SSO не должен эвиктиться при RAM-давлении (у подов без класса приоритет 0) |

**Вне спеки:** подключение приложений (Open WebUI, RAGFlow, qm — шаги 2/3), OIDC для
внутреннего MCP-реестра (`MCP_REGISTRY_OIDC_*`), LDAP/AD-федерация, MFA/TOTP, identity
brokering, HA-кластер (2 реплики + Infinispan `jdbc-ping`), Prometheus-скрейп `/metrics`.

## 2. Предпосылки — проверено 2026-10-24

```bash
kubectl get sc                 # longhorn (default), longhorn-static
kubectl get ingressclass       # higress
kubectl get nodes -o custom-columns='NODE:.metadata.name,RAM:.status.allocatable.memory,CPU:.status.allocatable.cpu'
                               # 01: 32029372Ki/16, 02 и 03: 15548856Ki/12, 04: 29455896Ki/16; taint'ов нет
kubectl top nodes              # занято: 01 — 2.8Gi, 02/03 — по 3.3Gi, 04 — 3.1Gi (свободно ~11Gi на 02/03)
kubectl -n higress-system get svc higress-gateway   # LoadBalancer 192.168.10.230, externalTrafficPolicy: Local
dig +short auth.demo-ai-lab.ru @1.1.1.1             # 104.21.x / 172.67.x — anycast Cloudflare (wildcard уже proxied)
dig +short @192.168.10.1 auth.demo-ai-lab.ru        # 192.168.10.230 — split-DNS MikroTik (wildcard regexp)
```

- **DNS-работы не нужны**: внешний wildcard `*.demo-ai-lab.ru` (proxied) и LAN-split-DNS
  (regexp → `.230`) уже покрывают `auth.*`. Отдельная запись в Cloudflare не заводится.
- **Публикация автоматическая**: туннель роутит любой валидный Ingress диапазона
  `*.demo-ai-lab.ru` — как только K4 применит Ingress, `auth.*` становится доступен снаружи.
  Поэтому гейт админки (§4.5) — обязательный шаг той же фазы, а не «потом».
- **NTP**: проверить `timedatectl` на k8s-02 и k8s-03 перед K3 — расхождение часов ломает проверку JWT
  (токены живут минуты), а между двумя узлами ещё и валит кластерный кэш сессий.
- **Образы**: предзагрузить на **оба** узла пары (k8s-02 и k8s-03) в `preload-registry`
  (`192.168.10.188:5050`) или сразу `crictl pull` — канал площадки 4–6 МБ/с, ~450 МБ образов на два
  сервиса, а реплики Keycloak живут на разных узлах (иначе первый же переезд снова тянет из интернета).
  Критерий K1 — `kubectl -n keycloak get pod ... -o jsonpath='{.status.containerStatuses[0].imageID}'`
  содержит нужный digest.

## 3. Секреты и приватные файлы

### 3.1 Файлы в репозитории (в git не попадают)

| Файл | Что внутри | Кто читает |
|---|---|---|
| `keycloak-admin.local.md` | `bootstrap-admin-username/password` (временный админ master), `db-name/username/password` | `scripts/keycloak_secrets.sh` (K1), `scripts/keycloak_seed.py` (K5) |
| `keycloak-users.local.md` | `realm: dev`, `user-test-password`, `admin-test-password` | `scripts/keycloak_seed.py` (K5) |
| `keycloak-clients.local.md` | секреты клиентов по мере подключения сервисов (шаг 2/3) | seed-скрипт / руками в Admin Console |

- Формат — `ключ: значение`, по строке на ключ (машиночитаемо для `awk`); заголовок-комментарий
  в файле объясняет назначение. Права `600`, созданы 2026-10-24, пароли сгенерированы (28/20 симв.).
- **`.gitignore`**: добавлено правило `*.local.md` (покрывает и `inventory.local.md`, и новые
  файлы; explicit-строка остаётся). Проверка перед каждым коммитом:
  ```bash
  git check-ignore -v keycloak-admin.local.md keycloak-users.local.md keycloak-clients.local.md
  git status --porcelain | grep -E '\.local\.md' || echo 'чисто'
  ```
  Процедура AGENTS.md «Обязательная проверка чувствительности» дополнена этими именами.
- **Правило работы**: значения из файлов читаются в переменную и передаются флагом/через secret;
  в терминал не печатать (`set +x`, без `echo $PASS`), в чат и в доки не копировать,
  в `old/`, `preload-registry/`, дампы и логи не кладём.

### 3.2 Secret'ы в кластере (создаются скриптом, не Argo)

| Secret (ns `keycloak`) | Ключи | Источник |
|---|---|---|
| `keycloak-db` | `db-name`, `db-username`, `db-password` | `keycloak-admin.local.md` |
| `keycloak-bootstrap` | `username`, `password` | `keycloak-admin.local.md` |

`scripts/keycloak_secrets.sh` (идемпотентно, значения не печатает):
```bash
# псевдокод интерфейса; реализация — фаза K1
NS=keycloak
PW=$(awk -F': ' '/^db-password: /{print $2}' keycloak-admin.local.md)
kubectl -n $NS create secret generic keycloak-db \
  --from-literal=db-name="$(awk -F': ' '/^db-name: /{print $2}' keycloak-admin.local.md)" \
  --from-literal=db-username="$(awk -F': ' '/^db-username: /{print $2}' keycloak-admin.local.md)" \
  --from-literal=db-password="$PW" --dry-run=client -o yaml | kubectl apply -f -
# keycloak-bootstrap — аналогично; в конце: unset PW
```
Скрипт запускается **до** первого sync'а Argo (иначе под Keycloak в CrashLoop на подключении к БД)
и после каждой ротации пароля (§7.3).

### 3.3 Жизненный цикл bootstrap-админа

`KC_BOOTSTRAP_ADMIN_*` действует **только на первом старте** (пока нет master-реалма) — смена
значения в файле кластер не меняет. Поэтому после K5: сменить пароль через Admin Console/`kcadm`
(новое значение — в `keycloak-admin.local.md`), затем **убрать** `KC_BOOTSTRAP_ADMIN_*` из
Deployment (правка в git → Argo) — постоянная учётка остаётся в master с паролем из файла.
Второй админ-аккаунт приложений (`admin-test`) живёт **в realm `dev`** и никаких прав на
master-реалм и админку Keycloak не имеет.

## 4. Развёртывание через Argo CD

### 4.0 Размещение и отказоустойчивость (решение 2026-10-24)

Первая редакция спеки пинила всё на k8s-04 «по ADR-0003 (data-heavy)» — это неверно по двум причинам:
04 — двигатель демо (GPUStack + vLLM + page cache моделей), и **hard `nodeSelector` означает, что при
потере узла под не переезжает вообще**, а висит `Pending` до возврата железа.

Живые цифры (2026-10-24, `kubectl top nodes` / `describe`):

| Узел | allocatable RAM | занято | свободно | что ещё живёт | вердикт |
|---|---|---|---|---|---|
| k8s-01 | 30.5 Gi | 2.8 Gi | ~27 Gi | etcd/API, coredns; **в планах — RAGFlow-индексация, Docling OCR, qm** (спайки), диск самый изношенный | резерв (не первый выбор: спайки соседей) |
| k8s-02 | 14.8 Gi | 3.3 Gi | ~11 Gi | etcd/API, Higress-gateway, Argo CD, cert-manager | **да** |
| k8s-03 | 14.8 Gi | 3.3 Gi | ~11 Gi | то же + второй gateway | **да** |
| k8s-04 | 28 Gi | 3.1 Gi | ~25 Gi | metrics-server, Longhorn instance-manager; **на демо — GPUStack + инференс** | нет (конкурент за RAM/CPU в момент показа) |

Ключевое: **Keycloak — лёгкий сервис** (requests 768 Mi) и по ADR-0003 ему место именно на паре 02/03
(«ingress + лёгкие сервисы»); «data-heavy на 04» относится к большим хранилищам (Qdrant, ClickHouse, MinIO),
а не к 8-гиговой БД SSO. Поэтому: PostgreSQL — на 02/03 (soft-affinity), Keycloak — две реплики на разных
узлах пары, оба — soft-affinity, чтобы при потере обоих узлов поды могли сесть на 01/04, а не залипнуть.

Матрица сбоев (что реально произойдёт):

| Сценарий | 1 реплика + hard pin на 04 (редакция v1.0) | 1 реплика + soft-affinity 02/03 | **2 реплики на 02/03 + jdbc-ping (принято)** |
|---|---|---|---|
| ребут/падение k8s-04 | SSO мёртв до возврата 04 | SSO жив (04 не участвует) | SSO жив |
| падение k8s-02 (или 03) | SSO жив (он на 04) | переезд на второй узел, RTO 40–90 c (`started`-проба + implicit build) | **логин не прерывается**, второй под уже держит сессии |
| падение узла, где PostgreSQL | SSO мёртв | SSO мёртв 1–3 мин (переаттач тома Longhorn r=2) | то же 1–3 мин — **БД остаётся SPOF** |
| потеря обоих узлов пары | — | Pending до возврата одного | Pending/переезд на 01/04 (`preferred`, не `required`) |

Остаточные риски приняты осознанно: single-instance PostgreSQL (HA-БД = Patroni/CNPG — day-2, §9),
и `preferred`-антиаффинность допускает, что в крайнем случае обе реплики окажутся на одном узле
(лучше, чем `Pending` на демо; проверяется критерием K7).

### 4.1 Что кладём в git

Каталог `gitops/infra-apps/keycloak/` (имя каталога = namespace назначения; ApplicationSet
`infra-apps` подхватит его сам — отдельный Application писать не нужно):

```
gitops/infra-apps/keycloak/
  00-priorityclass.yaml     # ClusterPriorityClass demo-stand-critical (wave -2)
  10-postgres.yaml          # Service + StatefulSet + PVC-шаблон 8Gi (wave -1, sync-wave: "-1")
  20-keycloak.yaml          # Deployment + Service (wave -1)
  30-ingress.yaml           # Certificate auth-demo-tls + Ingress (wave 0)
```

- Sync-waves: PG/Keycloak раньше ingress'а; `Certificate` и `Ingress` — вместе (Higress подхватит
  серт, как только он Ready; до этого отдаёт дефолтный серт — норма для промежуточного состояния).
- Secrets в каталоге **отсутствуют намеренно**: Argo их не создаёт и не удаляет (объект вне git =
  вне prune), поэтому ротация идемпотентна и history остаётся чистой.
- Проверка после push: `kubectl -n argocd get app keycloak` → `Synced/Healthy`;
  живость — по подам, не по статусу Argo (`gitops/README.md`).

### 4.2 PostgreSQL

```yaml
# 10-postgres.yaml — ключевое
kind: StatefulSet
spec:
  serviceName: postgres
  replicas: 1
  template:
    spec:
      affinity:                       # БД жмётся к паре ingress-узлов, но не жёстко (иначе Pending на демо)
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference: {matchExpressions: [{key: kubernetes.io/hostname, operator: In, values: [k8s-02, k8s-03]}]}
      priorityClassName: demo-stand-critical
      containers:
      - name: postgres
        image: postgres:17.11@sha256:b8faeff7712663c2773a190181e1246e37e364b887611c04658c28b44e2408fe
        env:
        - {name: POSTGRES_DB,       valueFrom: {secretKeyRef: {name: keycloak-db, key: db-name}}}
        - {name: POSTGRES_USER,     valueFrom: {secretKeyRef: {name: keycloak-db, key: db-username}}}
        - {name: POSTGRES_PASSWORD, valueFrom: {secretKeyRef: {name: keycloak-db, key: db-password}}}
        - {name: PGDATA, value: /var/lib/postgresql/data/pgdata}   # подкаталог: lost+found на Longhorn
        - {name: POSTGRES_INITDB_ARGS, value: "--data-checksums"}
        resources: {requests: {cpu: 100m, memory: 256Mi}, limits: {cpu: "1", memory: 768Mi}}
        readinessProbe: {exec: {command: [sh, -c, "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]}, initialDelaySeconds: 10}
  volumeClaimTemplates:
  - metadata: {name: data}
    spec: {accessModes: [ReadWriteOnce], storageClassName: longhorn, resources: {requests: {storage: 8Gi}}}
```

### 4.3 Keycloak

```yaml
# 20-keycloak.yaml — ключевое
kind: Deployment
spec:
  replicas: 2
  strategy: {type: RollingUpdate, rollingUpdate: {maxUnavailable: 0, maxSurge: 1}}
  template:
    metadata: {labels: {app: keycloak}}
    spec:
      affinity:
        nodeAffinity:                 # пара 02/03 — предпочтительно; k8s-04 в списке нет намеренно
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference: {matchExpressions: [{key: kubernetes.io/hostname, operator: In, values: [k8s-02, k8s-03]}]}
        podAntiAffinity:              # реплики на разных узлах; не required — чтобы демо не залипало в Pending
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              topologyKey: kubernetes.io/hostname
              labelSelector: {matchLabels: {app: keycloak}}
      priorityClassName: demo-stand-critical
      containers:
      - name: keycloak
        image: quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b
        args: ["start",
               "--hostname=https://auth.demo-ai-lab.ru",
               "--hostname-backchannel-dynamic=true",
               "--http-enabled=true",
               "--proxy-headers=xforwarded",
               "--proxy-trusted-addresses=10.0.0.0/8",
               "--health-enabled=true", "--metrics-enabled=true",
               "--cache-stack=jdbc-ping", "--log=console"]
        env:
        - {name: KC_DB,          value: postgres}
        - {name: KC_DB_URL,      value: jdbc:postgresql://postgres.keycloak.svc:5432/keycloak}
        - {name: KC_DB_USERNAME, valueFrom: {secretKeyRef: {name: keycloak-db, key: db-username}}}
        - {name: KC_DB_PASSWORD, valueFrom: {secretKeyRef: {name: keycloak-db, key: db-password}}}
        - {name: KC_BOOTSTRAP_ADMIN_USERNAME, valueFrom: {secretKeyRef: {name: keycloak-bootstrap, key: username}}}
        - {name: KC_BOOTSTRAP_ADMIN_PASSWORD, valueFrom: {secretKeyRef: {name: keycloak-bootstrap, key: password}}}
        - {name: JAVA_OPTS_APPEND, value: "-XX:MaxRAMPercentage=70 -XX:InitialRAMPercentage=25"}
        resources: {requests: {cpu: 250m, memory: 768Mi}, limits: {cpu: 1500m, memory: 1536Mi}}
        ports: [{name: http, containerPort: 8080}, {name: mgmt, containerPort: 9000}]
        startupProbe:  {httpGet: {path: /health/started, port: mgmt}, periodSeconds: 5, failureThreshold: 60}
        readinessProbe:{httpGet: {path: /health/ready,   port: mgmt}, periodSeconds: 10}
        livenessProbe: {httpGet: {path: /health/live,    port: mgmt}, periodSeconds: 20, failureThreshold: 5}
        volumeMounts: [{name: tmp, mountPath: /tmp}]
      volumes: [{name: tmp, emptyDir: {}}]
```

Решения и почему именно так (проверено по докам Keycloak 26.8):

- **`--hostname` полный URL** — hostname v2: issuer в токенах фиксирован, `KC_HOSTNAME_URL` больше
  нет; динамически из заголовков Keycloak его не вычисляет намеренно (защита от подмены issuer).
- **`--hostname-backchannel-dynamic=true`** — серверные (backchannel) вызовы клиентов, живущих
  в кластере, могут идти на внутренний адрес `http://keycloak.keycloak.svc:8080` и не зависеть от
  внешнего пути через Cloudflare (риск R1). Фронтовые (`authorization_endpoint`) остаются внешними.
- **TLS терминирует Higress** (`--http-enabled=true`), Keycloak верит `X-Forwarded-*`
  только от pod-сети Cilium (`10.0.0.0/8`, cluster-pool; gateway-поды — `10.0.2.2`/`10.0.0.174`).
- **`--cache-stack=jdbc-ping`** — две реплики делят кэш сессий через БД, sticky-сессии не нужны;
  при падении узла пользователь не теряет логин. Бонус: health-check «Keycloak cluster health»
  доступен только в кластерном режиме на `jdbc-ping`/`jdbc-ping-udp`.
- **Health на management-порту 9000** (`http-management-health-enabled` по умолчанию true):
  `/health/started|live|ready`. Curl **внутри образа** недоступен (в образе нет curl) — проверять
  пробой/снаружи, не `kubectl exec curl`.
- **Первый старт делает implicit build** (health/metrics — build-time опции): готовность дольше,
  поэтому `startupProbe` с запасом 5×60 с. Не «лечим» переходом на кастомный образ — лишний слой
  для стенда.
- **`RollingUpdate` с `maxUnavailable: 0`** — при двух репликах и общем кэше это честная выкатка
  «ноль простоя»; `Recreate` вернулся бы к простою SSO на каждой правке манифеста.

### 4.4 Ingress и TLS

```yaml
# 30-ingress.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata: {name: auth-demo-tls, namespace: keycloak}
spec:
  secretName: auth-demo-tls
  dnsNames: ["auth.demo-ai-lab.ru"]
  issuerRef: {name: letsencrypt-wildcard, kind: ClusterIssuer}
  privateKey: {rotationPolicy: Always}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata: {name: auth, namespace: keycloak}
spec:
  ingressClassName: higress
  tls: [{hosts: ["auth.demo-ai-lab.ru"], secretName: auth-demo-tls}]
  rules:
  - host: auth.demo-ai-lab.ru
    http: {paths: [{path: /, pathType: Prefix, backend: {service: {name: keycloak, port: {number: 8080}}}}]}
```

- Отдельный `Certificate`, а не корневой wildcard-секрет: TLS-секрет ищется **в namespace Ingress'а**
  (cross-namespace ссылка в Ingress не поддерживается). Issuer `letsencrypt-wildcard` — кластерный,
  DNS-01 через Cloudflare-токен (F5/E5), работает для любого имени зоны.
- Лимит LE — 50 сертификатов/нед. на домен; при отладке не дёргать перевыпуск в цикле (см. §8).

### 4.5 Гейт админ-консоли (обязательно, часть K6)

Публичный `auth.*` означает публичный `/admin`. Решение — **Cloudflare Access на пути**
(не на весь хостнейм, иначе сломаются редиректы OIDC):

| Путь | Кто пускает |
|---|---|
| `/admin*` | Cloudflare Access (email-OTP, политика на владельца) — снаружи; из LAN Access не участвует (split-DNS → `.230` идёт мимо edge) |
| `/realms/master*` | то же (закрывает прямой password-grant к master снаружи) |
| `/realms/dev/*`, `/resources/*`, `/js/*`, `/robots.txt` | без ограничений — это и есть SSO для приложений |

- Скоупы токена: `Account → Access: Apps and Policies: Edit` + account id в инвентаре — уже
  заложены при E5 «про запас» (external-access-spec §E6); если не хватает — добавить.
- **Проверка обязательна в обе стороны**: снаружи `/admin/` → 403/302 на Access; из LAN → 200
  страница консоли. Только после этого фаза K6 закрыта.
- План Б (если Access не поднимаем): оставить `/admin` публичным, но усилить — brute-force
  (§5.1), пароль 28 символов, второго master-админа нет, `KC_LOG=console` + контроль
  неудачных входов через Admin API. Зафиксировать выбор в §7 ARCHITECTURE.

## 5. Realm `dev`: роли, пользователи, клиенты

### 5.1 Настройки реалма

| Настройка | Значение | Почему |
|---|---|---|
| realm / displayName | `dev` / `demo-ai-lab (dev)` | реалм приложений; администрирование Keycloak — отдельно в `master` |
| `registrationAllowed`, `resetPasswordAllowed` | `false` | SMTP на стенде нет: регистрация и сброс пароля почтой всё равно не доедут |
| `verifyEmail`, `loginWithEmailAllowed` | `false` / `true` | адреса тестовых учёток нерабочие; вход по логину |
| `editUsernameAllowed` | `false` | логины `user-test`/`admin-test` — контракт для приложений |
| `bruteForceProtected` | `true`: `failureFactor=5`, `waitIncrementSeconds=60`, `maxFailureWaitSeconds=900`, `permanentLockout=false` | пароли демонстрационные, перебор должен упираться в лимит |
| `accessTokenLifespan` | `300` c | стандарт; приложения стенда живут на коротких сессиях |
| `ssoSessionIdleTimeout` / `MaxLifespan` | `1800` / `36000` c | демо: полдня без повторного логина |
| `revokeRefreshToken` | `true`, `refreshTokenMaxReuse=0` | отзыв при выходе — предсказуемое поведение |
| `passwordPolicy` | `length(16) and notUsername(undefined) and notEmail(undefined)` | синтаксис проверить при seed'е: `kcadm` вернёт ошибку на невалидной политике |

### 5.2 Роли и пользователи

| Роль | Тип | Что даёт |
|---|---|---|
| `app-user` | realm role | обычный пользователь приложений |
| `app-admin` | realm role, composite (включает `app-user`) | администратор приложений; **не** админ Keycloak |

| Пользователь | Пароль | Роли | Атрибуты | Зачем |
|---|---|---|---|---|
| `user-test` | `keycloak-users.local.md` | `app-user` | `email: user-test@demo-ai-lab.ru`, `firstName: Test`, `lastName: User` | демонстрация «обычного» входа в приложения |
| `admin-test` | `keycloak-users.local.md` | `app-admin` (+`app-user` композитом) | `email: admin-test@demo-ai-lab.ru`, `firstName: Admin`, `lastName: Test` | демонстрация админ-функций в приложениях |

- Пароли ставятся **не временными** (`temporary=false`) — иначе первый вход упрётся в смену пароля,
  а история паролей/политика не нужны на демо.
- Логины/адреса публикуемы (это стенд), пароли — нет (§3).
- `admin-test` ≠ админ Keycloak: разные реалмы, разные права. В доках и на сцене это разделять явно.

### 5.3 Клиенты

| clientId | Тип | Flow | Redirect URI | Когда |
|---|---|---|---|---|
| `smoke-cli` | public | direct access grant (standard flow **off**) | — | K5: приёмочные curl-проверки токенов `user-test`/`admin-test` |
| `open-webui` | confidential | standard flow | `https://openwebui.demo-ai-lab.ru/oauth/oidc/callback` | шаг 2 демо |
| `ragflow` | confidential | standard flow | уточнить по доке/логу деплоя сервиса | шаг 2 |
| `qm` | confidential | standard flow | уточнить по доке деплоя | шаг 3 |
| MCP-реестр | confidential / OIDC | позже | внутренний URL реестра | вне спеки (ARCHITECTURE §3) |

- Redirect URI **не угадываем**: для каждого сервиса значение берётся из его документации/лога
  при первом деплое и фиксируется в `keycloak-clients.local.md` (секрет) + в таблице здесь (сам URI).
  Пока серт не поднят, `https://localhost:*` в тестах не добавляем — стенд живёт на реальных DNS.
- Post-logout redirect добавляется сразу (`Valid post logout redirect URIs`: `https://<host>/*`) —
  иначе выход из приложения не вернёт пользователя и это всплывёт на сцене.
- Секреты клиентов — только `keycloak-clients.local.md`; в git — ни в манифестах, ни в JSON-экспортах.

### 5.4 Как применяется конфигурация (idempotent seed)

`scripts/keycloak_seed.py` — единственный источник правды для realm/users/clients, Admin API
(`https://auth.demo-ai-lab.ru/realms/master/protocol/openid-connect/token`, `client_id=admin-cli`,
креды из `keycloak-admin.local.md`):

1. создать/обновить реалм `dev` (§5.1);
2. создать роли `app-user`, `app-admin` (+composite);
3. создать пользователей, выставить пароли `temporary=false`, назначить роли;
4. создать клиентов из таблицы §5.3, у которых известен redirect URI; выставить секреты;
5. напечатать **только сводку** (`realm: ok`, `roles: 2`, `users: 2`, `clients: N`) — значения не логировать.

Скрипт можно гонять повторно в любой момент (после правки §5.1/§5.2 — снова прогнать, не руками в UI).
Экспорт для ревью конфигурации: `kcadm export --realm dev --users skip` (без пользователей и
секретов; в git — только если понадобится дифф, и только `--users skip`).

## 6. Фазы и критерии приёмки

### K1 — предпосылки: образы, ns, Secret'ы
- образы запинены и предзагружены **на k8s-02 и k8s-03** (pull из `quay.io`/`docker.io` подтверждён: `quay.io` работает с площадки — проверено 2026-10-24);
- namespace создаётся **здесь**, до Secret'ов: `kubectl create ns keycloak` (идемпотентно; Argo потом
  с `CreateNamespace=true` просто видит существующий — namespace вне git, потому что Secret'ы в нём
  создаются раньше первого sync'а);
- Secret'ы: `./scripts/keycloak_secrets.sh`;
- NTP на k8s-02 и k8s-03 в норме.
```bash
kubectl -n keycloak get secret keycloak-db keycloak-bootstrap        # 2 объекта
git check-ignore -v keycloak-admin.local.md keycloak-users.local.md   # оба матчатся
```

### K2 — PostgreSQL
```bash
kubectl -n keycloak get sts postgres                                  # 1/1 Ready
kubectl -n keycloak get pvc data-postgres-0                           # Bound, 8Gi, SC longhorn
kubectl -n keycloak exec sts/postgres -- psql -U keycloak -d keycloak -c 'select version();'
```
- данные переживают рестарт пода: `kubectl -n keycloak delete pod postgres-0` → после Ready таблица
  `SELECT count(*) FROM pg_class;` не пустая после K3 (проверяется на следующей итерации).

### K3 — Keycloak
```bash
kubectl -n keycloak get deploy keycloak                    # 2/2, READY; поды на РАЗНЫХ узлах пары (kubectl get pod -o wide)
kubectl -n keycloak get pod -l app=keycloak -o yaml | grep -A2 'state: Running'
kubectl -n keycloak port-forward svc/keycloak 9000:9000 &  # управление — локально
curl -s localhost:9000/health/ready                        # {"status":"UP"...}
kubectl -n keycloak logs deploy/keycloak | grep -iE 'error|exception' | head   # пусто/только стартовые warn
```
- старт занял < 3 мин (implicit build); в логах нет ошибок подключения к БД.

### K4 — ingress, TLS, маршрут
```bash
kubectl -n keycloak get certificate auth-demo-tls -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'  # True
curl -sS -o /dev/null -w '%{http_code}\n' --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
     https://auth.demo-ai-lab.ru/realms/master/.well-known/openid-configuration    # 200 из LAN
openssl s_client -connect 192.168.10.230:443 -servername auth.demo-ai-lab.ru </dev/null 2>/dev/null \
  | openssl x509 -noout -issuer -subject -enddate                                      # issuer: Let's Encrypt (ISRG), CN=auth.demo-ai-lab.ru
curl -sS -o /dev/null -w '%{http_code}\n' https://auth.demo-ai-lab.ru/realms/master/.well-known/openid-configuration  # 200 через edge (при живых коннекторах)
```
- issuer в discovery-документе — **дословно** `https://auth.demo-ai-lab.ru/realms/dev` (для dev)
  и `.../realms/master`; никакого `http://` и никаких внутренних адресов в публичных метаданных.

### K5 — realm `dev`, пользователи, клиенты
```bash
# пароль берём из локального файла в переменную, в вывод не печатаем
UP=$(awk -F': ' '/^user-test-password: /{print $2}' keycloak-users.local.md)
AP=$(awk -F': ' '/^admin-test-password: /{print $2}' keycloak-users.local.md)
curl -s -d "grant_type=password&client_id=smoke-cli&username=user-test&password=$UP" \
  https://auth.demo-ai-lab.ru/realms/dev/protocol/openid-connect/token \
  | python3 -c 'import json,sys,base64; t=json.load(sys.stdin)["access_token"]; p=t.split(".")[1]; p+="="*(-len(p)%4); print(sorted(json.loads(base64.urlsafe_b64decode(p))["realm_access"]["roles"]))'
                                                                    # ['app-user']
# для admin-test: ['app-admin', 'app-user'] (композит разворачивается)
unset UP AP
```
- `user-test` логинится в браузере и получает токен с `app-user`; `admin-test` — с `app-admin`;
- `admin-test` **не** имеет доступа к Admin Console Keycloak (master), и в `master` его нет вовсе.

### K6 — админка и харденинг (§4.5)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://auth.demo-ai-lab.ru/admin/                    # снаружи: 403/302 → Access
curl -sS -o /dev/null -w '%{http_code}\n' --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
     https://auth.demo-ai-lab.ru/admin/                                                          # из LAN: 200
curl -sS -o /dev/null -w '%{http_code}\n' https://auth.demo-ai-lab.ru/realms/master/protocol/openid-connect/token  # снаружи: 403 → Access
```
- bootstrap-админ отработал: пароль сменён, `KC_BOOTSTRAP_ADMIN_*` убран из Deployment (правка в git → Argo);
- brute-force защита включена (проверить 6 неудачных входов → `temporarily disabled`), пароли не временные.

### K7 — закрытие фазы
- `python3 scripts/k8s_health.py --brief` — без новых WARN/FAIL;
- `kubectl -n argocd get app keycloak` → Synced/Healthy; живые поды Running;
- **drill отказоустойчивости (§4.0)** — обязателен, иначе размещение не проверено:
  ```bash
  kubectl -n keycloak get pods -o wide          # зафиксировать: реплики на разных узлах
  kubectl -n keycloak delete pod <реплика>      # 1) потеря пода: логин в приложении не рвётся
  curl -fsS -o /dev/null -w '%{http_code}\n' --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
       https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration   # 200 всё время
  kubectl -n keycloak scale deploy/keycloak --replicas=1  # 2) имитация потери узла: SSO отвечает
  # (масштаб вернуть в 2; после проверки — kubectl -n keycloak get pods -o wide снова 2/2)
  ```
  Критерий: 200 на discovery и успешный password-grant (K5) в каждом из двух сценариев;
  если при потере пода логин рвётся — `jdbc-ping` не поднялся (смотреть `Keycloak cluster health`
  в `/health/ready` и логи Infinispan).
- дописать в `ARCHITECTURE.md` §7 строку Keycloak (факт + дата), в `gitops/README.md` — состав
  `infra-apps/keycloak/`; в README — строку спеки в таблице документации;
- бэкап до объявления «готово» (§7.2) и запись в историю версий этой спеки.

## 7. Операции

### 7.1 Проверка «жив ли SSO» (в любой момент)
```bash
curl -fsS -o /dev/null -w 'lan:%{http_code} ' --resolve auth.demo-ai-lab.ru:443:192.168.10.230 \
     https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration
curl -fsS -o /dev/null -w 'edge:%{http_code}\n' https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration
kubectl -n keycloak get pods
```
`edge:` ≠ 200 при шторме uplink (R1) — это не поломка Keycloak: LAN-путь (основной для аудитории)
жив. В `scripts/k8s_health.py` Keycloak пока не входит; добавить проверку — отдельная правка скрипта.

### 7.2 Бэкап и восстановление
- PostgreSQL на Longhorn r=2 переживает отказ ноды, но **не** откат ошибки/апгрейда;
- перед обновлением Keycloak и перед демо: `kubectl -n keycloak exec postgres-0 -- pg_dump -U keycloak -Fc keycloak > ~/hermes-home/keycloak-backups/kc-$(date +%F).dump`
  (каталог **вне репо** — дамп содержит хэши паролей);
- восстановление: остановить Keycloak (scale 0) → `pg_restore --clean --if-exists` в ту же БД → scale 1;
- Longhorn: опционально recurring snapshot на PVC `data-postgres-0` (окно 1 ч, retention 3) —
  day-2, если останется место.

### 7.3 Ротация паролей
1. новый пароль → `keycloak-admin.local.md` / `keycloak-users.local.md` (файлы в git не попадают);
2. администратор Keycloak: Admin Console → Users → Credentials (или `kcadm set-password`);
   `user-test`/`admin-test`: `scripts/keycloak_seed.py` (шаг 3) — он идемпотентно переставит пароли;
3. БД: `scripts/keycloak_secrets.sh` (обновит Secret) → `kubectl -n keycloak rollout restart deploy/keycloak`
   (через git не нужно — Secret вне Argo);
4. bootstrap-пароль: только через Admin Console до снятия `KC_BOOTSTRAP_ADMIN_*`, иначе он всё равно
   не применяется (§3.3).

### 7.4 Обновление версии
1. бэкап (§7.2);
2. сверить, что апгрейд поддерживается (Keycloak: «upgrade guide», PG — мажор только через dump/restore;
   в пределах 26.x — плановая замена образа);
3. изменить digest в `gitops/infra-apps/keycloak/20-keycloak.yaml` → push → Argo;
4. критерий: K3+K5 повторно зелёные, `kubectl -n keycloak logs` без ошибок миграции схемы.

## 8. Риски и грабли

| # | Риск/грабля | Что делаем |
|---|---|---|
| R-K1 | **RAM пары 02/03** (~11 Gi свободно на каждой; там же etcd, gateway, Argo) | requests/limits (§4.3): 2×768 Mi + 256 Mi; `priorityClassName: demo-stand-critical`; soft-affinity допускает переезд на 01/04 при заполнении пары; контроль `kubectl top pod -n keycloak` |
| R-K2 | **PostgreSQL — SPOF** (1 реплика): при потере его узла SSO недоступен 1–3 мин (переаттач тома Longhorn) | принято для демо; r=2 спасает данные, не доступность; HA-БД (Patroni/CNPG) — day-2; перед демо — бэкап (§7.2) |
| R-K3 | пароли в файлах репо | `.gitignore: *.local.md` + `git check-ignore` в процедуре AGENTS.md + пре-коммит grep-скан; chmod 600; файлы не копировать в `old/`, дампы, чат |
| R-K4 | шторм uplink (R1) → вход снаружи не работает | LAN-путь (split-DNS → `.230`) не зависит от edge; демо-аудитория в LAN; `hostname-backchannel-dynamic` снимает зависимость внутренних клиентов от внешнего пути |
| R-K5 | LE-лимит 50 сертов/нед при отладке TLS | не гонять перевыпуск в цикле; при залипании — проверить, что `Secret cloudflare-api-token` на месте и Issuer Ready (F5/E5), а не создавать дубли Certificate |
| R-K6 | wildcard-секрет из `demo-test` «напрашивается» на переиспользование | Ingress не умеет cross-namespace TLS: только свой `Certificate` в ns `keycloak` |
| R-K7 | `auth.*` автоматически публичен (туннель роутит любой Ingress) | гейт `/admin*` и `/realms/master*` через Access — часть K6, не «потом»; до гейта `auth.*` в мир не объявлять |
| R-K8 | implicit build на первом старте (дольше, пишет в `/opt/keycloak`) | `startupProbe` 5×60 c; не путать с падением пода; кастомный образ не нужен |
| R-K9 | curl внутри контейнера отсутствует (в образе нет curl) | health проверять пробой/`port-forward`/`kubectl exec` не использовать для curl |
| R-K10 | `*.demo-ai-lab.ru` wildcard-серт в паре с Cloudflare Access | Access-приложение строго по путям; иначе OIDC-редиректы сломаются — проверка K6 обе стороны обязательна |
| R-K11 | расхождение часов → JWT невалиден (и расходятся кэши реплик) | NTP-проверка в K1, `date -u` на k8s-02/03 vs консоль |

## 9. Что забывают в таких спеках (и что решено здесь) / открытые вопросы

| Пункт | Решение в этой спеке |
|---|---|
| **Размещение = отказоустойчивость** | §4.0: 2 реплики на паре 02/03, `preferred`-affinity (hard `nodeSelector` = `Pending` при потере узла); k8s-04 не первый выбор — там GPUStack/инференс |
| **БД** (Keycloak без своей БД не работает) | PostgreSQL 17.11 в том же ns, PVC 8 Gi Longhorn; общий data-tier стенда (ARCHITECTURE §5) ещё не существует — позже миграция dump/restore |
| TLS-секрет в namespace Ingress'а | свой `Certificate`, не wildcard из `demo-test` (§4.4) |
| Публичность и админка на одном хостнейме | Access по путям `/admin*`, `/realms/master*` (§4.5) |
| Backchannel для клиентов внутри кластера | `--hostname-backchannel-dynamic=true` (§4.3) |
| SMTP отсутствует | регистрация/сброс пароля выключены, `verifyEmail=false`, пароли не временные |
| Жизненный цикл bootstrap-админа | §3.3: смена пароля → снятие env → правка в git |
| Redirect/logout URI приложений | не угадываем, фиксируем при подключении сервиса (§5.3) |
| Роли приложений | `app-user` / `app-admin` (композит), отдельно от админа Keycloak |
| Приоритет под SSO при GPUStack на том же узле | `demo-stand-critical` PriorityClass |
| Бэкап и обновление | §7.2/§7.4 (дампы вне репо) |
| Метрики/health | `--health-enabled`, `--metrics-enabled`; Prometheus-скрейп — day-2 |
| Предзагрузка образов на медленном канале | K1, критерий по digest в `imageID` |
| NTP и время | K1 |
| Rate limit LE | R-K5 |
| Секреты в git | `.gitignore: *.local.md` + пре-коммит проверка (§3.1) |

**Открытые вопросы (решить до K6):**
1. Access по путям или план Б (публичная админка + brute-force) — выбрать явно и записать в §7 ARCHITECTURE.
2. Подключать ли `auth.*` к SSO самих служебных UI (Argo CD, GPUStack) — вне спеки, отдельным планом.
3. HA БД (Patroni / CloudNativePG, 2 экземпляра PG) — day-2: сейчас PostgreSQL единичный и остаётся
   единственной точкой отказа SSO (RTO 1–3 мин). Возвращаться, если логин станет критичным.
4. Нужен ли отдельный клиент для machine-to-machine (client credentials) до появления агентов шага 3.

## 10. Связанные документы и история версий

- `architecture/k8s-install-spec.md` — кластер F0–F10 (Longhorn, cert-manager/ClusterIssuer F5, ingress-VIP `.230` + Higress F7/F8, Argo CD F6).
- `architecture/external-access-spec.md` — Cloudflare Tunnel, split-DNS, Full strict, правило E6 (Access на служебные пути) и R1.
- `architecture/ARCHITECTURE.md` §3/§5 — место Keycloak в целевом слое «Данные и интеграции» и поправка §5: SSO живёт на паре 02/03, не на k8s-04 (`keycloak-spec.md` §4.0); §7 — статус.
- `gitops/README.md` — паттерн `infra-apps/<имя>` → Application + ns; `gitops/root/applicationsets.yaml`.
- `AGENTS.md` — что нельзя публиковать (секреты, приватные файлы), процедура перед коммитом.

История версий:
- **v1.1** (2026-10-24): **размещение пересмотрено (вопрос владельца).** Ключевая ошибка v1.0 — hard
  `nodeSelector` на k8s-04: при потере узла под не переезжает (`Pending`), а 04 на демо занят
  GPUStack/инференсом. Стало: Keycloak ×2 на паре **k8s-02/03** (`preferred` nodeAffinity +
  `preferred` podAntiAffinity, `--cache-stack=jdbc-ping` — сессии переживают потерю поданоды),
  PostgreSQL на 02/03 (soft-affinity), k8s-04 исключён из предпочтения. Добавлены §4.0 с живыми
  цифрами и матрицей сбоев, drill отказоустойчивости в K7, переписаны R-K1/R-K2 (SPOF — БД, RTO 1–3 мин).
- **v1.0** (2026-10-24): спека создана. Пины проверены на стенде: Keycloak 26.8.1 (`quay.io`,
  пробный под поднялся, `kc.sh --version` = 26.8.1, JVM 21.0.12.1), PostgreSQL 17.11 (digest по
  Docker Hub API). Развёртывание — Argo CD (`gitops/infra-apps/keycloak/`), Secret'ы — вне git.
  Созданы приватные файлы `keycloak-admin.local.md`, `keycloak-users.local.md`,
  `keycloak-clients.local.md`; `.gitignore` дополнен `*.local.md`. Кластер (2026-10-24): все 4 ноды
  Ready, `longhorn` default, ingressclass `higress`, VIP `.230`, `auth.demo-ai-lab.ru` уже резолвится
  и снаружи (anycast Cloudflare), и в LAN (`.230`).
