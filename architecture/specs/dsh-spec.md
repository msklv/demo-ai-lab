# dsh-spec — DeepSeek Harness (`dsh.`) на стенде: SSO-гейт, две модели, MCP и каталоги, k8s-05

> **Версия:** v1.2 (2026-11-24) · **Статус:** **развёрнуто** — W1–W3, W5–W7 закрыты на стенде
> (`dsh.` за SSO-гейтом, свой TLS, **официальный `dsh-mcp-manager`** на 5 серверов, стартовые скиллы);
> **W4 закрыт только на локальном маршруте** (внешний `deepseek-flash` ждёт поднятого стража), W8 не начат.
> **Цель:** шаг 4 демо, второй агентский рантайм (ADR-0012) — агент-харнесс с песочницей и плагинами:
> вход через **SSO Keycloak** гейтом на шлюзе, две модели (локальная `Qwen3.8-27B-UD` через `api.` и
> внешняя `deepseek-flash` через `llm-svc.` — DLP + страж fail-closed), инструменты — **MCP-серверы стенда**,
> доступ к **каталогу MCP** (`mcp.`) и **каталогу скиллов** (GitHub-репо, ADR-0010).
> **Внешнее имя:** `dsh.demo-ai-lab.ru` — Ingress Higress, TLS `letsencrypt-http01` (как `hm.`/`spk.`).
> **Механизм развёртывания:** Argo CD, каталог `gitops/apps/dsh/`; образ собирается нами (официального нет).
> Креды — `dsh.local.md` (в `.gitignore`). Ничего секретного в этом документе нет.

Фазы этой спеки — **W1–W8** (буква W не занята; занятые: F, E, K, G, O, S, D, Y, M, P, H, R).

## 0. Что уточнила сверка с источниками (2026-11-17)

Сверялись: npm-реестр `@deepseek-ai/dsh` (dist-tags, engines, integrity), `docs/user/guide/configuration`
(слои конфигурации, `settings.yaml`), `docs/user/guide/public-deployments` (публикация Web UI за прокси),
`packages/mcp/mcp-client` (транспорты MCP), npm-пакеты `@deepseek-ai/dsh-skill`, `@deepseek-ai/dsh-mcp-client`.

