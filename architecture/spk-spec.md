# Спецификация установки Speakr (транскрибация аудио и видео)

> **Версия:** v1.2 (2026-10-28) · **Статус:** **развёрнуто 2026-10-28 (Argo CD, ns `spk`); S1–S3 сняты,
> S4–S6 (SSO, транскрибация, edge) — нет**
> **Цель:** шаг 2 демо — загрузка записи → транскрипт с таймкодами → саммари. ASR — существующая модель
> `whisper-turbo` в GPUStack (на 5060 Ti), тексты — `gemma-4-12B`, вход — Keycloak (SSO).
> **Внешнее имя:** `spk.demo-ai-lab.ru` (LAN — split-DNS на `.230`, снаружи — Cloudflare Tunnel).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/spk` с plain-манифестами (официального
> Helm-чарта у проекта нет); секреты — `Secret` в кластере, значения вне git.

Стиль-образцы: `architecture/k8s-install-spec.md` (F\*), `external-access-spec.md` (E\*),
`keycloak-spec.md` (K\*), `gpustack-spec.md` (G\*). Эта спека занимает букву **S**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Проект | **`murtaza-nasir/speakr`** (Docker Hub `learnedmachine/speakr`), AGPL-3.0, последний коммит 27.10.2026 | единственный self-hosted «Speakr» с веб-UI и сменными ASR-коннекторами; `learnedmachine` — авторский Docker Hub-аккаунт того же проекта |
| Образ | `docker.io/learnedmachine/speakr:0.10.16-alpha-lite` — индекс `sha256:71f09318a3ae23efbbd6c77ba12ddd45627308d236380514807e74fcad9a691d`, amd64 `sha256:4eb50ac06942f640acc9d47431a411ccc9448368863a498328d3812e7e68e274`, ≈ **332 MiB** | `skopeo inspect` + hub API (2026-10-28). `-lite` без PyTorch: теряется только semantic search в Inquire Mode, полный образ тянет 3,3 GiB на канале 2–5 МБ/с |
| Почему не `latest` | `latest` = `0.10.16-alpha` (тот же digest), стабильных тегов новее 0.8 нет; `-alpha` — единственная живая ветка | `skopeo list-tags`; риск R-S1 |
| Namespace | `spk` (создаёт ApplicationSet `apps`) | изоляция, TLS-секрет в своём ns |
| Реплики | **1**, без исключений | SQLite single-writer; очередь задач — потоки процесса; `entrypoint` делает `db.create_all()`+ALTER'ы |
| Контейнеры | **1** (`speakr`): Flask 3.1.3 + gunicorn `gthread` `--workers 3 --threads 8 --timeout 600`, порт **8899**; `ffmpeg`/`ffprobe` внутри образа | Dockerfile `CMD`/`EXPOSE`; отдельного воркера/брокера нет (`job_queue.py` — `threading.Thread`) |
| Состояние | PVC **20Gi** `longhorn` RWO → `/data`: `instance/transcriptions.db` (SQLite), `instance/` (SECRET_KEY), `uploads/` | mp3 128k ≈56 МБ/час речи; 20 GiB на старт достаточно (расчёт, не замер) |
| БД | SQLite (`SQLALCHEMY_DATABASE_URI` не задаём) | Postgres поддерживается (`psycopg2` в образе), но для одного админа избыточен; путь миграции — §7 |
| Redis / S3 | не ставим: `RATELIMIT_STORAGE_URI` пусто, `FILE_STORAGE_BACKEND=local` | Redis нужен только для точных rate-limit, S3 — только для объектного хранилища |
| ASR-бэкенд | GPUStack: `TRANSCRIPTION_CONNECTOR=openai_whisper`, `TRANSCRIPTION_BASE_URL=https://api.demo-ai-lab.ru/v1`, `TRANSCRIPTION_API_KEY` (Secret), `TRANSCRIPTION_MODEL=whisper-turbo` | **не `asr_endpoint`**: тот коннектор постит multipart на `{ASR_BASE_URL}/asr` (формат whisper-asr-webservice), а у GPUStack — OpenAI-совместимый `/v1/audio/transcriptions` |
| Диаризация | **не поддерживается** выбранным коннектором (нет спикеров, только таймкоды) | `openai_whisper` capabilities: chunking/timestamps/language/hotwords/initial_prompt; спикеры только у `asr_endpoint` (WhisperX) или облачных |
| Тексты (саммари, заголовки, Inquire) | GPUStack `gemma-4-12B`: `TEXT_MODEL_BASE_URL=https://api.demo-ai-lab.ru/v1`, `TEXT_MODEL_API_KEY`, `TEXT_MODEL_NAME=gemma-4-12B` | без них транскрипт работает, саммари падает |
| SSO | `ENABLE_SSO=true`, `SSO_DISCOVERY_URL=https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration`, `SSO_CLIENT_ID=spk`, `SSO_REDIRECT_URI=https://spk.demo-ai-lab.ru/auth/sso/callback`, `SSO_AUTO_REGISTER=true`, `SSO_DISABLE_PASSWORD_LOGIN=true` | Authlib 1.6.x в образе; callback в коде `/auth/sso/callback`; парольный вход админа остаётся аварийным |
| Регистрация | `ALLOW_REGISTRATION=false` | в коде дефолт `true` (`auth.py`) — за периметром это открытая саморегистрация |
| Ingress | `Ingress` класс `higress` + `Certificate spk-demo-tls` (ClusterIssuer `letsencrypt-wildcard`) в ns `spk` | правило E-серии; ingress-настройки чарта нет — пишем сами |
| Пробы | `livenessProbe`/`readinessProbe` **TCP 8899** | эндпоинта `/health` нет, `GET /` → 302; TCP-проба безопаснее httpGet по редиректу |
| Ресурсы | requests `250m/512Mi`, limits `2/4Gi` | доки: min 4 GB RAM, рекомендуют 8 GB; `-lite` без torch (ожидаемо 1,5–2 GiB RSS, **не замерено**); на 03 свободно ≈9,3 GiB |
| Размещение | `nodeAffinity.preferred` → `demo-ai-lab/role=ingress` (02/03), anti-affinity к себе preferred | одна реплика + RWO: жёсткий пин даёт `Pending` при потере узла |
| Размер загрузки | системная настройка БД `max_file_size_mb` (дефолт **250**) → `MAX_CONTENT_LENGTH` | в ENV не задаётся; меняется в админке; для видео в audio-only ×4 |
| Секреты | `Secret spk-secrets`: `SECRET_KEY`, `TRANSCRIPTION_API_KEY`, `TEXT_MODEL_API_KEY`, `ADMIN_PASSWORD`; `Secret spk-oidc` — клиент SSO | в git только имена |

