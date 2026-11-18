# Hermes Agent — агентский рантайм стенда (`hm.demo-ai-lab.ru`): SSO, MCP, две модели

> **Версия:** v1.5 (2026-11-14) · **Статус:** **развёрнуто 2026-11-06** — ns `her`, под 1/1 Running на
> **k8s-03** (замер 14.11; манифест возвращает пару k8s-02/03 — под переедет при следующем rollout), панель
> `https://hm.demo-ai-lab.ru` за SSO Keycloak (клиент `hm`, публичный PKCE),
> MCP `doc.` + `ysrch.` подключены и вызываются моделью, `deepseek-flash` через `llm-svc.` отвечает.
> Сняты **H1–H5**, H6 — до браузерного входа владельца; H7–H10 открыты. Журнал и отклонения от плана — §13.
> **v1.5:** **GitHub MCP включаем** (решение владельца 2026-11-14) — отдельный self-host сервер в ns
> `mcp-github`, только ClusterIP, токен per-request (§7.1). **Не установлен**: раскатка и приёмка — H10;
> egress `api.github.com` замерен 14.11 (200 из пода `hermes`), строка в allowlist ISP — действие владельца.
> **Цель:** шаг 4 демо — агент, который работает на стенде «изнутри»: веб-панель за **SSO Keycloak**,
> инструменты — **MCP-серверы стенда** (`doc.`, `ysrch.`), основная модель — **`deepseek-flash` через
> `llm-svc.`** (внешний DeepSeek за шлюзом с DLP и стражем), вторая — **локальная `Qwen3.8-27B-UD`
> через `api.`** (GPUStack, кейс 01). Агент живёт в кластере и показывает: вход по SSO, вызов MCP-инструмента
> стенда, ответ модели «снаружи» и ответ локальной 27B — без единого шага мимо шлюза.
> **Внешнее имя:** `hm.demo-ai-lab.ru` — LAN через split-DNS на `.230`, снаружи — edge (ADR-0004).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/her/` (plain-манифесты, как `spk/`, `doc/`);
> Secret'ы создаются **до** первого синка и в git не попадают.
> Ничего секретного в этом документе нет: ключи — в `her.local.md` (в `.gitignore`), в кластере — Secret `her-secrets`.

Стиль-образцы: `architecture/specs/k8s-install-spec.md` (F\*), `architecture/specs/keycloak-spec.md` (K\*),
`architecture/specs/llm-proxy-spec.md` (P\*), `architecture/specs/gpustack-spec.md` (G\*).
Эта спека занимает букву **H**. Решения ADR не пересматриваются: ADR-0006 (DLP/страж), ADR-0008
(внешний LLM только через шлюз), ADR-0003 (размещение).

## 0. Что уточнила сверка с исходниками (2026-11-06)

Сверялись: документация Hermes (`hermes-agent.nousresearch.com/docs`, страницы `web-dashboard`,
`user-guide/docker`, `features/mcp`, `features/browser`, `configuring-models`, `mcp-config-reference`)
и `hub.docker.com/v2/repositories/nousresearch/hermes-agent`. Всё, что ниже — факт из этих источников,
а не предположение из общего вида «агент в контейнере».

| Что | Ожидание «по аналогии» | Факт (проверено 2026-11-06) |
|---|---|---|
| SSO панели | «как у OWU: OIDC confidential client + `client_secret`» | **Самописный client_secret не поддерживается.** Панель (`dashboard`) ходит в IdP встроенным плагином `dashboard_auth/self_hosted`: **стандартный OIDC, только публичный клиент + PKCE S256** (`confidential clients … not supported yet`). Секрета у клиента быть не должно |
| Что именно проверяет плагин | «проверит токен как OWU» | Проверяется **ID-token** (RS256/ES256) по `jwks_uri` из `{issuer}/.well-known/openid-configuration`, `iss` и `aud` прибиты к `issuer`/`client_id`; access-token считается непрозрачным. Расхождение часов допускается 60 с (`dashboard.oauth.self_hosted.id_token_leeway`) |
| Когда включается гейт | «флагом» | Гейт включается **самим фактом не-loopback bind**: `HERMES_DASHBOARD_HOST=0.0.0.0` → гейт ON. Флага «выключить» нет: `--insecure` объявлен no-op; **без провайдера панель не стартует вообще** (fail-closed) |
| Права вошедшего | «роли из Keycloak» | Любой, кого пустил IdP, получает **права владельца машины**: ролей/групп Hermes не проверяет (`Every account that can sign in acts as you`). Ограничение доступа — **только на стороне Keycloak** |
| Порт и данные | «пробросить 8080, том в `~/.hermes`» | Панель — **9119** (`HERMES_DASHBOARD=1`), gateway-API — **8642** (только при `API_SERVER_ENABLED=true`). Всё состояние — один каталог **`/opt/data`**; `/opt/hermes` в опубликованном образе **неизменяем** (self-update отключён маркером) |
| Процессы | «один процесс, упадёт — перезапустим подом» | В образе **s6-overlay**: `gateway run` — heartbeat-`sleep`, gateway и панель — supervised-сервисы, рестарт за секунды без пересоздания контейнера |
| MCP | «отдельный клиент/прокси» | MCP-клиент встроен: `mcp_servers.<имя>` в `config.yaml`, HTTP-транспорт — просто `url`, доп. заголовки — `headers`, `${VAR}` резолвится из `.env`/окружения профиля. Фильтр инструментов — `tools.include`/`tools.exclude` |
| Браузер: подключение внешнего | «только `/browser connect`, как в CLI» | Есть **постоянный** эндпоинт: `browser.cdp_url` в `config.yaml` или `BROWSER_CDP_URL` в окружении — с ним `browser_exec`/`browser_cdp`/`browser_dialog`/`browser_vault` работают с чужим браузером, а свой Chromium не поднимается. `/browser connect` — интерактивная команда CLI, гейтвеем не диспатчится (для пода не годится). Побочный эффект CDP-эндпоинта: включается guard приватных адресов (`security.allow_private_urls`) |
| Браузер | «нужен Playwright/npm install» | **Playwright не нужен и в рантайме недоступен**: `browser_exec` поднимает свой Chromium, в официальном образе он уже внутри (`/etc/hermes/chromium-executable-path`). Рантайм-установки в `/opt/hermes` запрещены — «доустановить playwright» можно только сборкой своего образа |
| Провайдеры | «только облачные из списка» | Есть `providers:` (словарь) с `base_url` + `api_key: "${VAR}"`, плюс `model.aliases.<имя>` с `key_env`. Любой OpenAI-совместимый эндпоинт подключается без плагинов |
| Контекст | «любая модель» | Hermes **отказывается стартовать на модели с окном < 64 000 токенов**. `deepseek-flash` (128K) и `Qwen3.8-27B-UD` (128K) проходят; `gemma-4-12B` с `--max-model-len 4096` — нет |

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ | `nousresearch/hermes-agent:v0.23.0@sha256:adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002` (индекс; amd64-манифест `sha256:0dd31821db01611eaeedc44743260336c2d72bff47b9117b06313b29ca85ad76`, 1,12 ГБ) | digest снят с Docker Hub API 2026-11-06; тег `v0.23.0` = `stable` = `latest` на ту же дату. Пин по digest: тег `latest` двигается, стенд не должен меняться от чужого релиза |
| Namespace | `her` (создаёт ApplicationSet `apps` по имени каталога; Secret'ы — до первого синка) | паттерн `gitops/apps/*`; один ns на сервис |
| Реплики | **1** (`strategy: Recreate`) | состояние — SQLite `/opt/data/state.db` в WAL; два писателя в один том не поддерживаются. Цена — RTO ≈ 1–3 мин на переаттач тома Longhorn (§8) |
| Размещение | `required` — **k8s-01/02/03**; `preferred` — пара **k8s-02/03** (`demo-ai-lab/role in [ingress]`); k8s-04/05 не занимать | 04 — GPUStack/инференс, 05 — Firecrawl; падение пода 04 не должно уносить панель. Замер 2026-11-14: на 02 занято 11,3 Gi из 15,5 (requests 10,6), на 03 — 10,2 (requests 11,3), Hermes — 0,92 Gi → 02/03 проходят по RAM; `required` по 01 оставляет запас, если пара занята. R-H16 закрыт, см. §11 |
| Ресурсы | requests `500m`/`1Gi`, limits `2`/`4Gi` | панель + gateway + Chromium в одном поде; Chromium — главный потребитель. Цифры **предварительные**: уточняются замером `kubectl top` в H1/H3 |
| Данные | PVC **10 Gi**, SC `longhorn` (r=2), `mountPath: /opt/data` | сессии, память, скиллы, cron, логи, `auth.json`; WAL на блочном томе Longhorn корректен (запрет из доки — про virtiofs/9p, не про PVC) |
| TLS | `Certificate hm` в ns `her`, ClusterIssuer **`letsencrypt-http01`** (HTTP-01), срок 90 дней с автопродлением | DNS-01 невозможен (зона на reg.ru), поэтому валидация идёт HTTP-01: LE → публичный `:80` (haproxy на VM, 301 на https) → `:443` → SSH-hop'ы → Higress → солвер. Выпущено 2026-11-06, CN `hm.demo-ai-lab.ru`, до 04.02.2027 (§13 п.7, п.12) |
| Ingress | один, класс `higress`, host `hm.demo-ai-lab.ru`, `/` → `service/hermes:9119`, TLS | панель и API — с одного порта; WebSocket `/api/ws` идёт тем же маршрутом |
| Публичность | **сначала только LAN**: тот же allowlist, что `argo`/`hgc`/`mon` (`WasmPlugin lan-only-ui`, `gitops/infra-apps/infra/lan-only-ui.yaml`). Открытие наружу — отдельный шаг H7 **после** приёмки SSO и ограничения по роли | панель даёт права владельца машины; `her.` уже резолвится (split-DNS + wildcard), значит **любой заведённый Ingress сразу публикуется** наружу. Порядок «сначала LAN, потом край» — правило E6/ADR-0004 |
| Авторизация | OIDC Keycloak realm `dev`, клиент **`hm` — публичный, PKCE S256**, redirect `https://hm.demo-ai-lab.ru/auth/callback` | §0: confidential-клиент панелью не поддерживается. **Правка плана:** в `architecture/endpoints.md` клиент `hm` записан как `confidential` — при заведении он создаётся **публичным**; таблицу правим после H6 |
| Ограничение доступа людей | realm-роль `her-user` + copy browser-flow с `Condition - user role` на клиенте `her` | Hermes ролей не проверяет (§0), значит «пускать только своих» можно только в Keycloak. Без этого любой `user-test`/`admin-test` = владелец агента |
| Break-glass | **нет** второго провайдера входа (basic auth не заводим); аварийный доступ — `kubectl exec` + `hermes` CLI внутри пода | лишний пароль на публичном хосте — поверхность атаки; CLI в поде закрывает ту же задачу без второй учётки |
| Браузер | **Chromium официального образа, в том же контейнере** — решение владельца 2026-11-06; вынос по CDP (sidecar / отдельный под) **отложен**, условия пересмотра — §8.1 | профиль на сессию, ни одного лишнего сетевого эндпоинта, guard приватных адресов не включается; изоляция памяти — вопрос замера, не архитектуры |
| Терминал агента | `terminal.backend: local` (shell **в поде**), Docker-сокет **не монтируется** | у агента нет доступа к containerd/kubelet и к данным других ns; `docker`-backend в поде без сокета не работает и не нужен |
| Gateway-API | `API_SERVER_ENABLED` **не включаем** (8642 не слушаем, наружу не выставляем) | OpenAI-совместимый API агента не нужен демо, а без ключа (`API_SERVER_KEY`) он был бы открытым |
| Конфигурация | `config.yaml` — из ConfigMap через initContainer-сид (копируется в PVC, если файла нет); секреты — из Secret в окружение | ConfigMap, смонтированный файлом поверх PVC, ломает `hermes config set` (read-only); сид идемпотентен и не затирает правки, сделанные в панели |
| PriorityClass | `demo-stand-critical` (уже создан каталогом `keycloak`, **не пересоздавать**) | панель должна отвечать во время показа; на 02/03 при RAM-давлении поды без класса (0) эвиктятся первыми |
| Секреты | `her-secrets` (ключ `llm-svc`, ключ GPUStack), создаётся `scripts/her_secrets.sh` из `her.local.md` | AGENTS.md: приватные файлы в git не попадают, Secret'ы — не через Argo |
| Мониторинг | HTTP-монитор Kuvasz `https://hm.demo-ai-lab.ru/api/status`, плюс пробы пода | `/api/status` отдаёт `auth_required`/`auth_providers` без входа — идеальная дешёвая проба (ADR-0009) |

**Вне спеки:** мессенджеры (`gateway` как Telegram/Discord-бот — egress закрыт, каналов нет), второй
профиль/мультипрофильный режим, RAG самого агента, fine-tune, `dsh` (отдельный рантайм шага 4),
внешние облачные браузеры и Tool Gateway Nous (подписки на стенде нет).

## 2. Предпосылки — проверено 2026-11-06

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get nodes -o custom-columns='NODE:.metadata.name,RAM:.status.allocatable.memory,CPU:.status.allocatable.cpu'
# k8s-01 24286908Ki/16 · k8s-02 15548848Ki/12 · k8s-03 15548844Ki/12 · k8s-04 32036368Ki/16
kubectl top nodes
# 01: 11 955Mi (50%) · 02: 7 933Mi (52%) · 03: 10 023Mi (66%) · 04: 15 443Mi (49%)
kubectl get apps -n argocd
# argocd, doc, gpustack, infra, keycloak, llm, mcp-registry, owu, root-app, spk, ysrch — все Synced/Healthy
kubectl get ingress -A | grep -c higress     # 19 Ingress'ов; her. среди них НЕТ (это план)
dig +short @192.168.10.1 hm.demo-ai-lab.ru  # 192.168.10.230 — имя уже резолвится, маршрута нет
```

| Что | Факт (2026-11-06) | Следствие для H |
|---|---|---|
| DNS | `hm.demo-ai-lab.ru` → `192.168.10.230` из LAN, снаружи — wildcard Cloudflare | DNS не заводим; **как только появится Ingress, хост публикуется** — отсюда порядок H5→H7 |
| `hm.` сейчас | `curl https://hm.demo-ai-lab.ru/` → `000` (Higress сбрасывает TLS на неизвестном SNI) | ожидаемо до деплоя; критерий H5 — `200`/`302` |
| `llm-svc.` | `GET /v1/models` без ключа → **401** | маршрут живой, ключ обязателен; список моделей — `deepseek-flash`, `deepseek-v4-pro` (`llm-proxy-spec` §2) |
| `api.` (GPUStack) | `GET /v1/models` без ключа → **401** | ключ GPUStack обязателен; 27B отдаётся как обычная OpenAI-модель |
| `doc.` | `GET /health` → **200** | MCP-сервер доступен, авторизации нет (`doc-spec` §1) |
| Образ | `v0.23.0`, amd64-манифест `sha256:0dd31821…`, 1,12 ГБ, запушен 2026-11-05 | предтяжка обязательна (H1): образ крупный, канал 4–6 МБ/с |
| Keycloak | 26.8.1, `https://auth.demo-ai-lab.ru`, realm `dev`, роли `app-user`/`app-admin`/`agent-service`, клиенты `smoke-cli`/`gps`/`agent-runtime`/`mcp`; клиента `her` **нет** | клиент `hm` + роль `her-user` создаются в H6 и вносятся в сид `scripts/keycloak_seed.py` (ручные правки в UI не считаются) |
| GPU-резиденты | на 5070 Ti: стражи `Qwen3Guard-Gen-4B` (внешний маршрут) **или** `Qwen3.8-27B-UD` (кейс 01) — не одновременно | `llm-svc.` и 27B **взаимоисключающие** (§6): в кейсе 01 внешний маршрут отдаёт `503` (страж снят, fail-closed) |
| NTP | ноды синхронизированы (k8s-install F0) | JWT/ID-token с допуском 60 с — расхождение внутри допуска |

## 3. Секреты

| Файл / объект | Что внутри | Кто читает |
|---|---|---|
| `her.local.md` (корень репо, gitignored) | `llm_svc_key:`, `gpustack_key:`, `kuvasz_mcp_key:` (последний — после ADR-0009), `github_pat:` (для §7.1) | `scripts/her_secrets.sh` (awk `-F': '`), человек при ротации |
| Secret `her-secrets` (ns `her`) | `HER_LLM_SVC_KEY`, `HER_GPUSTACK_KEY`, `KUVASZ_MCP_TOKEN`, `HER_GITHUB_PAT` (последний — при раскатке H10) | под `hermes` (env), ссылки в `config.yaml` — `${HER_…}`; под `github-mcp` секретов **не** получает (§7.1) |
| Secret `llm-apikey` (ns `llm`) | ключи потребителей `llm-svc`, `llm-svc-bearer`, **`llm-svc-her`** (новый) | `key-auth` на `llm-svc.` |
| `keycloak-clients.local.md` | `client_id: hm` (значение не секрет — публичный клиент; в файле фиксируется факт + redirect) | человек, сид Keycloak |

- **Отдельный потребитель `llm-svc-her`.** Ключ Hermes не переиспользует `llm-svc`-ключ OWU/Speakr:
  `key-auth` присваивает `X-Mse-Consumer`, а на нём висят квоты `ai-token-ratelimit`
  (`gitops/apps/llm/62-wasm-token-ratelimit.yaml`). Отдельный consumer = отдельная квота и
  отдельный отзыв без перезапуска чужих сервисов. Правка — третий элемент в `consumers`/`keys`
  шаблона `gitops/apps/llm/templates/wasm-key-auth.yaml.tpl` + значение в `llm-apikey`.
  Bearer-вариант (`Authorization: Bearer <ключ>`) уже поддержан отдельным consumer'ом
  `llm-svc-bearer` — Hermes как OpenAI-клиент ходит именно так.
- Ключ GPUStack — **свой** (`her-27b`), с доступом только к `Qwen3.8-27B-UD`: кейс 01 показывает
  именно выдачу узкого ключа (case 01, шаг 7). Ключи `owu`/`spk`/`beellama-test` не трогаем.
- **GitHub PAT — только fine-grained и read-only.** `github_pat:` в `her.local.md` → `HER_GITHUB_PAT`
  в Secret `her-secrets`; права: `Contents: Read`, `Issues: Read`, `Pull requests: Read`,
  `Metadata: Read` (автоматически) и только на нужные репозитории (`msklv/demo-ai-lab`).
  **Classic `ghp_` не берём:** скоупы шире нужного, и сервер на каждый запрос делает лишний `HEAD`
  к `api.github.com` за `X-OAuth-Scopes` (у fine-grained этого нет, §7.1). Токен живёт только в
  поде `hermes` (env → заголовок запроса); под `github-mcp` не получает секретов вовсе.
  `scripts/her_secrets.sh` дополняется парой `HER_GITHUB_PAT` при раскатке H10 — до этого ключа в
  Secret нет и H10 не начинается.
- Гигиена перед коммитом: `git ls-files | grep -E '\.local\.(md|pem)$|(^|/)\.env'` → rc=1;
  `git check-ignore -v her.local.md` → матчится правилом `*.local.md`.

## 4. Развёртывание

### 4.1 Состав каталога

```
gitops/apps/her/
├── 00-namespace.yaml        # ns her (Argo CreateNamespace=true тоже умеет, файл — для явности)
├── 10-pvc.yaml              # 10Gi longhorn, RWO
├── 15-configmap.yaml        # config.yaml (шаблон §4.4) + seed-скрипт не нужен
├── 20-deployment.yaml       # initContainer-сид + hermes (gateway run + панель)
├── 30-service.yaml          # ClusterIP 9119
├── 40-ingress.yaml          # hm. + Secret hm-demo-tls
└── README.md                # runbook: секреты, сид Keycloak, приёмка
```

Порядок: Secret `her-secrets` (+ правка `llm-apikey` и `key-auth`) → `kubectl apply -f gitops/apps/her/`
(или push в `main`, Application создаст ApplicationSet `apps`) → H3–H9.

### 4.2 Deployment — ключевые поля

```yaml
spec:
  replicas: 1
  strategy: { type: Recreate }                  # SQLite: второй писатель недопустим
  template:
    spec:
      priorityClassName: demo-stand-critical
      securityContext: { fsGroup: 1000 }        # uid образа сверить в H1 (`id` в поде)
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference: { matchExpressions: [ { key: demo-ai-lab/role, operator: In, values: [ingress] } ] }
      initContainers:
        - name: seed-config
          image: <тот же пин, что ниже>          # лишний образ не тянем
          command: ["sh","-c","[ -s /opt/data/config.yaml ] || cp /seed/config.yaml /opt/data/config.yaml"]
          volumeMounts:
            - { name: data, mountPath: /opt/data }
            - { name: seed, mountPath: /seed }
      containers:
        - name: hermes
          image: nousresearch/hermes-agent:v0.23.0@sha256:adb789…f0fc002
          command: ["gateway","run"]            # s6 сам поднимет gateway + панель
          env:
            - { name: HERMES_DASHBOARD,             value: "1" }
            - { name: HERMES_DASHBOARD_HOST,        value: "0.0.0.0" }   # иначе панель слушает loopback контейнера
            - { name: HERMES_DASHBOARD_PUBLIC_URL,  value: "https://hm.demo-ai-lab.ru" }
            # BROWSER_CDP_URL НЕ задаём: браузер — Chromium из образа (§8.1, решение 2026-11-06)
          envFrom: [ { secretRef: { name: her-secrets } } ]
          ports: [ { containerPort: 9119, name: http } ]
          readinessProbe: { httpGet: { path: /api/status, port: 9119 }, initialDelaySeconds: 30, periodSeconds: 10 }
          livenessProbe:  { httpGet: { path: /api/status, port: 9119 }, initialDelaySeconds: 60, periodSeconds: 30, failureThreshold: 6 }
          resources: { requests: { cpu: 500m, memory: 1Gi }, limits: { cpu: "2", memory: 4Gi } }
          volumeMounts:
            - { name: data, mountPath: /opt/data }
            - { name: shm,  mountPath: /dev/shm } # Chromium без этого падает: дефолт 64 МиБ
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: hermes-data }
        - name: seed
          configMap: { name: her-config }
        - name: shm
          emptyDir: { medium: Memory, sizeLimit: 512Mi }
```

Почему так (все пункты — из §0, не «на всякий случай»):

- **`HERMES_DASHBOARD_HOST=0.0.0.0` + `PUBLIC_URL`** — панель в контейнере по умолчанию слушает
  loopback; `PUBLIC_URL` нужен, чтобы callback собирался как `https://hm.demo-ai-lab.ru/auth/callback`
  (за прокси `X-Forwarded-*` можно и не увидеть), и чтобы точный `Host` был принят запросом
  (панель отбивает чужой `Host` как защиту от DNS-rebinding).
- **`/dev/shm` в память** — Chromium использует разделяемую память; при 64 МиБ headless-браузер
  в контейнере падает на старте. Нужен **только** пока браузер живёт в контейнере агента; при выносе
  браузера по CDP (§8.1) `/dev/shm` переезжает в контейнер-браузер. Альтернатива (`--disable-dev-shm-usage` в `browser.chromium_args`) —
  хуже: на диск и медленнее.
- **`Recreate`** — том один, реплика одна.
- **`gateway run`** — единственная поддерживаемая «долгая» команда образа; панель включается
  переменной и живёт под s6 рядом с gateway.

### 4.3 Service и Ingress

```yaml
kind: Service
metadata: { name: hermes, namespace: her }
spec: { selector: { app: hermes }, ports: [ { name: http, port: 9119, targetPort: 9119 } ] }
---
kind: Ingress
metadata:
  name: her
  namespace: her
  annotations: { cert-manager.io/cluster-issuer: letsencrypt-wildcard }
spec:
  ingressClassName: higress
  tls: [ { hosts: [hm.demo-ai-lab.ru], secretName: hm-demo-tls } ]
  rules:
    - host: hm.demo-ai-lab.ru
      http: { paths: [ { path: /, pathType: Prefix, backend: { service: { name: hermes, port: { number: 9119 } } } } ] }
```

- WebSocket `/api/ws` (чат панели, терминал `/api/pty`) идёт тем же маршрутом; если H8 покажет обрыв
  по таймауту — правится аннотацией класса `higress` (точное имя сверить в H8, не угадывать).
- Пока идёт приёмка (H5–H6), хост **должен** попасть в `matchRules` плагина `lan-only-ui`
  (домен добавляется в его ConfigMap), иначе SSO-приёмка автоматически станет публичной.

### 4.4 `config.yaml` (ConfigMap `her-config`, сид в PVC)

Шаблон; финальную форму подтверждает H3 (`hermes config get model`) — имена ключей сверены с
`configuring-models`/`configuration`, но проверяются на живой версии.

```yaml
model:
  provider: llm-svc
  default: deepseek-flash
  base_url: https://llm-svc.demo-ai-lab.ru/v1
  api_mode: openai
providers:
  llm-svc:                                  # внешний DeepSeek за шлюзом (ADR-0008)
    base_url: https://llm-svc.demo-ai-lab.ru/v1
    api_key: "${HER_LLM_SVC_KEY}"           # Bearer → consumer llm-svc-her
    request_timeout_seconds: 300
  gpustack:                                 # локальная 27B на дискретной карте k8s-04 (RTX 5070 Ti, сверка 2026-11-09)
    base_url: https://api.demo-ai-lab.ru/v1
    api_key: "${HER_GPUSTACK_KEY}"
    request_timeout_seconds: 900            # decode ~81 tok/s (4K) / ~42 (128K), один слот: длинные ходы не режем
model.aliases:
  local27b:
    model: Qwen3.8-27B-UD
    provider: gpustack
    base_url: https://api.demo-ai-lab.ru/v1
    key_env: HER_GPUSTACK_KEY
auxiliary:                                  # сжатие/заголовки — на быструю внешнюю
  compression:       { provider: llm-svc, model: deepseek-flash }
  title_generation:  { provider: llm-svc, model: deepseek-flash }
dashboard:
  public_url: https://hm.demo-ai-lab.ru
  oauth:
    provider: self-hosted
    self_hosted:
      issuer: https://auth.demo-ai-lab.ru/realms/dev
      client_id: hm                         # публичный PKCE-клиент, секрета нет
      scopes: "openid profile email"
  trusted_proxies: ["10.0.0.0/8"]            # Envoy Higress ходит из pod-сети Cilium
mcp_servers:
  docling:
    url: https://doc.demo-ai-lab.ru/mcp
    tools: { include: ["*"] }                # сузить в H4 по факту tools/list (имена не выдумывать)
  yandex-search:
    url: https://ysrch.demo-ai-lab.ru/mcp
  kuvasz:
    url: https://mon.demo-ai-lab.ru/mcp
    headers: { "X-API-Key": "${KUVASZ_MCP_TOKEN}" }   # MCP-ключ Kuvasz из Secret (имя переменной — как в her-secrets)
    enabled: false                           # включается после деплоя Kuvasz (ADR-0009)
  github:                                    # self-host в кластере, ClusterIP (§7.1, решение 2026-11-14)
    url: http://github-mcp.mcp-github.svc:8101/mcp
    headers: { "Authorization": "Bearer ${HER_GITHUB_PAT}" }   # PAT из her-secrets, на каждый запрос
    tools: { include: ["*"] }                # сузить в H10 по факту tools/list (read-only-набор — 23 инструмента)
```

- `trusted_proxies` — важно: по этому списку панель решает, доверять ли `X-Forwarded-Proto`
  (флаг `Secure` на cookie). Без него вход за TLS-терминацией отдаёт cookie без `Secure`.
- Фильтры MCP — предмет §7; конкретные имена инструментов снимаются `tools/list` в H4,
  в спеку вписываются после замера (не выдумывать).

## 5. Домен: SSO в Keycloak

| Параметр | Значение | Комментарий |
|---|---|---|
| Client ID | `hm` | короткое имя = имя хоста (правило `architecture/endpoints.md`) |
| Тип | **public**, `client authentication` OFF | §0: плагин панели не умеет confidential |
| Flow | Standard flow ON, Direct access OFF, Service accounts OFF | браузерный вход |
| PKCE | `pkce.code.challenge.method = S256` | обязателен для public-клиента |
| Valid redirect URI | `https://hm.demo-ai-lab.ru/auth/callback` | `<public_url>/auth/callback` — из доки панели |
| Web origins | `https://hm.demo-ai-lab.ru` | CORS панели |
| Роль-гейт | realm-роль `her-user`; copy browser-flow + `Condition - user role` (иначе deny) | Hermes ролей не проверяет — единственный барьер здесь |
| Users | `user-test` (роль `her-user`), `admin-test` (по решению) | остальным вход закрыт flow'ом |

Проверка (до браузера, из пода или с консоли):

```bash
curl -s https://auth.demo-ai-lab.ru/realms/dev/.well-known/openid-configuration | jq '{issuer,authorization_endpoint,token_endpoint,jwks_uri}'
# issuer должен быть ровно https://auth.demo-ai-lab.ru/realms/dev (без завершающего слэша — тоже ок)
```

## 6. Модели и маршрутизация

| Роль | Модель | Через что | Ограничения, которые надо знать на сцене |
|---|---|---|---|
| Основная | `deepseek-flash` (128K) | `llm-svc.` → `ai-proxy` → `api.deepseek.com`; DLP `ai-data-masking` + страж `ai-qwen-guard` (fail-closed), квота по `x-consumer = llm-svc-her` | при снятом стражее маршрут отдаёт **`503`** (кейс 01); тело запроса до 1 МиБ (`llm-proxy-spec` §2.1); DLP маскирует ПДн и восстанавливает их в ответе — на код/логи это не влияет, но тексты с телефонами/адресами приходят «звёздочками» в трейсе |
| Локальная | `Qwen3.8-27B-UD` (ctx 128 000, BeeLlama custom backend) | `api.` → GPUStack, ключ `her-27b` | **один слот (`-np 1`)**, decode ~81 tok/s на 4K и ~42 на 128K, prefill ~850–1400 tok/s (замер 2026-11-09, RTX 5070 Ti, `gpustack-custom-backend-spec` §5–§6); карта эксклюзивна — любой сосед = OOM; при 128K контексте ход долгий — на сцене короткий вопрос, не needle |
| Сжатие/заголовки | `deepseek-flash` | `llm-svc.` | дешёвая и быстрая; на 27B aux не вешаем — займёт единственный слот |
| Fallback | **не настраиваем автоматический** | — | 27B и `llm-svc.` несовместимы по времени жизни (кейс 01 снимает стража, 27B занимает карту). Автопереключение дало бы «случайно другую модель» на глазах у зала; переключение — вручную `/model local27b` |

Демо-сценарий моделей: один и тот же вопрос дважды — `deepseek-flash` (быстро, 128K) и `/model local27b`
(локально, медленнее, «данные не уходят наружу»). Возврат на основную — `/model deepseek-flash`.

## 7. MCP: что подключаем и что осознанно нет

| Сервер | Адрес | Инструменты | Авторизация | Решение |
|---|---|---|---|---|
| Docling | `https://doc.demo-ai-lab.ru/mcp` | conversion (PDF/URL → документ), generation/manipulation | нет (`doc-spec` §1) | **включаем**; на сцене — разбор PDF в markdown |
| Yandex Search | `https://ysrch.demo-ai-lab.ru/mcp` | `web_search`, `gen_search`, `image_search`, `web_search_async`, `get_operation` | нет; ключ Search API внутри сервиса | **включаем** — это единственный «интернет» агента (прямого egress нет) |
| Kuvasz | `https://mon.demo-ai-lab.ru/mcp` | HTTP/TCP/ICMP/DNS-мониторы, инциденты, статус-страницы | `X-API-Key` (MCP-ключ) | **заготовка**, `enabled: false` до деплоя Kuvasz (ADR-0009); хост — только LAN |
| MCP Registry | `https://mcp.demo-ai-lab.ru` | — | — | **не MCP-сервер**: это каталог (`/v0`). Агенту полезен как источник ссылок, не как инструмент |
| GitHub | `http://github-mcp.mcp-github.svc:8101/mcp` — **self-host** в ns `mcp-github`, ClusterIP, без Ingress (§7.1) | 23 read-only инструмента (замер `tools/list` 14.11): `list_issues`/`issue_read`, `list_pull_requests`/`pull_request_read`, `search_code`/`search_repositories`/`search_issues`, `get_file_contents`, `list_commits`/`list_branches`, `get_latest_release`… | `Authorization: Bearer ${HER_GITHUB_PAT}` на **каждый** запрос (PAT в `her-secrets`, детали — §7.1) | **включаем** (решение владельца 2026-11-14): демо — чтение кода/issues/PR своих репозиториев. Egress `api.github.com` замерен 14.11 → 200; предусловие — строка в allowlist ISP (вне стенда) |
| Atlassian MCP, HuggingFace | внешние облака | — | токены | **нет**: корпоративные `bitbucket.gnivc.ru`/Jira вне зоны стенда, HF-инструменты агенту не нужны (веса качаются на узлы, не агентом) |

Правила подключения (из доки MCP-клиента): `mcp_servers.<имя>.url` — HTTP-транспорт, `headers` —
доп. заголовки, `${VAR}` — из окружения профиля; после правки конфига — `/reload-mcp` (или рестарт пода).
Управление в панели тоже работает (страница MCP), но **источник правды — `config.yaml` в git**.
Фильтры `tools.exclude`/`tools.include` обязательны: Docling отдаёт десяток инструментов, из них на сцене
нужны 2–3; лишние съедают контекст и провоцируют агента «попробовать всё».

### 7.1 GitHub MCP — self-host в кластере, токен per-request (решение 2026-11-14)

**Что ставим.** Официальный `ghcr.io/github/github-mcp-server` **v1.12.0** (amd64-манифест
`sha256:7cc0b474f2bff1e7e5bc794999e19b42d476ee6dba0cf1a305f4ced2de158348`) в отдельном ns
`mcp-github`: Deployment (1 реплика) + Service `ClusterIP`, эндпоинт `/mcp`, порт 8101.
**Ни Ingress, ни сертификата, ни SSO** — сервер доступен только из
кластера (`github-mcp.mcp-github.svc:8101`), как `fc` в `firecrawl-spec`. Публичного имени у него нет.
**Ревизия ADR-0012 (2026-11-17):** запись в каталоге `mcp.` обязательна, набор инструментов общий для обоих
агентов — нужен внутренний адрес; «не публикуем в каталог» снято.

**Почему self-host, а не hosted** (`https://api.githubcopilot.com/mcp/`): hosted требует OAuth-цикла
внутри агента, не даёт верхней границы прав на уровне пода и не проверяется в репозитории; self-host
даёт `--read-only`/`--toolsets` флагами, пин по digest и тот же образ, что уже проверен в локальном
стенде поддержки.

**HTTP-режим — stateless всегда** (замер 14.11 на v1.12.0; в исходниках `pkg/http/handler.go` —
`Stateless: true`): `initialize` не выдаёт `Mcp-Session-Id`, `tools/list` и `tools/call` отвечают без
рукопожатия, `GET`/`DELETE` → 405. Следствия для стенда: sticky-сессий нет, рестарт пода `github-mcp`
не ломает агентскую сессию, а конфигурация может задаваться **в запросе** заголовками
`X-MCP-Toolsets`/`X-MCP-Readonly`/`X-MCP-Lockdown`, а не глобально — один инстанс обслуживает разных
агентов с разными правами. Обратная сторона: server→client запросы (sampling/elicitation) и уведомления
вне запроса недоступны — для чтения кода это не нужно.

**Авторизация.** Токен **не хранится в поде `github-mcp`**: HTTP-режим читает только заголовок
`Authorization`, env `GITHUB_PERSONAL_ACCESS_TOKEN` игнорируется (замер: без заголовка → `401` даже
при заданной переменной). Поэтому PAT лежит в `her-secrets` → env пода `hermes` → заголовок в каждом
запросе (§4.2). Плюсы: под инструмента без секретов, разные токены разным агентам без пересоздания
сервера. PAT — fine-grained, read-only, только нужные репозитории (§3).

**Флаги пода:** `--read-only` (write-инструменты не регистрируются — верхняя граница прав),
`--toolsets repos,issues,pull_requests,users` (после read-only остаётся 23 инструмента, замер 14.11);
дефолтный `--repo-access-cache-ttl 5m` не трогаем (кэш в памяти, не сессионное состояние).
`--lockdown-mode` **не включаем**: он вырезает тела issues/PR/комментариев — ровно то, что читаем на
демо; вопрос пересмотра — если понадобится защита от инъекций в чужом контенте (R-H18).

**Egress.** Под `github-mcp` ходит к `api.github.com:443`. Замер 14.11 **из пода `hermes`** (k8s-03):
`api.github.com` → **200** за 0.28 s, `github.com` → 200 — этим доказана доступность адреса со стенда
(другого пода под рукой не было; по схеме вызывающий — `github-mcp`, egress-путь у подов общий).
Белый список реализуется **выше стенда** (ISP/внешние роутеры, `llm-proxy-spec` §2), из кластера он не
виден — строка `api.github.com` фиксируется за владельцем, а регресс ловится только в H10.

**Манифесты** — `gitops/apps/mcp-github/` (каталог **не** коммитить до подтверждения строки в allowlist:
ApplicationSet `apps` подхватит его сразу и раскатает).

```yaml
# 00-namespace.yaml
apiVersion: v1
kind: Namespace
metadata: { name: mcp-github }
---
# 20-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: github-mcp
  namespace: mcp-github
  annotations: { argocd.argoproj.io/sync-wave: "1" }
spec:
  replicas: 1
  selector: { matchLabels: { app.kubernetes.io/name: github-mcp } }
  template:
    metadata:
      labels: { app.kubernetes.io/name: github-mcp, app.kubernetes.io/part-of: demo-ai-lab }
    spec:
      priorityClassName: demo-stand-critical
      containers:
        - name: github-mcp
          image: ghcr.io/github/github-mcp-server:v1.12.0@sha256:7cc0b474f2bff1e7e5bc794999e19b42d476ee6dba0cf1a305f4ced2de158348
          # http-режим; секретов в поде нет — токен приходит заголовком от клиента (§7.1).
          # ВНИМАНИЕ: это `args`, а НЕ `command`: ENTRYPOINT образа — `/server/github-mcp-server`,
          # `command` заменил бы его и под упал бы `exec: "http": executable file not found`
          # (та же грабля, что у Hermes, §13 п.1). В `docker compose` этому соответствует `command`.
          args: ["http", "--listen-host", "0.0.0.0", "--port", "8101",
                 "--read-only", "--toolsets", "repos,issues,pull_requests,users"]
          ports: [ { containerPort: 8101, name: http } ]
          readinessProbe: { tcpSocket: { port: http }, initialDelaySeconds: 5, periodSeconds: 10 }
          livenessProbe:  { tcpSocket: { port: http }, initialDelaySeconds: 20, periodSeconds: 30 }
          resources: { requests: { cpu: 50m, memory: 64Mi }, limits: { cpu: 500m, memory: 256Mi } }
      affinity:                       # лёгкий stateless — на пару ingress, k8s-04/05 не занимаем
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference: { matchExpressions: [ { key: demo-ai-lab/role, operator: In, values: [ingress] } ] }
---
# 30-service.yaml
apiVersion: v1
kind: Service
metadata: { name: github-mcp, namespace: mcp-github }
spec:
  selector: { app.kubernetes.io/name: github-mcp }
  ports: [ { name: http, port: 8101, targetPort: http } ]
```

**Подключение в агенте.** При раскатке сид-скрипт `gitops/apps/her/15-configmap.yaml` дополняется
блоком `mcp_servers.github.*` (§4.2), но **сид не перезаписывает существующий `config.yaml`** — на живом
поде запись добавляется вручную и переживает рестарт (файл на PVC):

```bash
kubectl -n her exec deploy/hermes -- hermes config set mcp_servers.github.url http://github-mcp.mcp-github.svc:8101/mcp
kubectl -n her exec deploy/hermes -- hermes config set mcp_servers.github.headers.Authorization 'Bearer ${HER_GITHUB_PAT}'
# путь с заголовком может ответить «unknown key» — значение всё равно пишется (журнал §13 п.6)
kubectl -n her exec deploy/hermes -- hermes mcp list        # github: connected
```

В Deployment `hermes` добавляется env `HER_GITHUB_PAT` из `her-secrets` (без него заголовок пустой и
сервер отвечает `401`), затем `kubectl -n her rollout restart deploy/hermes`.

**Не делаем:** write-инструменты (issues/PR) — Q-H7. Публикация в каталог `mcp.` — по ADR-0012
(ревизия v1.6, нужен внутренний адрес); «GitHub-инструменты только у Hermes» снято — набор общий.

## 8. Обвязка агента: что реально нужно (и чего не нужно)

Ответ на «что ещё понадобится для работы агента». Таблица — по слоям; «нужно» = без этого агент
не работает или работает плохо, «нет» = сознательно не тащим.

| Слой | Нужно? | Чем закрыто / почему нет |
|---|---|---|
| Рантайм и процессы | **да** | образ с s6, `gateway run` + панель; рестарт сервисов без пересоздания пода |
| Хранилище состояния | **да** | PVC 10 Gi `/opt/data` (SQLite WAL, сессии, память, скиллы, cron, `auth.json`) |
| Shell агента | **да** | `terminal.backend: local` — команды в поде, без Docker-сокета и хостовых монтирований |
| Браузер | **да, но встроенный** | Chromium уже в образе; `browser_exec` работает «из коробки» + `/dev/shm` 512 МиБ |
| **Playwright** | **нет** | `browser_exec` его не использует (свой Chromium через CDP). `npx playwright install` в рантайме невозможен: `/opt/hermes` неизменяем, lazy-install запрещён. Нужен именно CLI-Playwright/скрипты — только **свой образ** `FROM <пин> + npx playwright install --with-deps chromium`, и это отдельная фаза (в v1 не делаем: даёт дублирующий браузер и +1–2 ГБ образа) |
| Web search/extract | **нет прямого** | интернета у пода нет; `web_search`/`web_extract` без бэкенда бесполезны → поиск идёт через MCP `yandex-search`. Выключение встроенных инструментов — H3 (`hermes tools`), точный ключ фиксируем по выводу CLI |
| Git/репозитории | **нет клона в v1** | код читается **через GitHub MCP** (`get_file_contents`/`search_code`, read-only, §7.1), а не git-клоном: клонировать репозиторий в под не нужно и незачем (локальный репозиторий стенда в под не монтируем — там приватные `*.local.md`). Демо-данные — файлы в `/opt/data/work`, скиллы — из образа + при необходимости seed-ConfigMap |
| Скиллы/память | **да** | `/opt/data/skills` и `memories/` на PVC; стартовый набор — 3–5 скиллов, положенных сидом (не весь каталог: он раздувает системный промпт) |
| Cron/kanban/субагенты | **опционально** | работают внутри пода; при рестарте in-flight задача теряется, расписание в PVC остаётся. На демо не показываем |
| Сеть/egress | **да, узко** | исходящие только к `auth.` (discovery/JWKS/token), `llm-svc.`, `api.`, `doc.`, `ysrch.`, `mcp.`, `github-mcp.mcp-github.svc:8101` (+ DNS). Прямого выхода в интернет у пода быть не должно: всё внешнее — через шлюз с DLP/стражем (ADR-0006/0008). Единственный внешний адрес в схеме — `api.github.com`, и по схеме в него ходит **не под `hermes`**, а под `github-mcp` (§7.1), получая токен заголовком; замер 14.11 сделан из пода `hermes` (другого не было) — он доказывает доступность адреса со стенда, а не выдачу прав агенту |
| SSO | **да** | публичный PKCE-клиент `hm` + роль-гейт в Keycloak (§5) |
| Секреты | **да** | Secret `her-secrets` → env; в git только имена |
| Наблюдаемость | **да** | пробы `/api/status`, лог пода, HTTP-монитор Kuvasz; отдельный Prometheus-скрейп не нужен |
| Бэкап | **да** | снапшот тома Longhorn перед апгрейдом + `hermes backup` в `/opt/data/backup`; восстановление — §9 |
| NTP/TLS/DNS | **да** | уже есть (F0/F5, split-DNS); проверяются в H5 |
| GPU | **нет своего** | агент не держит GPU: модели — общие сервисы (`llm-svc.`, `api.`) |
| Docker-in-Docker | **нет** | агент не должен управлять контейнерами; сокет не монтируется |

### 8.1 Браузер отдельным подом (CDP): можно, но отложено

> **Решение владельца 2026-11-06:** остаёмся на Chromium официального образа в контейнере агента, CDP-вынос
> не делаем. Раздел сохранён как условие пересмотра: если замер H1/H8 покажет OOM или просадку панели из-за
> браузера — эскалация по шагам ниже; отдельный под — только вместе с `dsh` (шаг 4).

Вынести браузер штатно можно: у Hermes есть **постоянный** CDP-эндпоинт — `browser.cdp_url` в `config.yaml`
или `BROWSER_CDP_URL` в окружении. Ничего интерактивного для этого не нужно (`/browser connect` — команда
CLI-сессии, из гейтвея не исполняется). Когда эндпоинт задан, `browser_exec`, `browser_cdp`, `browser_dialog`
и `browser_vault` работают с присоединённым браузером, а свой Chromium Hermes не поднимает.

| Что | один контейнер (v1) | sidecar в том же поде | отдельный под/Deployment |
|---|---|---|---|
| Профиль браузера | свежий **на сессию**, выбрасывается | один на под | один на всех потребителей |
| Cookie/SSO между сессиями | не текут | текут внутри пода | текут между всеми агентами |
| CDP-поверхность | нет (в контейнере) | `127.0.0.1` внутри пода | `ClusterIP:9222`, **без аутентификации** |
| Память | в лимите агента (4Gi) | свой лимит | свой лимит |
| Изоляция сбоя | падение Chromium = рестарт пода | рестарт контейнера, агент жив | независимо |
| Guard приватных адресов | **не включается** (браузер = терминал) | включается | включается |

**Почему в v1 один контейнер:**

1. Профиль **на сессию** — на стенде это свойство, а не мелочь: в браузере может оказаться живая SSO-сессия
   в `owu.`/`argo.`, и делить её между сессиями и субагентами не нужно (R-H14).
2. CDP-эндпоинт включает guard приватных адресов: браузер начинает отбивать LAN-адреса, а весь смысл —
   ходить по хостам стенда. Обходить это `security.allow_private_urls: true` = осознанно снять защиту
   ради того, что терминал в поде и так может — ухудшение без выигрыша.
3. CDP не аутентифицирован: любой под, дотянувшийся до `:9222`, получает навигацию и `Runtime.evaluate`,
   то есть управление браузером и всё, куда он залогинен (R-H15).

**Порядок эскалации** (если H1/H8 покажут, что Chromium душит под — OOM или просадка панели):

1. **sidecar** — предпочтительный вариант: второй контейнер того же образа, CDP только на loopback,
   сетевой поверхности не добавляет:

```yaml
      containers:
        - name: chromium
          image: <тот же пин>
          command: ["sh","-c","exec \"$(cat /etc/hermes/chromium-executable-path)\" --headless=new --no-sandbox \
            --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
            --user-data-dir=/profile --no-first-run --no-default-browser-check about:blank"]
          readinessProbe: { tcpSocket: { port: 9222 }, initialDelaySeconds: 5, periodSeconds: 10 }
          resources: { requests: { cpu: 200m, memory: 512Mi }, limits: { cpu: "1", memory: 2Gi } }
          volumeMounts:
            - { name: shm, mountPath: /dev/shm }
            - { name: profile, mountPath: /profile }      # emptyDir: профиль живёт с подом
        # у контейнера hermes: env BROWSER_CDP_URL=http://127.0.0.1:9222; /dev/shm ему больше не нужен
```

   `--no-sandbox` здесь осознан: user-namespace в поде недоступен, иначе Chromium не стартует под non-root;
   компенсация — браузер в своём контейнере с лимитом, без хостовых монтирований и без egress наружу.

2. **отдельный Deployment** — только если браузером пользуются **несколько** агентов (`dsh` шага 4) или
   браузер нужен на другой ноде. Тогда обязательны: `ClusterIP` **без** Ingress, `NetworkPolicy`
   «ingress только из ns `her`», профиль на явно выбранном томе, `security.allow_private_urls: true`
   прописанный в спеку как осознанное ослабление (а не всплывший побочный эффект) и строка в §11.
   Для одного агента это лишняя поверхность и лишний объект в обслуживании.

**Что меняется в приёмке при переходе на CDP:** проба пода — `tcpSocket:9222` у контейнера-браузера;
H8 проверяет не только чат, но и `browser_exec` (навигация + скриншот), `browser_dialog` и `/api/pty`;
в H9 добавляется проверка, что `9222` недоступен из другого ns (`kubectl -n demo-test run … -- wget -T2`).

## 9. Фазы H1–H10

Каждая фаза — команды и ожидаемый результат. Кластер: `export KUBECONFIG=~/.kube/demo-ai-lab.conf`.

### H1 — образ, предтяжка, «скелет» пода

```bash
kubectl -n default run her-probe --image=nousresearch/hermes-agent:v0.23.0@sha256:adb7890916de63245523492be8f68f9d2095fecbec4e2a6dab7960381f0fc002 \
  --restart=Never --image-pull-policy=IfNotPresent --command -- hermes --version
kubectl -n default get pod her-probe -o jsonpath='{.spec.nodeName}{" "}{.status.containerStatuses[0].imageID}{"\n"}'
kubectl -n default logs her-probe            # ожидаем строку версии (0.23.0)
kubectl -n default exec her-probe -- id      # uid/gid → fsGroup в §4.2
kubectl -n default delete pod her-probe
```

**Приёмка:** под `Succeeded`, `imageID` содержит `sha256:0dd31821…`, лог с версией, `id` записан в спеку.
**Грабля:** `--overrides` с `nodeSelector` может быть проигнорирован — читать `.spec.nodeName`.

### H2 — Secret'ы и сид конфигурации

```bash
# llm: третий consumer llm-svc-her в wasm-key-auth + значение в Secret llm-apikey (правка gitops/apps/llm)
./scripts/her_secrets.sh                      # только Secret в ns her (сам ns создаёт ApplicationSet apps)
kubectl -n her get secret her-secrets -o go-template='{{range $k,$v := .data}}{{$k}}{{"\n"}}{{end}}'
kubectl apply -f gitops/apps/her/            # или push → ApplicationSet apps
kubectl -n her rollout status deploy/hermes
```

**Приёмка:** под `1/1 Running`, в логах s6 — gateway и dashboard подняты, `/api/status` отвечает
(из пода: `kubectl -n her exec deploy/hermes -- wget -qO- http://127.0.0.1:9119/api/status`).
**Провал fail-closed** («Refusing to bind dashboard … no auth providers») означает, что OIDC-переменные
не доехали — это ожидаемо до H6, поэтому на H2 в `config.yaml` панель ещё можно держать на loopback,
а на `0.0.0.0` переводить в H5 (см. примечание ниже).

> **Порядок:** чтобы H2 не блокировался SSO, H2 идёт с `HERMES_DASHBOARD_HOST=127.0.0.1`; `0.0.0.0` +
> `PUBLIC_URL` включаются в H5 после заведения клиента. Обратный порядок тоже допустим — тогда H2 и H5
> сливаются (панель не стартует без провайдера).

### H3 — модели

```bash
kubectl -n her exec deploy/hermes -- hermes chat -q "ответь одним словом: работает"
kubectl -n her exec deploy/hermes -- hermes doctor          # конфиг и зависимости; какие ключи model/provider резолвились
kubectl -n her exec deploy/hermes -- hermes config          # показать действующий config.yaml (подкоманда — по `hermes config --help`)
kubectl -n her exec deploy/hermes -- printenv HER_LLM_SVC_KEY | wc -c   # ключ доехал в окружение пода (длина, не значение)
# локальная 27B (после поднятия Qwen3.8-27B-UD по кейсу 01): тот же GET к https://api.demo-ai-lab.ru/v1 с ключом HER_GPUSTACK_KEY
```

**Приёмка:** непустой ответ на `chat -q` (внешняя), `deepseek-flash` в списке моделей llm-svc,
`Qwen3.8-27B-UD` — в списке GPUStack; `/model local27b` в сессии даёт ответ локальной.

### H4 — MCP

```bash
kubectl -n her exec deploy/hermes -- hermes mcp --help   # подкоманда списка серверов (в доке показаны add/configure/login)
kubectl -n her exec deploy/hermes -- hermes mcp list
kubectl -n her exec deploy/hermes -- hermes chat -q "через docling разбери /opt/data/work/sample.pdf и покажи первые 5 строк"
kubectl -n her exec deploy/hermes -- hermes chat -q "через yandex-search найди 'демо стенд ИИ' и верни 3 ссылки"
```

**Приёмка:** оба сервера `connected`; по каждому — успешный вызов; в выводе видно имя инструмента
(`mcp__docling__*`, `mcp__yandex-search__*`). Имена инструментов и политика `tools.include/exclude`
фиксируются в §7 по факту `tools/list`.

### H5 — Ingress, TLS, LAN-гейт

```bash
kubectl -n her get certificate her-demo-tls        # READY=True (LE)
curl -s -o /dev/null -w '%{http_code}\n' https://hm.demo-ai-lab.ru/api/status   # 200
curl -s https://hm.demo-ai-lab.ru/api/status | jq '{auth_required, auth_providers}'
# ожидаем: auth_required=true, в списке провайдеров self-hosted
```

**Приёмка:** `auth_required=true` и `self-hosted` в `auth_providers`; незалогиненный `/` → редирект на
вход IdP. **До H7** хост обязан быть в `lan-only-ui` — проверить `curl` через туннель → `403`.

### H6 — SSO-цикл

1. Keycloak: клиент `hm` (public, PKCE, redirect, web origins) + роль `her-user` + copy flow с
   `Condition - user role`; всё — в `scripts/keycloak_seed.py`, не руками в UI.
2. Браузер: `https://hm.demo-ai-lab.ru/` → вход `user-test` → панель.
3. Проверка отказа: пользователь **без** роли `her-user` → Keycloak отбивает на своей странице.

```bash
curl -s -c /tmp/her.jar -o /dev/null -w '%{http_code} %{redirect_url}\n' https://hm.demo-ai-lab.ru/
# 302 на /realms/dev/protocol/openid-connect/auth?…client_id=her…code_challenge_method=S256
```

**Приёмка:** вход и выход (logout гасит сессию и в Keycloak — RFC 7009), в панели видно имя пользователя;
пользователь без роли не проходит. Cookie `Secure` выставлен (проверить в DevTools).

### H7 — внешний край

Снимаем хост из `lan-only-ui` **только** если H6 зелёная и роль-гейт работает.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://hm.demo-ai-lab.ru/api/status   # снаружи 200
curl -s -o /dev/null -w '%{http_code}\n' https://hm.demo-ai-lab.ru/              # 302 на IdP
```

**Приёмка:** снаружи тот же SSO-цикл; `403` от LAN-гейта больше не мешает. Обратный ход (закрыть снова) —
одна строка в ConfigMap плагина, фиксируется в README каталога.

### H8 — панель и Desktop в работе

- Чат в панели: сообщение → ответ стримом → инструмент → ответ (проверить `terminal` и один MCP).
- Hermes Desktop с Mac-консоли: **Remote Gateway** → `https://hm.demo-ai-lab.ru` → Sign in (тот же SSO).
- WebSocket: `/api/ws` не рвётся на 5+ минутах простоя и на длинном ответе; `/api/pty` открывается.

**Приёмка:** живая сессия из браузера и из Desktop, без ручных правок в поде; обрывы WS — с записанным
кодом закрытия (4403 = Host/peer mismatch, 4401 = билет не аутентифицирован).

### H9 — мониторинг, бэкап, регистрация

```bash
# Kuvasz: HTTP-монитор https://hm.demo-ai-lab.ru/api/status (expect 200) — через MCP или UI (ADR-0009)
kubectl -n her exec deploy/hermes -- hermes backup    # архив в /opt/data/backup
kubectl -n her get pvc hermes-data                    # Bound, 10Gi
```

**Приёмка:** монитор в Kuvasz зелёный, бэкап создан и читается (`hermes import --dry-run` не обязателен,
но файл открывается как tar), строка в `architecture/ARCHITECTURE.md` §7 и в `architecture/endpoints.md` (статус
`her` → «установлен», клиент — публичный), `scripts/k8s_health.py` знает новый хост (слой «маршруты»).

### H10 — GitHub MCP (self-host, внешний вызов)

Предусловия: строка `api.github.com` в egress-allowlist подтверждена владельцем (вне стенда); в
`her.local.md` есть `github_pat:`, в `her-secrets` — `HER_GITHUB_PAT` (fine-grained, read-only, только
`msklv/demo-ai-lab`); каталог `gitops/apps/mcp-github/` (§7.1) закоммичен и Application Synced/Healthy.

```bash
kubectl -n mcp-github get deploy,svc,pod             # 1/1 Running, Service ClusterIP :8101
# без токена сервер обязан отказывать: 401 — проверка, что auth не «провалилась в аноним»
kubectl -n her exec deploy/hermes -- sh -c 'curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" \
  http://github-mcp.mcp-github.svc:8101/mcp'
# с токеном из env пода — SSE с tools/list (токен подставляет shell в поде, не локальный)
kubectl -n her exec deploy/hermes -- sh -c 'curl -s -X POST -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "Authorization: Bearer $HER_GITHUB_PAT" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" \
  http://github-mcp.mcp-github.svc:8101/mcp | head -c 300'
kubectl -n her exec deploy/hermes -- hermes mcp list                     # github: connected
kubectl -n her exec deploy/hermes -- hermes chat -q "через github покажи 3 последних issue в msklv/demo-ai-lab"
```

**Приёмка:** `github` — `connected`; read-инструмент возвращает данные репозитория; в `tools/list` **нет**
write-инструментов (`create_*`/`update_*`/`delete_*` — граница держится флагом `--read-only`); значение
PAT не встречается в логах подов `hermes`/`github-mcp`; образ предтянут на целевую ноду (слой «Образы»
`health-check-spec` — на сцене pull с GHCR = минуты тишины); после приёмки — строка статуса в
`architecture/ARCHITECTURE.md` §7.

## 10. Операции

| Задача | Как |
|---|---|
| Логи | `kubectl -n her logs deploy/hermes` (s6 сводит gateway и панель); per-profile лог — `/opt/data/logs/gateways/<profile>/current` |
| Рестарт сервиса | рестарт пода (s6 внутри контейнера перезапускает упавший сервис сам) |
| Апгрейд | поднять тег+digest в `gitops/apps/her/20-deployment.yaml`, push; перед этим — снапшот PVC. `hermes update` в образе **не работает** (маркер image-managed, exit 2) |
| Бэкап | снапшот тома Longhorn (`lng.` UI или `VolumeSnapshot`) + `hermes backup` в `/opt/data/backup`; архив вне репо |
| Восстановление | новый PVC из снапшота → под; при переезде на другой кластер — `hermes import` |
| Ротация ключа llm-svc | новый ключ в `llm-apikey` для consumer `llm-svc-her` → `kubectl -n her rollout restart` (старый удалить после проверки) |
| Ротация ключа GPUStack | UI GPUStack → API Keys → новый `her-27b` → Secret → рестарт; старый revoke |
| Ротация GitHub PAT | новый fine-grained PAT (read-only, те же репозитории) → `github_pat:` в `her.local.md` → `./scripts/her_secrets.sh` → `kubectl -n her rollout restart deploy/hermes`; старый — revoke в GitHub. Под `github-mcp` не трогаем: он токена не хранит (§7.1) |
| Обслуживание GitHub MCP | логи `kubectl -n mcp-github logs deploy/github-mcp`; рестарт пода безопасен — сервер stateless, агентская сессия не рвётся (§7.1). Обновление — тег+digest в `gitops/apps/mcp-github/20-deployment.yaml` |
| Проверка «панель не открыта» | `curl` через туннель без входа: до H7 — `403` (LAN-гейт), после — `302` на IdP, **никогда** `200` на `/` без cookie |

## 11. Риски

| # | Риск | Что делаем |
|---|---|---|
| R-H1 | Панель = права владельца машины; любой, кого пустил IdP, получает shell в поде | роль-гейт `her-user` в Keycloak (§5), сначала LAN-онли (H5), край — только после H6/H7; открытых учёток в realm `dev` не заводим |
| R-H2 | Утечка данных наружу через модель | весь трафик к LLM — только `llm-svc.` с DLP и стражем fail-closed (ADR-0006/0008); прямого egress у пода нет (§8) |
| R-H3 | Агент исполняет деструктивные команды в поде | терминал в поде, без Docker-сокета и без kubeconfig; PVC — единственное, что он может испортить; снапшот перед демо |
| R-H4 | Keycloak недоступен → панель недоступна (нет второго провайдера) | осознанно (break-glass = CLI в поде); Keycloak ×2 + `jdbc-ping`, drill K уже снят |
| R-H5 | `llm-svc.` в кейсе 01 отдаёт `503` (страж снят) | на сцене: либо кейс 01, либо внешняя модель; переключение — `/model`, в кейсе 01 — только `local27b` |
| R-H6 | 27B: один слот, ~42–81 tok/s (128K / 4K, замер 2026-11-09) — «долгий» агентский цикл | короткие вопросы, `request_timeout_seconds: 900`, aux-задачи не на 27B |
| R-H7 | Chromium в контейнере падает/тормозит | `/dev/shm` 512 МиБ (память), лимит 4Gi; при OOM — `browser.headed: false` (дефолт) и `--disable-gpu` |
| R-H8 | SQLite WAL на сетевом/чужом ФС | только блочный PVC Longhorn RWO, одна реплика; RWX/NFS не использовать |
| R-H9 | `Host` mismatch / DNS-rebinding → 403/4403 | `dashboard.public_url` выставлен, `trusted_proxies` = pod-сеть Cilium (`10.0.0.0/8`) |
| R-H10 | WebSocket рвётся на прокси | проверка в H8; при обрыве — таймауты маршрута Higress, не «перезапустить под» |
| R-H11 | Образ 1,12 ГБ на канал 4–6 МБ/с | предтяжка H1; при апгрейде — сначала pull на нужную ноду |
| R-H12 | Агент без интернета «не умеет искать» и это видно на демо | поиск — `yandex-search` MCP (живой, проверен), в сценарии это заявлено как «инструменты стенда, не интернет» |
| R-H14 | Браузер общий (sidecar/отдельный под) → cookie и SSO-сессия текут между сессиями и субагентами | в v1 профиль на сессию; при переходе на CDP — `--user-data-dir` на `emptyDir` (профиль живёт с подом) и явная запись в README, что браузер общий и в нём может быть чужой вход |
| R-H15 | CDP без аутентификации: `:9222` = навигация + `Runtime.evaluate` в чужом браузере | v1 — порт не слушается; sidecar — только `127.0.0.1`; отдельный под — `ClusterIP` + `NetworkPolicy` (ingress только из ns `her`), наружу никогда |
| R-H16 | ~~На k8s-02/03 контейнеры получают урезанный набор capabilities (`CapEff 0x2000000420`), любой s6/gosu-образ падает на drop привилегий~~ **закрыт 2026-11-14** | Причина — `base_runtime_spec` (`/etc/containerd/base-ulimits.json`) с тремя caps (`AUDIT_WRITE/KILL/NET_BIND_SERVICE`) и `noNewPrivileges`, включённый 04.11 ради fd и снятый 08.11 (`health-runbook` §10d). Проверка 14.11: `base_runtime_spec=''` на всех пяти нодах; в подах 02/03 `CapBnd/CapEff=0xa80425fb`, `chown` и `setgroups` работают; образ Hermes на 02 поднялся, s6-drop до `hermes` прошёл. Обходной `nodeAffinity` снят, размещение — по §1; `scripts/k8s_health.py` теперь WARN'ит при непустом `base_runtime_spec` |
| R-H13 | Роль-гейт `Condition - user role` не проверен на этом Keycloak | H6 включает проверку отказа явным пользователем без роли; если flow не сработает — fallback: отдельный realm/`her`-only клиент с ограниченным набором пользователей, решение фиксируется в спеке |
| R-H17 | PAT к GitHub лежит в поде агента: любой, кто получил shell (R-H1), уводит токен | fine-grained + read-only + только нужные репозитории (§3); ротация по §10; значение не печатается в доках и не попадает в git (`her.local.md`); в логах подов не появляется — проверка в H10 |
| R-H18 | Prompt injection из содержимого репозитория (issue/PR/код) → агент выполняет чужие инструкции | сервер в `--read-only` (писать не может), терминал без Docker-сокета, внешний LLM — только через `llm-svc.` с DLP/стражем; на демо читаем только свои репозитории; `--lockdown-mode` — резерв, если контент станет чужим (он скрывает тела issues/PR) |
| R-H19 | Egress к `api.github.com` закроется сменой allowlist'а у ISP/внешних роутеров — молча, из кластера это не видно | замер 14.11 в журнале §13 п.13; в H10 — обязательный `curl` из пода; при таймаутах/403 смотреть allowlist и не «перезапускать под» |

## 12. Открытые вопросы

| # | Вопрос | Кто/когда |
|---|---|---|
| Q-H1 | Открывать `her.` наружу на демо или оставить LAN-онли (как `argo`/`hgc`)? | владелец, перед H7 |
| Q-H2 | Нужен ли Demо-гость (отдельный пользователь без права менять конфиг)? Hermes прав не различает — гость = владелец; значит либо не пускаем, либо пускаем доверенного | владелец |
| Q-H3 | Нужны ли агенту **git-инструменты** (клон репозитория в `/opt/data/work`)? Чтение кода уже закрывает GitHub MCP (§7.1: `get_file_contents`/`search_code`); клон нужен только для `git log`/диффов и правки файлов. Замер 14.11: `github.com` со стенда → 200 | владелец, после H10 |
| Q-H4 | Стартовый набор скиллов (3–5) — какие? Кандидаты: `demo-ai-lab-stand`, `homelab-kubernetes-cluster`, `ocr-and-documents`. **Уточнение 2026-11-10:** публичный каталог скиллов — репозиторий `msklv/skills-demo-ai-lab` (ADR-0010, 18 скиллов Apache-2.0, установка копированием каталога), вопрос не закрывает: выбираем из каталога или из профиля агента | владелец + H2 |
| Q-H5 | Нужен ли `dsh` рядом (шаг 4) и делят ли они MCP-набор? | архитектура шага 4 |
| Q-H6 | Нужен ли «тёплый» профиль, то есть `browser.user_data_dir` на PVC (вход в `owu.`/`argo.` сохраняется между сессиями)? По умолчанию профиль на сессию и выброшен — так безопаснее, но на демо каждый раз логин заново | владелец, до H8 |
| Q-H7 | Нужны ли агенту **write**-инструменты GitHub (issues/PR/комментарии)? Сейчас сервер жёстко в `--read-only`; включение = отдельное решение + PAT с правом записи и пересмотр R-H18 | владелец, после H10 |

## 13. Журнал развёртывания (2026-11-06)

Факты замера, а не пересказ §2–§9. Каждый пункт — то, что в плане было неверно или не учтено.

| # | Что | Факт | Как учтено |
|---|---|---|---|
| 1 | ENTRYPOINT образа | `command: ["gateway","run"]` в манифесте **ломает** запуск: `exec: "gateway": executable file not found` | в манифесте `args: ["gateway","run"]`, ENTRYPOINT (`/init`) не переопределять |
| 2 | `securityContext` | `fsGroup: 1000` → s6-applyuidgid `unable to set supplementary group list`; `runAsUser: 10000` → `s6-overlay-suexec: fatal: unable to setgid to root` | контейнер стартует root'ом (дефолт образа), stage2 сам делает chown `/opt/data` и drop до hermes (10000) — `securityContext` не задаём |
| 3 | **Узлы 02/03** | **закрыто 2026-11-14:** причина — `base_runtime_spec` 04–08.11 (3 caps, `noNewPrivileges`, `hostname: runc`); после снятия 08.11 caps снова `0xa80425fb`. Проверено подом Hermes на 02 (s6 stage1→stage2, drop до `hermes`) и busybox на 02/03 (`chown`, `setgroups`) | `nodeAffinity` возвращён к §1 (`required` 01/02/03, `preferred` ingress-пара); остаточные `/etc/containerd/base-ulimits.json*` не используются, удалить при удобном окне. Под переедет на 02/03 при следующем rollout (после push манифеста) |
| 4 | Поток и инструменты | на стриме `llm-svc.` возвращает **только `reasoning_content`**: «Model produced reasoning but no visible response», 0 tool calls. В нестримовом запросе тот же промпт отдаёт `tool_calls` | `model.streaming: false` — обязательный ключ для этого маршрута (док: escape-hatch для OpenAI-совместимых серверов с поломанным стримом tool-call) |
| 5 | Бюджет вывода | reasoning-модель списывает бюджет из общего лимита; при дефолте длинный ответ/вызов инструмента не влезает → `finish_reason: length` | `model.max_tokens: 8000`; `capabilities.answer_in_reasoning` пробовали — **хуже** (Hermes принимал reasoning за финальный ответ и завершал ход), ключ снят |
| 6 | Ключи панели | `hermes config set dashboard.oauth.*` отвечает «unknown key, use --force», но **значение пишет**; `/api/status` → `auth_providers: [basic, self-hosted]` | сид-скрипт в ConfigMap `her-config` фиксирует рабочую последовательность; basic auth — переходный, снимается после браузерной приёмки SSO |
| 7 | TLS | зона `demo-ai-lab.ru` делегирована на **ns1/ns2.reg.ru**, а ClusterIssuer `letsencrypt-wildcard` умеет только Cloudflare-DNS-01 → challenge висит в `pending`, TXT `_acme-challenge` в авторитетной зоне не появляется. HTTP-01 сначала не проходил: на внешней VM **не было слушателя `:80`** (`connection refused` для валидатора) | заведён второй ClusterIssuer `letsencrypt-http01`; на VM добавлен `frontend public_http` (`bind :80`, `redirect scheme https 301`) — валидатор идёт по редиректу на существующий 443-путь, отдельных `:80`-форвардов в SSH-hop'ах не потребовалось. Серт `hm` выпущен 2026-11-06 (LE YR2, до 04.02.2027), копия wildcard больше не нужна |
| 8 | SSO-клиент | клиент `hm` создан сидом (`keycloak_seed.py`): **public**, PKCE S256, redirect `https://hm.demo-ai-lab.ru/auth/callback`; роль `her-user` выдана `user-test`/`admin-test` | редирект проверен: `302 → /realms/dev/protocol/openid-connect/auth?client_id=her&…code_challenge_method=S256`. Условный browser-flow (роль-гейт) **не сделан** — R-H13 открыт |
| 9 | Инструменты | `hermes mcp add` в неинтерактивном exec не проходит (интерактивный выбор инструментов → «Cancelled») | серверы заведены через `hermes config set mcp_servers.<имя>.url`; `hermes mcp test` — зелёный, вызов инструмента моделью: 6 tool calls за 13 с |
| 10 | Проверенные критерии | `/api/status` из LAN и снаружи → 200 (`auth_required=true`); `/` → 302 на `/login`; `/auth/login?provider=self-hosted` → 302 на Keycloak; `hermes chat -q` без инструментов — 5–6 с, с инструментами — 12–13 с | H1–H5 сняты; H6 — остался браузерный вход человека; H7 (край + LAN-гейт), H8 (Desktop/WS), H9 (Kuvasz/бэкап) открыты |

| 11 | Имя хоста | по решению владельца 2026-11-06 адрес сменился `her.` → **`hm.demo-ai-lab.ru`**: пересоздан Ingress, Secret `hm-demo-tls`, в Keycloak заведён клиент **`hm`** (public+PKCE, redirect `https://hm.demo-ai-lab.ru/auth/callback`), старый клиент `her` удалён; в панели `dashboard.public_url` и `client_id` = `hm`. Внутренние имена объектов (ns `her`, PVC `hermes-data`, Secret `her-secrets`, каталог `gitops/apps/her/`) **оставлены**: переименование ns = пересоздание PVC и простой без функциональной выгоды | проверено: `hm./api/status` → 200, `/auth/login?provider=self-hosted` → 302 `client_id=hm`, `her.` → `000` |

| 12 | Порт 80 на VM | в `haproxy.cfg` не было ни одного слушателя `:80` (только `:443`, `127.0.0.1:19443` для резервного туннеля и `18443/18444` — концы SSH-hop'ов). Фильтр источника (100 conn / 50 conn за 10 с) и SNI-запрет для `argo/hgc/lng/mon` живут во `frontend public_https` | добавлен `frontend public_http`: `bind :80`, `mode http`, `redirect scheme https code 301` (бэкап конфига — `haproxy.cfg.bak-<дата>`). Порты 80/443 на VM открыты правилом источника; диапазон источника `0.0.0.0/0`, то есть весь интернет — при необходимости сузить до `/32`. Наблюдение на будущее: `timeout client/server 60s` в `mode tcp` порвёт idle-WebSocket панели/Desktop — для H8 поднять до 300–900 с |

Что осталось сделать руками владельца: войти в панель через Keycloak (`user-test`) и подтвердить, что панель
и чат работают в браузере; после этого снять переходный basic-auth из Deployment и закоммитить
`gitops/apps/her/` (сейчас объекты поставлены `kubectl`, Argo их ещё не видит).

| 13 | GitHub MCP в HTTP-режиме (2026-11-14) | **сервер stateless всегда** (v1.12.0): `initialize` не выдаёт `Mcp-Session-Id`, `tools/list`/`tools/call` отвечают без рукопожатия, `GET`/`DELETE` → 405, в исходниках `Stateless: true`. Env `GITHUB_PERSONAL_ACCESS_TOKEN` в HTTP-режиме **игнорируется** — без `Authorization` `401` даже при заданной переменной, значит под сервера держим **без секретов**, токен идёт заголовком от клиента. Egress 14.11 из пода `hermes` (k8s-03): `api.github.com` → **200** (0.28 s), `github.com` → 200. `tools/list` при `--read-only --toolsets repos,issues,pull_requests,users` → **23** инструмента. Образ **без shell** (distroless), ENTRYPOINT — `/server/github-mcp-server` | §7.1: self-host `ghcr.io/github/github-mcp-server:v1.12.0` в ns `mcp-github` (ClusterIP), `HER_GITHUB_PAT` в `her-secrets` → env `hermes`; в манифесте `args` (а не `command`), пробы только `tcpSocket`, exec-проверки — из пода `hermes`; раскатка и приёмка — H10 |

## 14. Связанные документы и история

- Модели и внешний маршрут: `architecture/specs/llm-proxy-spec.md` (P\*), `adr/adr-0008-external-llm-deepseek-proxy.md`,
  `adr/adr-0006-guardrail-higress-qwen3guard.md`.
- Локальная 27B: `architecture/specs/gpustack-custom-backend-spec.md` (B\*), `cases/01-27b-one-card.md`.
- SSO: `architecture/specs/keycloak-spec.md` (K\*); адреса и клиенты — `architecture/endpoints.md`.
- MCP стенда: `architecture/specs/doc-spec.md` (D\*), `architecture/specs/ysearch-spec.md` (Y\*),
  `architecture/specs/mcp-registry-spec.md` (M\*), `adr/adr-0005-*`, `adr/adr-0009-monitoring-kuvasz.md`;
  **GitHub MCP — только эта спека §7.1** (self-host, ClusterIP; в каталог `mcp.` — по ADR-0012).
- Кластер и размещение: `architecture/specs/k8s-install-spec.md` (F\*), `architecture/ARCHITECTURE.md` §5–§7.
- Внешний доступ и LAN-гейт: `architecture/specs/external-access-spec.md` (E6/E9).
- Документация продукта (сверка §0): `hermes-agent.nousresearch.com/docs` — `features/web-dashboard`,
  `user-guide/docker`, `features/mcp`, `reference/mcp-config-reference`, `features/browser`,
  `user-guide/configuring-models`, `user-guide/configuration`.

| Версия | Дата | Что изменилось |
|---|---|---|
| v1.6 | 2026-11-17 | ADR-0012 переопределяет §7.1 в части каталога и набора: GitHub MCP доступен **обоим** агентам и обязан попасть в каталог `mcp.` (нужен внутренний адрес); «в каталог не публикуем» и «только у Hermes» снято, реализация — задача |
| v1.5 | 2026-11-14 | **GitHub MCP включён в набор агента** (решение владельца): §7.1 — self-host `ghcr.io/github/github-mcp-server:v1.12.0` в ns `mcp-github` (ClusterIP, без Ingress/SSO/каталога), `--read-only` + `--toolsets repos,issues,pull_requests,users`, PAT per-request из `her-secrets`, под сервера без секретов; stateless и отсутствие env-токена в HTTP-режиме подтверждены замером; egress `api.github.com` замерен 200 из пода. Приёмка — H10, риски R-H17…R-H19, вопрос Q-H7. **Раскатка не выполнена** |
| v1.4 | 2026-11-14 | **R-H16 закрыт:** причина урезанных caps на 02/03 — `base_runtime_spec`, снятый 08.11; проверены `CapEff 0xa80425fb`, `chown`/`setgroups` и s6-drop, образ Hermes поднялся на 02. Обходной `nodeAffinity` снят: `required` 01/02/03, `preferred` — пара ingress; `k8s_health.py` проверяет `base_runtime_spec` в SSH-замере |
| v1.3 | 2026-11-06 | развёрнуто H1–H5 (журнал §13): `args` вместо `command`, без `securityContext`, обход дефекта capabilities на 02/03, `streaming: false` + `max_tokens`, wildcard-серт вместо DNS-01, клиент `hm` в сиде Keycloak. v1.2: решение владельца: браузер — Chromium официального образа, CDP-вынос отложен (§1, §4.2, §8.1); Q-H6 переформулирован под `browser.user_data_dir`. v1.1: §8.1: вынос браузера по CDP — `browser.cdp_url`/`BROWSER_CDP_URL`, сравнение «контейнер / sidecar / отдельный под», эскалация, R-H14/R-H15, Q-H6 (тёплый профиль). v1.0: первая редакция: пины образа сверены по Docker Hub API, SSO-механика, MCP-набор, две модели, обвязка (в т.ч. ответ «Playwright не нужен»), фазы H1–H9, риски. Живых шагов не выполнено — статус «спека, не установлено» |