| Что | Ожидание «по аналогии» | Факт (проверено 2026-11-17) |
|---|---|---|
| Версия | «стабильный релиз» | npm `latest` = **`0.2.2-rc.5`** (24.11), `alpha` = `0.2.3-alpha.2`; стабильного тега нет — берём `latest` и фиксируем |
| Node | «любой» | `engines: node >= 24.9.0` — база образа `node:24-slim` |
| Адрес слушателя | «bind 0.0.0.0:3080» | `--profile web` без флагов слушает **loopback**: `--host` принимает **один конкретный** адрес интерфейса, wildcard отвергается (`Usage: --host <host> bind address: one concrete IPv4 or IPv6 literal…`). Поэтому слушатель — `--host $(POD_IP)` (downward API), проверено W2 |
| Прокси | «переписать Host и всё» | Прокси обязан: сохранить **browser-facing `Host`** (иначе `403` на все API), форвардить `Upgrade`/`Connection`, отдать `/` → `/` (только `/` и `/connect` обменивают launch-token на cookie) |
| Конфигурация | «`settings.yaml` — живой файл настроек» | В `0.2.2-rc.5` `settings.yaml` — **legacy**: импортируется ОДИН раз в `<DSH_HOME>/profiles/web/cordis.patch.yml` и переименовывается в `settings.yaml.imported`. Живая поверхность — слои Cordis-патчей: бандл → профиль → home-патч → `--patch` |
| Флаги лаунчера | «как у любого CLI» | `--profile` и `--patch` — флаги **лаунчера**: первый незнакомый ему токен начинает app-аргументы, поэтому `--patch` после `--port` уезжает в приложение → `error: unknown option '--patch'` (проверено W2) |
| Аутентификация | «есть OIDC, как у Hermes» | **Своего OIDC нет**: вход = launch-token в напечатанном URL + подписанная сессионная cookie; учётка **одна** (права = владелец процесса) |
| MCP | «только плагины» | Есть официальный мост **`@deepseek-ai/dsh-mcp-client`** — «connects to MCP servers and registers their tools», транспорты `stdio` и `StreamableHTTP` |
| Скиллы | «скиллы = плагины» | Отдельный пакет **`@deepseek-ai/dsh-skill`** — «agent skill provider registry»: скиллы каталогом SKILL.md-файлов |
| Провайдеры моделей | «только DeepSeek official» | `llm-pi-ai.providers.<id>`: `apiKeyEnv`, `api: openai-completions`, `baseURL`, `models[]`; дефолтная модель — строка `agent-default-model` (`provider` + `model`) в том же слое патча, не в `settings.yaml` |
| MCP-конфиг | «один плагин со списком `servers[]`» | `dsh-mcp-client` — **один entry на сервер** (`serverName`, `transport`, `url`/`headers`); несколько entry в одном `insert`; инструменты видны модели как `mcp__<serverName>__<tool>` |
| Песочница | «контейнер на задачу» | Пресеты процесса: `read-only` / `workspace-write` / `danger-full-access` (`permission.defaultPreset`); изоляция — процессная, не отдельный под |
| Образ | «есть официальный» | В Docker Hub и ghcr официального образа нет (ghcr на `deepseek-ai/dsh` отвечает `401`, Hub по «deepseek harness» — мимо) → **образ собираем сами** |

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ | **свой**: `ghcr.io/msklv/dsh:v0.2.2-rc.5` — `FROM node:24-slim` + `npm i -g @deepseek-ai/dsh@0.2.2-rc.5` (integrity пакета `sha512-cNbp12tLYLUTXaVli7zwwMjzmmEVCD1PRldg4oKtXM4+lFYckcaliMS2PU/FoThB4iAN/fKOSID0nrtRZU4Gjw==`) | официального образа нет; пин по версии + пуш в ghcr, деплой по **дигесту** (прецедент — форк-образы (`ghcr.io/msklv/…`), снятые вместе с QM; правило «тег двигается, дигест нет» остаётся) |
| Namespace | `dsh` | паттерн «один ns на сервис» |
| Реплики | **1**, `strategy: Recreate` | состояние — каталог `/opt/data` на PVC; два писателя в один том не поддерживаются |
| Размещение | **приоритет — k8s-05** (`preferred`, вес 100), альтернатива k8s-01 | решение владельца; 05 без GPU и без шлюза, там же RAGFlow и Firecrawl — RAM-бюджет §5 `architecture/ARCHITECTURE.md` |
| Ресурсы | requests `250m/512Mi`, limits `1/2Gi` | веб-UI + Node-рантайм агента без локальных моделей; замер в W3 |
| Данные | PVC **5 Gi** `longhorn` (r=2), `mountPath: /opt/data` | сессии, память, скиллы, плагины профиля |
| Web | `dsh --profile web --patch /etc/dsh/overlay.yml --public-url https://dsh.demo-ai-lab.ru/ --trusted-host dsh.demo-ai-lab.ru --host $(POD_IP) --port 3080`, под `tini` + обёрткой `run-dsh.sh` | слушатель — **конкретный адрес пода**: wildcard CLI отвергает; порт 3080 наружу не публикуется, в ns до него доходит только `dsh-auth` |
| SSO | **`oauth2-proxy` перед dsh**: Keycloak realm `dev`, клиент **`dsh`** (confidential), redirect `https://dsh.demo-ai-lab.ru/oauth2/callback`; upstream `http://dsh.dsh.svc:3080/` + второй `http://dsh.dsh.svc:4181/launch/` | у dsh нет OIDC (§0); в Higress из OIDC-login нет ничего (установлены только `jwt-auth`, `key-auth`, `opa`, `ip-restriction`, ai-\* — 17.11), поэтому гейт делает прокси, а не шлюз |
| Вход для человека | `https://dsh.demo-ai-lab.ru/launch` — страница-редирект на launch-URL текущего пода (§5.1) | launch-token печатается только в лог процесса и меняется при каждом старте; без страницы каждый гость лезет в `kubectl logs` |
| Публичность | снаружи сразу за SSO-гейтом (W7 принят 23.11); LAN-гейт `lan-only-ui` — **отдельной правкой после приёмки** | правило E6/ADR-0004: сначала LAN, потом край; исключение сделано сознательно — иначе выпуск/продление серта требует окна с исключением хоста из обоих `lan-only-ui*` |
| Модели | локальная **`Qwen3.8-27B-UD`** через `api.`; внешняя **`deepseek-flash`** через `llm-svc.` (DLP + страж fail-closed) | §4 |
| MCP | **официальный `@deepseek-ai/dsh-mcp-manager`** (строка профиля `web` с 0.2.2-rc.5): по инстансу `dsh-mcp-client` на сервер, статус/`restart`/`probe`, правка из Settings; набор — `config.servers` оверлея; серверы — `doc.`, `ysrch.`, `mon.`, `github`, `firecrawl`, `rag.` (после деплоя) | §6; набор инструментов общий с Hermes (ADR-0012) |
| Плагины | сверх бандла — `dsh-hooks-codex` (+`hook-protocol`), `dsh-tool-todo`, `dsh-tool-workflow` включены; `dsh-webhook`/`dsh-webhook-github` доставлены выключенными | §6.1; версии прибиты к рантайму (peer-строгие) |
| Каталоги | **каталог MCP** — чтение `https://mcp.demo-ai-lab.ru/v0/servers`; **каталог скиллов** — GitHub-репо `msklv/skills-demo-ai-lab` по пину коммита | ADR-0005 (каталог), ADR-0010 (скиллы = отдельный репозиторий) |
| Песочница | `permission.defaultPreset: workspace-write`; `danger-full-access` **запрещён** | агент исполняет чужой текст; полный доступ = «шелл по HTTP» |