## 2. Предпосылки — проверено 2026-10-28

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass
kubectl top nodes
dig +short @192.168.10.1 spk.demo-ai-lab.ru
skopeo inspect docker://docker.io/learnedmachine/speakr:0.10.16-alpha-lite --override-arch amd64
```

| Факт | Значение (замер) |
|---|---|
| StorageClass / Ingress | `longhorn` default; `higress`; VIP `.230`; Longhorn свободно 02/03 ≈ 244 GiB |
| Ноды | 03 — 14,8 GiB RAM, 12 CPU, метка `demo-ai-lab/role=ingress`; занято 5827 Mi → **свободно ≈9,3 GiB** |
| DNS | `spk.demo-ai-lab.ru`: LAN → `192.168.10.230`, снаружи → anycast Cloudflare (отдельная запись не нужна) |
| Keycloak | issuer `https://auth.demo-ai-lab.ru/realms/dev`; клиента `spk` ещё нет — создаётся сидом |
| GPUStack | `whisper-turbo` (`faster-whisper` int8 через vox-box) `RUNNING` на 5060 Ti, 2 294 MiB; `gemma-4-12B` `RUNNING`; `/v1/*` без ключа → **401** |
| Чарт | официального нет: в репозитории только `Dockerfile`, `config/docker-compose.example.yml`, `deployment/setup.sh`; в Artifact Hub пакета `speakr` нет |
| Образ | `-lite` 332 MiB (amd64), `-alpha` 3303 MiB; `latest` == `0.10.16-alpha` |

**Предусловие:** ключ модели GPUStack (O1 в `owu-spec.md`) — он же нужен здесь для `TRANSCRIPTION_API_KEY`
и `TEXT_MODEL_API_KEY`; без ключа загрузка падает на `401` от GPUStack.

## 3. Секреты и приватные файлы

| Файл | Что внутри | Кто читает |
|---|---|---|
| `spk-admin.local.md` (0600, gitignored) | `SECRET_KEY`, bootstrap `ADMIN_USERNAME/ADMIN_PASSWORD`, ссылка на ключ GPUStack | агент, человек |
| `keycloak-clients.local.md` | `spk` client secret | сид, Keycloak |
| `gpustack-admin.local.md` | ключ модели (`TRANSCRIPTION_API_KEY` = `TEXT_MODEL_API_KEY`) | агент, человек |

