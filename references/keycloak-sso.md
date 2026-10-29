# Keycloak (SSO) на стенде demo-ai-lab

Источник истины — `architecture/specs/keycloak-spec.md` в репо (решения, фазы K1–K7, приёмка), адреса сервисов —
`architecture/endpoints.md` (короткие имена `owu`/`rag`/`spk`/`qm`/`her`, `api`, `auth`). Здесь только
то, что нужно помнить, когда спекой пользуешься. Развёртывание — **Argo CD** (`gitops/infra-apps/keycloak/`),
ns `keycloak`, внешнее имя `https://auth.demo-ai-lab.ru`. **Размещение: пара k8s-02/03, две реплики
Keycloak + PostgreSQL; k8s-04 НЕ использовать** — там на демо GPUStack/инференс (см. раздел о
размещении ниже).

## Пины и проверка

- Keycloak **26.8.1** `quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b`
  (JVM 21). Реестр `quay.io` со стенда доступен — проверяется пробным подом (`kc.sh --version`).
- PostgreSQL **17.11** (`postgres:17.11@…`), PVC 8 Gi на `longhorn`, подкаталог `PGDATA=/var/lib/postgresql/data/pgdata`
  (иначе `lost+found` в корне тома).

## Конфигурация Keycloak, которая работает за Higress

```
start --hostname=https://auth.demo-ai-lab.ru --http-enabled=true
      --hostname-backchannel-dynamic=true
      --proxy-headers=xforwarded --proxy-trusted-addresses=10.0.0.0/8
      --health-enabled=true --metrics-enabled=true --cache-stack=jdbc-ping --log=console
```

- **hostname v2 — только полный URL.** `KC_HOSTNAME_URL` больше нет; Keycloak намеренно не вычисляет
  issuer из заголовков (защита от подмены). Проверка: issuer в discovery — дословно
  `https://auth.demo-ai-lab.ru/realms/<realm>`, без `http://` и внутренних адресов.
- **TLS терминирует Higress** → `--http-enabled=true`; `--proxy-trusted-addresses` = pod-сеть Cilium
  `10.0.0.0/8` (gateway-поды живут в `10.0.2.x`/`10.0.0.x`; `10.42.x` из `.spec.podCIDR` — не она).
- **`--hostname-backchannel-dynamic=true`** — серверные вызовы приложений из кластера могут идти на
  `http://keycloak.keycloak.svc:8080` и не зависеть от туннеля Cloudflare (риск R1). Фронтовые URL остаются внешними.
- **Health — management-порт 9000**: `/health/started|live|ready`. `curl` В ОБРАЗЕ НЕТ — проверять
  probes'ами/`port-forward`/снаружи, не `kubectl exec ... curl`.
- `--health-enabled/--metrics-enabled` — build-time опции → первый старт делает implicit build: поднимается
  дольше (до ~3 мин), `startupProbe` с запасом (5×60 c). Это не падение.
- **Две реплики — `--cache-stack=jdbc-ping`**: кэш сессий делится через БД, sticky-сессии не нужны,
  пользователь не теряет логин при потере пода/узла. `--cache=local` — только когда реплика одна
  (иначе каждый экземпляр живёт своей сессией). `strategy: RollingUpdate, maxUnavailable: 0` — выкатка
  без простоя SSO; `Recreate` вернул бы простой на каждой правке манифеста.

## Размещение и отказоустойчивость (не прибивать к одному узлу)

Живые цифры стенда (проверять заново): k8s-01 30.5 Gi allocatable/2.8 Gi занято (в планах RAGFlow/Docling —
спайки, диск самый изношенный), **02 и 03 по 14.8 Gi/~3.3 Gi занято (~11 Gi свободно, там же etcd, Higress,
Argo)**, k8s-04 28 Gi (метрики + Longhorn instance-manager, на демо — GPUStack). SSO-нагрузка — 768 Mi
requests на реплику, т.е. это ЛЁГКИЙ сервис: ему место на паре ingress-узлов, а не рядом с инференсом.

- **Hard `nodeSelector` = нет переезда.** При потере узла под висит `Pending` до возврата железа — «прибили
  к железу» превращается в «SSO мёртв весь демо, хотя три узла свободны». Только `preferred`
  `nodeAffinity` (не `required`) + `preferred` `podAntiAffinity` по `app: <svc>`: реплики расходятся по
  узлам, но при потере обоих не залипают, а садятся куда есть место.
- Матрица, которой обосновываем выбор в спеке: ребут 04 → SSO жив (04 не участвует); падение 02/03 →
  логин не рвётся (вторая реплика с общим кэшем); падение узла с PostgreSQL → 1–3 мин без логина
  (переаттач тома Longhorn) — **БД остаётся SPOF**, r=2 спасает данные, не доступность; **HA-БД не
  планируется** (решение 2026-10-24: демо, не прод).