## 2. Предпосылки (проверить до W1)

| Что | Состояние | Проверка |
|---|---|---|
| Реестры при сборке | сборка образа требует доступа к npm-реестру и ghcr | сборочная машина/CI: `npm view @deepseek-ai/dsh@0.2.2-rc.5 version`; push в `ghcr.io/msklv/` |
| Node-версия | `engines >= 24.9.0` | `node --version` в образе ≥ 24.9 |
| Keycloak | клиент `dsh` **заведён 23.11** (confidential, redirect `/oauth2/callback`), секрет — в `keycloak-clients.local.md` | `scripts/keycloak_seed.py`, §5 |
| Внешняя модель | `llm-svc.` работает со статическим ключом; страж fail-closed | `POST /v1/chat/completions` → 200; без стража → `503 guard unavailable` |
| Локальная модель | `Qwen3.8-27B-UD` в GPUStack, резидентной не держим (ADR-0007) | в кейсе 06 карта занята стражем `Qwen3Guard-Gen-4B` ≈12,7 GiB → 27B только когда карта свободна |
| MCP-серверы | `doc.`, `ysrch.`, `mon.` живы; `github` — в оверлее (24.11), работает при заданном `GITHUB_PAT`; `rag.` — после `rag-spec` R1–R8 | вызов `initialize` по in-cluster DNS из пода `dsh` |
| Каталог скиллов | репозиторий `msklv/skills-demo-ai-lab` опубликован (ADR-0010) | `git ls-remote` + фиксация коммита в `values` |
| Узел 05 | 30,5 GiB allocatable, занято Firecrawl ≈5 GiB + Kuvasz/Postgres ≈1 GiB + RAGFlow (по `rag-spec`) | `kubectl describe node k8s-05` |

## 3. Секреты (`dsh.local.md`, gitignored)

| Ключ (файл → имя ключа) | Куда идёт |
|---|---|
| `dsh-client-secret` (`keycloak-clients.local.md`) | Secret `dsh-oidc` → `OAUTH2_PROXY_CLIENT_SECRET` |
| `cookie_secret` (`dsh.local.md`) | Secret `dsh-oidc` → `OAUTH2_PROXY_COOKIE_SECRET`. **32 символа ASCII**: oauth2-proxy принимает только 16/24/32 байта, `openssl rand -base64 32` даёт 44 и роняет прокси (`cookie_secret must be 16, 24, or 32 bytes`, проверено W1) |
| `gpustack_key` (`dsh.local.md`) | Secret `dsh-models` → `GPUSTACK_API_KEY`; ключ GPUStack `dsh` с `allowed_model_names: [Qwen3.8-27B-UD]` |
| `svc_api_key` (`llm.local.md`) | Secret `dsh-models` → `LLM_SVC_API_KEY` (статический ключ стенда, общий) |
| `admin-mcp-api-key` (`kuvasz.local.md`) | Secret `dsh-mcp` → `KUVASZ_MCP_KEY` (`X-API-KEY` для `mon./mcp`) |
| `github-pat` (если включён `github-mcp`) | Secret `dsh-mcp` |