- `SECRET_KEY` обязателен и постоянен: если не задать, приложение сгенерит его и положит в `/data/instance`
  (тогда том обязателен, иначе все сессии разлогинятся при рестарте).
- `ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD` — bootstrap-админ в entrypoint: после первого входа
  сменить пароль и убрать `ADMIN_PASSWORD` из манифеста (оставить в приватном файле).
- В git — только `secretKeyRef`; проверка гигиены — `git check-ignore -v spk-admin.local.md` + пре-коммит grep.

## 4. Развёртывание

Состав `gitops/apps/spk/`:

| Файл | Что | Sync-wave |
|---|---|---|
| `10-pvc.yaml` | `PersistentVolumeClaim data` 20Gi `longhorn` RWO | 0 |
| `20-deployment.yaml` | `Deployment speakr` (replicas 1), `strategy: Recreate`, `env`/`envFrom`, `resources`, TCP-пробы, `volumeMounts /data` | 0 |
| `30-service.yaml` | `Service speakr` ClusterIP → 8899 | 0 |
| `40-ingress.yaml` | `Certificate spk-demo-tls` + `Ingress` → `speakr:8899` | 0 |

Ключевые фрагменты (почему именно так):

```yaml
strategy: { type: Recreate }          # RWO-том + SQLite: второй под не должен подняться рядом
containers:
  - name: speakr
    image: docker.io/learnedmachine/speakr:0.10.16-alpha-lite
    ports: [{ containerPort: 8899, name: http }]
    env:
      - { name: ALLOW_REGISTRATION,   value: "false" }          # в коде дефолт true
      - { name: TRANSCRIPTION_CONNECTOR, value: openai_whisper }
      - { name: TRANSCRIPTION_BASE_URL,  value: "https://api.demo-ai-lab.ru/v1" }
      - { name: TRANSCRIPTION_MODEL,     value: whisper-turbo }
      - { name: TEXT_MODEL_BASE_URL,     value: "https://api.demo-ai-lab.ru/v1" }
      - { name: TEXT_MODEL_NAME,         value: gemma-4-12B }
      - { name: ENABLE_SSO,              value: "true" }
      - { name: SSO_PROVIDER_NAME,       value: Keycloak }
      - { name: SSO_DISCOVERY_URL,       value: "https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration" }
      - { name: SSO_REDIRECT_URI,        value: "https://spk.demo-ai-lab.ru/auth/sso/callback" }
      - { name: SSO_AUTO_REGISTER,       value: "true" }
      - { name: SSO_DISABLE_PASSWORD_LOGIN, value: "true" }
      - { name: SESSION_COOKIE_SECURE,   value: "true" }
      - { name: TRUSTED_PROXY_HOPS,      value: "1" }           # один прокси перед app — Higress
    envFrom:
      - secretRef: { name: spk-secrets }                        # SECRET_KEY, *_API_KEY, ADMIN_*
      - secretRef: { name: spk-oidc }                           # SSO_CLIENT_ID, SSO_CLIENT_SECRET
    volumeMounts: [{ name: data, mountPath: /data }]
    livenessProbe:  { tcpSocket: { port: http }, initialDelaySeconds: 30, periodSeconds: 20 }
    readinessProbe: { tcpSocket: { port: http }, initialDelaySeconds: 10, periodSeconds: 10 }
    resources:
      requests: { cpu: 250m, memory: 512Mi }
      limits:   { cpu: "2",  memory: 4Gi }
```

- Образ работает **от root** (в Dockerfile нет `USER`) и сам делает `chmod 755` на `/data` — не задавать
  произвольный `runAsUser` без проверки прав на том.
- `TRUSTED_PROXY_HOPS` = **1**: перед приложением один прокси — Higress (envoy), он сам дописывает
  `X-Forwarded-For`. При 2 ProxyFix срезает лишний хоп, `remote_addr` остаётся адресом пода Higress
  (наблюдалось `10.0.0.88`), и rate-limit `10 per minute` на `/auth/sso/login` считается на всех
  клиентов сразу → после десятка попыток вход отбивается `429` (проверено 28.10.2026: с hops=1 в
  логе `ratelimit ... (192.168.10.200) exceeded`). Обратная сторона: на внешнем пути (CF → туннель →
  haproxy → hop → Higress) в лимите окажется IP последнего прокси — уточняется в S6.
- Ингресс: поднять лимит тела запроса и таймауты под загрузку (250 МБ дефолт) — конкретные аннотации
  Higress фиксируются в S3 по факту.

## 5. Конфигурация домена (Keycloak)