- Приёмка размещения — drill в финальной фазе: `delete pod` реплики (логин и discovery 200 не рвутся),
  затем `scale --replicas=1` (имитация потери узла), вернуть 2. Если логин рвётся — `jdbc-ping` не поднялся
  (смотреть `Keycloak cluster health` в `/health/ready`).
- Предтяжка образов — на ОБА узла пары (иначе первый переезд снова тянет 450 МБ по 4–6 МБ/с), NTP — тоже
  на обоих (расхождение часов валит и JWT, и кластерный кэш).

## Учётные записи и реалм

- `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` (бывшие `KEYCLOAK_ADMIN*`) действуют **только на первом старте**,
  пока нет master-реалма: смена значения в файле кластер не меняет. Порядок: сменить пароль через
  Admin Console/`kcadm` → убрать env из Deployment правкой в git.
- Реалм приложений — `dev`; роли `app-user` и `app-admin` (композит, включает `app-user`).
  Пользователи `user-test`/`admin-test` — **не** админы Keycloak: master-реалм отдельно.
- Пароли ставить `temporary=false`, иначе первый вход упрётся в смену пароля.
- SMTP на стенде нет → `registrationAllowed=false`, `resetPasswordAllowed=false`, `verifyEmail=false`,
  `bruteForceProtected=true`.
- Клиент `smoke-cli` — public + direct access grant, только для приёмочного password-grant в curl;
  клиенты сервисов (`owu`/`rag`/`spk`/`qm`/`her`) — confidential, redirect URI берётся из доки/лога сервиса
  (не угадывать) и сразу плюс post-logout URI `https://<host>/*`.
- **Служебные UI:** SSO подключаем **только к GPUStack** из служебных UI (решение 2026-10-24) — клиент `gps`,
  redirect `<server-url>/auth/oidc/callback`, issuer `https://auth.demo-ai-lab.ru/realms/dev`,
  env через `server.environmentConfig` чарта 2.2.3 (`GPUSTACK_OIDC_*`), `EXTERNAL_AUTH_DEFAULT_INACTIVE=true`
  (роли раздаём руками). **Argo CD SSO не получает** — локальный admin-пароль, UI наружу не публикуется.
- **M2M (шаг 4):** один клиент `agent-runtime` — client-credentials, service account, роль `agent-service`,
  токен 300 с без refresh, секрет в k8s Secret. Валидация токена — на Higress (`jwt-auth` по JWKS),
  аудит вызовов — по логам Higress; отдельный аудит в Keycloak-событиях не включаем.
- **Docling — без SSO и без авторизации** (решение 2026-10-24): публичный маршрут, OIDC-клиента нет.

## Секреты и операции

- Файлы: `keycloak-admin.local.md` (bootstrap-админ + учётка БД), `keycloak-users.local.md`,
  `keycloak-clients.local.md` — в `.gitignore` через `*.local.md`, `0600`. Secret'ы `keycloak-db`,
  `keycloak-bootstrap` создаёт скрипт (Argo их не знает и не удаляет).
- Ротация БД-пароля: файл → скрипт (Secret) → `rollout restart deploy/keycloak`.
- Бэкап до апгрейда: `kubectl -n keycloak exec postgres-0 -- pg_dump -U keycloak -Fc keycloak > <локальный-каталог-бэкапов>/kc-<дата>.dump`
  (дампы вне репо — в них хэши). Восстановление: scale Keycloak 0 → `pg_restore --clean --if-exists` → scale 1.
- **Админка публичного `auth.*` — план Б (решение 2026-10-24):** Keycloak доступен из интернета
  целиком, включая `/admin` и `/realms/master*`; Cloudflare Access **не заводим**. Защита —
  `bruteForceProtected` (5 неудач → `temporarily disabled`), пароль master ≥28 симв. только в
  `keycloak-admin.local.md`, снятие `KC_BOOTSTRAP_ADMIN_*` после K5, контроль логов. Возврат гейта —
  если стенд станет больше, чем демо (Access строго по путям).

## Грабли

- TLS-секрет wildcard из `demo-test` не переиспользуется (namespace-local) — свой `Certificate`.
- Не дёргать перевыпуск сертификата в цикле: LE 50 сертов/нед на домен.
- Вызов к `master` снаружи — это открытый канал брутфорса админа (принято осознанно, план Б): следить
  за `temporarily disabled` в логах и не оставлять bootstrap-пароль в манифесте.
- Пустой ответ edge (`530`) — это R1-шторм канала, а не Keycloak: LAN-путь проверять отдельно.