Скрипт `scripts/dsh_secrets.sh` (`--init` заводит `dsh.local.md`) создаёт Secret'ы **до** первого синка;
значения в вывод не попадают, печатаются только имена ключей.

## 4. Модели и конфигурация

Слои конфигурации: бандл профиля → `cordis.patch.yml` профиля → home-патч → **`--patch`**. Конфиг
стенда живёт в последнем слое: ConfigMap `dsh-config` → `/etc/dsh/overlay.yml`, применяется при каждом
старте. `settings.yaml` в этой версии не используется (§0) — правка в git + рестарт пода вместо дрейфа
конфигурации в PVC (у `her.` конфиг, наоборот, в томе).

```yaml
# overlay.yml (фрагмент; значения ключей — из env, Secret dsh-models)
- id: llm-pi-ai                    # заменяет config строки целиком
  config:
    providers:
      gpustack:                   # локальная 27B (кейс 01, карта свободна)
        displayName: GPUStack (локальная)
        apiKeyEnv: GPUSTACK_API_KEY
        api: openai-completions
        baseURL: https://api.demo-ai-lab.ru/v1
        models: [{id: Qwen3.8-27B-UD, contextWindow: 131072}]
      llm-svc:                    # внешняя модель: DLP + страж fail-closed + лимиты
        displayName: llm-svc. (внешняя, DLP + страж)
        apiKeyEnv: LLM_SVC_API_KEY
        api: openai-completions
        baseURL: https://llm-svc.demo-ai-lab.ru/v1
        models: [{id: deepseek-flash, contextWindow: 131072}]
- id: agent-default-model         # дефолт для новых агентов
  config: {provider: llm-svc, model: deepseek-flash}
```

Песочница задаётся переменной процесса `DSH_PERMISSION_MODE=workspace-write` (в бандле это же значение
по умолчанию — выписано явно, чтобы не зависеть от версии бандла).

| Роль | Модель | Маршрут | Ограничение |
|---|---|---|---|
| Дефолт | `deepseek-flash` (128K) | `llm-svc.` | страж `Qwen3Guard-Gen-4B` (≈12,7 GiB на 5070 Ti) должен быть поднят, иначе `503` |
| Локальная | `Qwen3.8-27B-UD` (128K) | `api.` / GPUStack | резидентной нет (ADR-0007): доступна, когда карта не занята стражем/генерацией |

## 5. SSO-гейт

`oauth2-proxy` в ns `dsh`, версия `v7.15.6` (quay.io, пин по дигесту `sha256:c3415e86…b12048`):

| Параметр | Значение |
|---|---|
| `--provider` | `keycloak-oidc`, issuer `https://auth.demo-ai-lab.ru/realms/dev` |
| `--client-id` / secret | `dsh` / из Secret `dsh-oidc` |
| `--redirect-url` | `https://dsh.demo-ai-lab.ru/oauth2/callback` |
| `--upstream` (два) | `http://dsh.dsh.svc:3080/` (dsh) и `http://dsh.dsh.svc:4181/launch/` + `/launch` (§5.1) — маршрутизация по префиксу пути |
| `--cookie-secret` | из Secret `dsh-oidc`; cookie `Secure`, `SameSite=Lax`, `--cookie-expire=8h`, `--cookie-refresh=30m` |
| `--pass-host-header` | `true` — Host не переписывается (R-W5) |
| `--code-challenge-method` | `S256` (Keycloak умеет PKCE; без флага прокси логирует предупреждение) |
| `--trusted-proxy-ip` | `10.0.0.0/8` — без него `--reverse-proxy` доверяет `X-Forwarded-*` любому источнику |
| `--email-domain` | `*` (пул демо-учёток `devrel01…devrel20` + `user-test`, как у остальных сервисов) |
| Порт | 4180; наружу не публикуется — Ingress ведёт на него |

Ingress: host `dsh.demo-ai-lab.ru`, `/` → `dsh-auth:4180`, TLS `Certificate dsh-demo-tls`
(`letsencrypt-http01`). LAN-гейт `lan-only-ui` на `dsh.` пока **не** навешен: в список входят
`argo/hgc/lng/mon`, и его добавление само требует окна выпуска серта (ACME получает 403) — см.
`cert-issuance-lan-only` в скилле стенда.

### 5.1 Вход для человека: `/launch`