| Параметр клиента | Значение |
|---|---|
| clientId | `spk` |
| тип | confidential, standard flow |
| redirect URI | `https://spk.demo-ai-lab.ru/auth/sso/callback` |
| web origins | `https://spk.demo-ai-lab.ru` |
| обязательный claim | `email_verified=true` (иначе `SSO_REQUIRE_VERIFIED_EMAIL=true` режет вход) |

Сидинг — `scripts/keycloak_seed.py` (идемпотентный upsert). Пользователь `admin-test@demo-ai-lab.ru`
входит как SSO-админ; bootstrap-админ по паролю остаётся аварийным входом (`SSO_DISABLE_PASSWORD_LOGIN`
его не отключает).

## 6. Фазы и приёмка

### S1. Предусловие: ключ GPUStack и живой ASR

```bash
KEY=$(awk -F': ' '/^model-key: /{print $2}' gpustack-admin.local.md)
curl -s -H "Authorization: Bearer $KEY" https://api.demo-ai-lab.ru/v1/models | grep -c whisper-turbo
```
Приёмка: `1` (модель видна по ключу).

### S2. Каркас в git и секреты

`gitops/apps/spk` (PVC/Deployment/Service/Ingress) + `Secret spk-secrets`, `spk-oidc`.
Приёмка: `kubectl -n argocd get app spk` → `Synced`; `kubectl -n spk get secret spk-secrets spk-oidc`.

### S3. Установка и health

```bash
kubectl -n spk get pods,pvc,svc
kubectl -n spk rollout status deploy/speakr --timeout=300s
kubectl -n spk exec deploy/speakr -- python -c "import sqlite3;print(sqlite3.connect('/data/instance/transcriptions.db').execute('select count(*) from users').fetchone())"
```
Приёмка: под `1/1`, PVC `Bound`, таблица `users` существует, рестартов 0.

### S4. SSO

Вход через Keycloak → `/auth/sso/callback` → пользователь создан (`source=SSO`).
Приёмка: вход `admin-test@` и `user-test@`; `ALLOW_REGISTRATION=false` проверен — формы регистрации нет;
аварийный парольный вход админа работает.

### S5. Транскрибация (ядро приёмки)

Загрузка записи 5–10 минут через UI → дождаться транскрипта. Приёмка:

```bash
kubectl -n gpustack exec gpustack-server-0 -- bash -lc 'export PGPASSWORD=$(cat /var/lib/gpustack/postgres_root_pass); psql -h 127.0.0.1 -U root -d gpustack -tA -c "select name,state from model_instances;"'
```
- в GPUStack-логе модели видны запросы `/v1/audio/transcriptions`;
- транскрипт содержит таймкоды, время обработки и точность фиксируются замером (для репетиции);
- саммари строится (`gemma-4-12B`) — либо явно фиксируется, что `TEXT_MODEL_*` не настроены.

### S6. Публикация и путь

```bash
curl -s -o /dev/null -w '%{http_code}\n' --resolve spk.demo-ai-lab.ru:443:192.168.10.230 https://spk.demo-ai-lab.ru/
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 https://spk.demo-ai-lab.ru/     # снаружи
```
Приёмка: LAN `200` (после редиректа на `/login`), edge `200`, серт `CN=spk.demo-ai-lab.ru`;
загрузка файла 100+ МБ через edge не рвётся (проверка лимитов ингресса).

## 7. Операции

| Задача | Как |
|---|---|
| Health | `kubectl -n spk get pods`; TCP 8899; `scripts/k8s_health.py --brief` |
| Бэкап | `kubectl -n spk scale deploy/speakr --replicas=0` → снапшот Longhorn тома → `scale 1` (SQLite: копия только на остановленном) |
| Апгрейд | поднять тег в манифесте (`0.10.x-alpha-lite`) → `Sync`; проверить миграции `init_db.py` в логе, при провале — откат тега |
| Переезд на Postgres | `SQLALCHEMY_DATABASE_URI=postgresql://…` + отдельный под PG; миграции данных между БД нет — только при пустой базе |
| Ротация ключа GPUStack | обновить `Secret spk-secrets` → `rollout restart` |
| Ротация `SECRET_KEY` | разлогинивает всех |
| Лимит размера файла | админка → `max_file_size_mb` (дефолт 250); `MAX_CONTENT_LENGTH` пересчитывается на старте |