Проблема: dsh пускает по **launch-token**, который печатается только в лог процесса
(`dsh web: https://dsh.demo-ai-lab.ru/?token=…`) и генерится заново на каждый старт; cookie подписана
секретом из credential-стора на PVC (живёт до 30 дней, рестарт пода её не отменяет), но новый браузер
без токена получает `401 dsh web authentication required; reopen the URL printed by dsh web`. Гнать
каждого гостя в `kubectl logs` — не вариант для демо.

Решение (в поде `dsh`, `2/2`):

| Часть | Что делает |
|---|---|
| `run-dsh.sh` (обёртка, ConfigMap) | запускает `dsh …` через `tee` в `/var/run/dsh/dsh.log`, ловит строку с `?token=`, атомарно кладёт `index.html` с `<meta http-equiv="refresh">` на этот URL |
| сайдкар `launch` (тот же образ, `node launch-server.js`) | на `:4181` отдаёт эту страницу (любой путь), `/healthz` → 200 |
| `oauth2-proxy` | второй upstream `…:4181/launch/` + `…:4181/launch`; **страница за тем же SSO** — токен не уезжает к неаутентифицированному клиенту |

Поток: `GET /launch` → SSO-редирект → после входа 200 с meta-refresh → `/?token=…` → `303 ./` +
cookie dsh → `/` = UI. Проверено end-to-end скриптовым входом `user-test` (302 → Keycloak → callback →
`/launch` 200 → `/?token` 303 → `/` 200, 40 102 байта HTML).

Токен не логируется сайдкаром и не попадает в ответ иначе как внутри самой страницы; доступ к странице
= доступ к dsh, поэтому отдельного пути «только для админа» не заводим. Для диагностики —
`./scripts/dsh_launch_url.sh --token` (сырой URL из лога), обычный вход — `./scripts/dsh_launch_url.sh`.

**Что гейт НЕ даёт (честно):** dsh остаётся **single-identity** — после входа по SSO любой гость работает
в одном и том же рабочем пространстве с правами владельца процесса. Персональной идентичности внутри
агента нет; различить гостей можно только по логам Keycloak и access-логу шлюза. Это ограничение самого
рантайма (§0), а не реализации гейта, и оно фиксируется на сцене словами, а не замалчивается.

## 6. MCP и каталоги

| Инструмент | Адрес (in-cluster) | Авторизация |
|---|---|---|
| Docling MCP | `http://docling.doc.svc:8000/mcp` | нет |
| Yandex Search MCP | `http://yandex-search.ysrch.svc:8766/mcp` | ключ Search API — внутри сервиса |
| Kuvasz MCP | `http://kuvasz.monitoring.svc:8080/mcp` | `X-API-KEY` (Secret `dsh-mcp`) |
| RAGFlow MCP | `http://ragflow.rag.svc:9380/api/v1/mcp` | API-ключ RAGFlow per-client |
| GitHub MCP | `http://github-mcp.mcp-github.svc:8101/mcp` | `Authorization: Bearer <PAT>` per-request |
| Firecrawl MCP | `http://firecrawl-mcp.fc.svc:8080/mcp` | нет (self-host без аутентификации) |

Правило ADR-0012: **MCP смотрят только внутрь** — все адреса in-cluster, внешних маршрутов у MCP нет.

Менеджер уже в профиле `web` (строка `mcp-manager`); серверы задаются `config.servers` в оверлее —
полный список в `gitops/apps/dsh/20-config.yaml` (источник истины), здесь форма записи:

```yaml
- id: mcp-manager
  config:
    servers:
      firecrawl: {transport: streamable-http, url: 'http://firecrawl-mcp.fc.svc.cluster.local:8080/mcp'}
```

`github` — токен per-request из `GITHUB_AUTH` (`hermes-spec` §7.1), без ключа инструменты дают `401`;
`ragflow` не подключаем — ns `rag` держит только эмбеддинги/реранкер (`rag-spec` R1–R8).

**Каталоги:**

- **MCP-каталог** — чтение `GET https://mcp.demo-ai-lab.ru/v0/servers` (6 записей: docling, yandex-search,
  kuvasz, ragflow, github, firecrawl); агент получает список инструментов и ссылки, сами вызовы — по адресам выше.
  Второй реестр (плагин `dsh-mcp-registry` из npm) **не берём**: сторонний код в горячем пути агента.
- **Каталог скиллов** — репозиторий `msklv/skills-demo-ai-lab` (ADR-0010). Копируется в образ
  initContainer'ом `git clone` по **пину коммита** в `/opt/data/skills`; полный каталог не кладём — стартовый
  набор 3–5 скиллов (иначе системный промпт раздувается).

### 6.1 Официальные плагины сверх бандла (2026-11-24)

В бандле `web` (`0.2.2-rc.5`) уже 337 пакетов (разница с каталогом npm — 11); пакеты — в `image/Dockerfile`, строки — в оверлее:

| Пакет (все `0.2.2-rc.5`) | Состояние | Зачем |
|---|---|---|
| `dsh-hooks-codex` (+ `dsh-hook-protocol` — библиотека, не плагин) | **включено** | детерминированный гейт вне модели: `/etc/dsh/hooks.json` из ConfigMap. `SessionStart` даёт контекст, `PreToolUse` на `bash` блокирует разрушительные команды (`guard-bash.js`, блок = exit 2 + причина в stderr) |
| `dsh-tool-todo`, `dsh-tool-workflow` | **включено** (в бандле `disabled: true`) | план задачи, переживающий ходы; JS-оркестрация субагентов одним вызовом |
| `dsh-webhook` + `dsh-webhook-github` | **доставлено, выключено** | вход GitHub-событий в сессию; включение = маршрут на edge + HMAC-секрет + правила диспатча |

Не берём: `dsh-experimental-*` (pre-alpha), `dsh-office-to-pdf` (LibreOffice ~700 МБ — есть docling), `dsh-tool-web`/`web-search-deepseek` (egress мимо `llm-svc`/DLP), `dsh-api-account-controller`, сторонние панели и маркетплейсы.
**Телеметрия:** `session-telemetry-otel` по умолчанию шлёт логи сессии на `dsh-otel-collector.deepseeksvc.com`;
на стенде внешний экспорт выключен `DSH_TELEMETRY_DISABLED=1`.

## 7. Состав каталога `gitops/apps/dsh/` и образ

| Файл | Что | sync-wave |
|---|---|---|
| `00-namespace.yaml` | Namespace `dsh` | −1 |
| `10-pvc.yaml` | PVC 5Gi Longhorn (`/opt/data`) | 0 |
| `20-config.yaml` | ConfigMap `dsh-config`: `overlay.yml` (§4), MCP-мост (§6), `run-dsh.sh` + `launch-server.js` (§5.1), `seed-skills.sh` | 0 |
| `30-dsh.yaml` | Deployment `dsh` (`2/2`: dsh + сайдкар `launch`; образ по дигесту, `Recreate`), Service `dsh:3080` и `dsh:4181` | 1 |
| `40-auth.yaml` | Deployment `dsh-auth` (oauth2-proxy) + Service `dsh-auth:4180`, `envFrom` Secret `dsh-oidc` | 1 |
| `50-ingress.yaml` | `Certificate dsh-demo-tls` + Ingress `/` → `dsh-auth:4180` | 2 |
| `image/Dockerfile` | `FROM node:24-slim`, `npm i -g --allow-scripts=… @deepseek-ai/dsh@0.2.2-rc.5`, `USER node`, `WORKDIR /opt/data` | сборка |

Сборка: `docker buildx build --platform linux/amd64 -t ghcr.io/msklv/dsh:v0.2.2-rc.5 gitops/apps/dsh/image`
→ `skopeo copy --dest-creds msklv:$TOKEN docker-daemon:… docker://ghcr.io/msklv/dsh:v0.2.2-rc.5` →
дигест (`skopeo inspect --override-arch amd64`) в `30-dsh.yaml`. Обновление рантайма — новая версия пакета
→ новый тег/дигест → синк Argo (обновление «на месте» запрещено).

Пять граблей сборки и пуша (проверены 23.11, дополнены 24.11):

- `npm i -g` **без** `--allow-scripts` пропускает install-скрипты `node-pty`/`koffi`/`dsh-subprocess-local` —
  образ собирается, но терминал агента не работает; нужен явный список пакетов.
- Пакет ghcr по умолчанию **приватный**: анонимный pull → `401`, кластер получает `ErrImagePull`.
  Каталог стенда тянет образы анонимно, поэтому пакет `ghcr.io/msklv/dsh` переведён в **public**
  (UI GitHub; через REST видимость container-пакетов не меняется).
- Пуш из локального демона — `skopeo copy` с `--dest-creds`, а не `docker login`: не трогает
  credential store машины.