## 8. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-S1** | Только `-alpha`-теги: `0.10.16-alpha` — не стабильный релиз | фиксируем точный тег + digest, апгрейд только осознанно; откат = предыдущий тег |
| **R-S2** | `-lite` без PyTorch: нет semantic search в Inquire Mode | принято: Inquire не показываем; при необходимости — полный образ (3,3 GiB, канал) |
| **R-S3** | SQLite + RWO: один под, `Recreate`; при потере узла простой до переаттача | RTO 1–3 мин, репетиция; в сценарии шага 2 spk — не первый слайд |
| **R-S4** | `gunicorn --timeout 600`: загрузка/обработка дольше 10 минут рвётся на уровне приложения | лить готовые файлы; очередь внутри приложения уже принятого файла не страдает; большие записи резать |
| **R-S5** | `ALLOW_REGISTRATION` по умолчанию `true` | явный `false` + проверка в S4 |
| **R-S6** | `SSO_REQUIRE_VERIFIED_EMAIL=true` и Keycloak без `email_verified` → вход режется | проверить claim в токене при S4; при необходимости — пользователям выставить verified в Keycloak |
| **R-S7** | Диаризации нет: расшифровка «кто говорил» недоступна | зафиксировано в §1; при требовании — отдельный контейнер WhisperX ASR (второй потребитель VRAM, вне бюджета ADR-0007) |
| **R-S8** | Образ от root, старый Flask-стек, AGPL-3.0 | только внутри стенда, наружу — публичный сервис без админ-функций; лицензия не используется в продукте |
| **R-S9** | Лимиты загрузки/таймауты Higress для 250 МБ файлов не проверены | S6 отдельным шагом: загрузка 100+ МБ через edge, при обрыве — аннотации ингресса |

## 9. Что забывают в таких спеках (и что решено здесь)

| Пункт | Решение |
|---|---|
| Коннектор ASR | `openai_whisper` (а не `asr_endpoint`, который стучится в `/asr`) |
| Ключ `SECRET_KEY` | постоянный, иначе сессии теряются при рестарте |
| Пробы | `/health` нет — TCP-проба |
| Регистрация | выключена явно |
| Диаризация | отсутствует осознанно, записано в §1/§8 |
| Бэкап SQLite | только при остановленной реплике |

Открытые вопросы:

1. **Диаризация:** нужна ли на демо (тогда отдельный WhisperX-контейнер и второй ASR — VRAM не из
   бюджета ADR-0007) или достаточно транскрипта. *(Рекомендация: без диаризации.)*
2. **Хранение аудио:** оставлять исходники в `/data/uploads` (растёт том) или архивировать после
   транскрипции. *(Рекомендация: оставлять, 20 GiB хватает на демо.)*

## 10. Связанные документы и история версий

- `architecture/endpoints.md` — адрес `spk`, SSO.
- `architecture/gpustack-spec.md` — ASR-модель `whisper-turbo`, ключи API.
- `architecture/keycloak-spec.md` — клиент `spk`, сид.
- `references/demo-plan.md` — RAM-бюджет шага 2 (`Speakr+whisper ≈2G` на 03).

| Версия | Дата | Что |
|---|---|---|
| v1.2 | 2026-10-28 | **`TRUSTED_PROXY_HOPS` 2 → 1**: вход «не проходил по 10 раз» — при двух хопах ProxyFix оставлял `remote_addr` = адрес пода Higress, flask-limiter держал ОДНО ведро `10 per 1 minute` на `/auth/sso/login` для всех клиентов, после чего отдавал `429`. Проверка после правки: 10×`302`, затем `429` с `192.168.10.200` (реальный IP); полный SSO-цикл `user-test` и `admin-test` → `/auth/sso/callback` → `https://spk.demo-ai-lab.ru/` 200 |
| v1.1 | 2026-10-28 | **Развёрнуто через Argo CD** (`gitops/apps/spk`, Application `spk` — Synced/Healthy): S1 — ключ модели `demo-step2` (общий с `owu`) доступен из пода (`/v1/models` → 200); S2 — Secrets `spk-secrets`/`spk-oidc` созданы до синка, клиент Keycloak `spk` заведён сидом, `redirectUris` сверены admin-API; S3 — под 1/1, PVC 20Gi Bound, LAN `/` → 302 `/login`, `/login` → 200. Образ, коннектор `openai_whisper` и SSO-переменные — как в §4 без правок. S4–S6 не сняты |
| v1.0 | 2026-10-28 | Первая версия. Живой замер: digest и размеры `-lite`/`-alpha`, отсутствие Helm-чарта (репозиторий + Artifact Hub), коннекторная архитектура ASR (ловушка `asr_endpoint` vs `openai_whisper`), SSO-переменные и callback из кода, `ALLOW_REGISTRATION=true` по умолчанию, свободная RAM 03, состояние `whisper-turbo`. Не установлено |