- **Плагины не ставятся ни `--prefix`, ни в `node_modules` пакета dsh:** первый даёт `up to date` без
  пакета на диске, второй — `ERR_MODULE_NOT_FOUND` (загрузчик профиля резолвит из `<profile>/node_modules`).
  Рабочая схема — пакеты в образе + `seed_plugins` в `run-dsh.sh` (§6.1). Библиотеку
  `dsh-hook-protocol` строкой не монтировать: это не cordis-плагин (`failed to import`).
- **`node-addon-landlock-run-linux-x64` в образ не попал:** OS-level песочница bash (W8) пока не
  включена, работают пресеты процесса (`workspace-write`) + `approval: ask`.

## 8. Фазы W1–W8 (каждая — приёмка командами)

| # | Что | Приёмка |
|---|---|---|
| **W1** | `scripts/dsh_secrets.sh`, каталог `gitops/apps/dsh/`, образ собран и запушен, пин по дигесту | ✅ Secret'ы на месте; `ghcr.io/msklv/dsh@sha256:c930c026…9be6` в манифесте; анонимный pull проходит (пакет public) |
| **W2** | PVC, ConfigMap (`overlay.yml` вместо `settings.yaml`), под + сайдкар | ✅ `dsh 2/2 Running` на k8s-05; лог: `listening on <pod IP>:3080` + напечатанный URL; `/launch` публикует страницу |
| **W3** | web за прокси без SSO (внутренняя проверка) | ✅ из пода: `/` с cookie → 200 `text/html`, 40 102 байта. `port-forward` **не работает** — слушатель на адресе пода, не на loopback: проверка идёт `kubectl exec … curl -H 'Host: dsh.demo-ai-lab.ru' http://<podIP>:3080/` |
| **W4** | модели (§4) | ✅ локальная: `--profile headless --patch overlay-local.yml` → ответ `работает` от `Qwen3.8-27B-UD`. ⏳ внешняя: `POST` доходит до `llm-svc.` и падает `503 guard unavailable` — поднять `Qwen3Guard-Gen-4B` (с 27B на одной карте не сядет) |
| **W5** | MCP (§6) | ✅ `initialize` → 200 у `docling`, `yandex_search`, `kuvasz` (с `X-API-KEY`); инструменты видны модели как `mcp__<server>__<tool>` |
| **W6** | каталоги | ✅ `/opt/data/skills`: `pdf`, `xlsx`, `systematic-debugging`, `test-driven-development` (пин `2007447…`); каталог MCP (4 записи) читается по `mcp.` |
| **W7** | SSO-гейт, `/launch` и TLS | ✅ `GET /` и `/launch` → 302 на `auth.demo-ai-lab.ru`; скриптовый вход `user-test`: callback → `/launch` 200 → `/?token` 303 → `/` 200; `Certificate` Ready (`CN=dsh.demo-ai-lab.ru`, LE, до 21.02.2027) |
| **W8** | песочница и границы | 🟡 частично 24.11: `sandbox-local` + `sandbox-policy` + `bash-sandbox` + `approval: ask` смонтированы бандлом, `DSH_PERMISSION_MODE=workspace-write` задан явно (§6.1); остаётся `NetworkPolicy` egress (в текущем виде отрезала бы init-контейнеру `github.com`) и проверка записи вне `/opt/data` |

## 9. Риски

| ID | Риск | Митигация |
|---|---|---|
| **R-W1** | Рантайм на **release-candidate** (`0.2.2-rc.5`) — API плагинов может разъехаться | фиксируем версию в образе; обновление — отдельным тегом после проверки W2–W5 |
| **R-W2** | dsh **single-identity**: SSO пускает людей, но внутри все работают под одной учёткой | ограничение рантайма, не гейта; на сцене проговариваем; на демо — один гость за раз |
| **R-W3** | Песочница процессная: агент видит ФС пода | `workspace-write` + PVC только `/opt/data` + `NetworkPolicy`; `danger-full-access` запрещён |
| **R-W4** | Внешняя модель уходит через `llm-svc.`, но 27B не влезает при поднятом страже | дефолт — `deepseek-flash`; локальную включаем только в кейсе 01 |
| **R-W5** | `Host`/WebSocket за прокси: любая правка `Host` → `403` на все API | прокси не переписывает `Host` (штатный `oauth2-proxy` upstream), проверка в W3/W7 |
| **R-W6** | RAM на 05: Firecrawl + Kuvasz + RAGFlow + dsh | `preferred`, а не `nodeSelector`; замер: 119m CPU / 461Mi — с запасом; при нехватке — k8s-01 |
| **R-W7** | `/launch` отдаёт страницу с launch-token: ошибка в маршрутизации (например, upstream на сайдкар без SSO) = вход в dsh без аутентификации | путь `/launch` проходит через тот же `oauth2-proxy`; отдельного Ingress-правила на сайдкар нет; проверка в W7 — без SSO-сессии `/launch` отдаёт `302`, а не 200 |
| **R-W8** | Обёртка `run-dsh.sh` встаёт между `tini` и `dsh`: сигналы и код выхода | `tini` остаётся PID 1, обёртка ловит `TERM/INT` и пересылает `dsh`; вывод идёт через `tee`, поэтому `kubectl logs` не меняется |

## 10. Открытые вопросы

| ID | Вопрос |
|---|---|
| **Q-W1** | ~~Нужен ли `headless`-профиль~~ — **закрыт 23.11**: headless работает и используется для приёмки моделей (`--profile headless … 'промпт'`), профиль инициализируется в `/opt/data/profiles/headless` |
| **Q-W2** | Оставляем ли доступ к `github-mcp` (PAT per-request) на сцене или только в artisan-режиме |
| **Q-W3** | ~~Сколько скиллов~~ — **закрыт 23.11**: стартовый набор 4 (`pdf`, `xlsx`, `systematic-debugging`, `test-driven-development`); расширяется правкой `seed-skills.sh` |

## 11. Связанные документы

- `adr/adr-0012-two-agent-runtimes-hermes-and-dsh.md` — решение: два рантайма, SSO, MCP внутрь.
- `architecture/specs/hermes-spec.md` (H\*) — первый агент: нативный SSO, MCP, GitHub MCP §7.1.
- `architecture/specs/rag-spec.md` (R\*) — RAGFlow MCP (`/api/v1/mcp`) и каталог.
- `architecture/specs/mcp-registry-spec.md` (M\*) — каталог MCP, публикация, `server.json`.
- `architecture/specs/llm-proxy-spec.md` (P\*) — `llm-svc.`, DLP, страж, лимиты; ADR-0008.
- `architecture/specs/keycloak-spec.md` (K\*) — клиент `dsh`, realm `dev`.
- `architecture/endpoints.md` — адрес `dsh.`; `cases/06-agents-sandbox.md` — сценарий показа.

## 12. История

| Версия | Дата | Что изменилось |
|---|---|---|
| v1.2 | 2026-11-24 | рантайм поднят до **`0.2.2-rc.5`** (образ `ghcr.io/msklv/dsh:v0.2.2-rc.5`): в этой версии профиль `web` монтирует **официальный `@deepseek-ai/dsh-mcp-manager`**, поэтому пять строк `dsh-mcp-client` заменены одной строкой `mcp-manager` + `config.servers` (источник истины остаётся git, Settings правит сессию); добавлен сервер `firecrawl` (ns `fc`); в каталоге MCP 6 записей |
| v1.1 | 2026-11-23 | **развёрнуто на стенде** (W1–W3, W5–W7): образ собран и запушен по дигесту (пакет ghcr переведён в public), ns/PVC/ConfigMap/Secret'ы/`oauth2-proxy`/Ingress + серт `CN=dsh.demo-ai-lab.ru` до 21.02.2027; конфиг переведён с `settings.yaml` на `--patch`-оверлей (в 0.2.2 `settings.yaml` — legacy), MCP-мост — один entry на сервер, слушатель `--host $(POD_IP)`; добавлен вход `/launch` (обёртка + сайдкар за тем же SSO, §5.1); локальный маршрут модели проверен ответом, внешний ждёт страж; закрыты Q-W1/Q-W3, добавлены R-W7/R-W8 |
| v1.0 | 2026-11-17 | спека создана: свой образ `ghcr.io/msklv/dsh:v0.2.2-rc.1` (node 24, пин по дигесту), один под + PVC `/opt/data`, SSO-гейт `oauth2-proxy` (Keycloak, клиент `dsh`), две модели (`Qwen3.8-27B-UD` через `api.`, `deepseek-flash` через `llm-svc.` со стражем и DLP), мост `@deepseek-ai/dsh-mcp-client` на 5 MCP-серверов, каталог MCP и каталог скиллов (GitHub-репо, пин коммита), песочница `workspace-write`, размещение — k8s-05 |
