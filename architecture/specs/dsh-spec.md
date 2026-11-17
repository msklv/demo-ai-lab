# dsh-spec — DeepSeek Harness (`dsh.`) на стенде: SSO-гейт, две модели, MCP и каталоги, k8s-05

> **Версия:** v1.0 (2026-11-17) · **Статус:** **спека, не развёрнуто** — ns `dsh` в кластере отсутствует,
> записи каталога MCP для агента нет (агент — потребитель, не сервер).
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
| Версия | «стабильный релиз» | npm `latest` = **`0.2.2-rc.1`** (2026-11-04), `next` = `0.2.2-rc.3`, `alpha` = `0.2.2-alpha.3`; стабильного тега нет — берём `latest` и фиксируем |
| Node | «любой» | `engines: node >= 24.9.0` — база образа `node:24-slim` |
| Адрес слушателя | «bind 0.0.0.0:3080» | `--profile web` слушает **loopback `:3080`**; наружу — реверс-прокси, которому отдаётся `--public-url` и `--trusted-host` |
| Прокси | «переписать Host и всё» | Прокси обязан: сохранить **browser-facing `Host`** (иначе `403` на все API), форвардить `Upgrade`/`Connection` (WebSocket), переписать `Path` cookie под монтирование и добавить `Secure`, отдать `/` → `/` (только `/` обменивает launch-token на cookie) |
| Аутентификация | «есть OIDC, как у Hermes» | **Своего OIDC нет**: вход = launch-token в напечатанном URL + подписанная сессионная cookie; учётка **одна** (права = владелец процесса) |
| MCP | «только плагины» | Есть официальный мост **`@deepseek-ai/dsh-mcp-client`** — «connects to MCP servers and registers their tools», транспорты `stdio` и `StreamableHTTP` |
| Скиллы | «скиллы = плагины» | Отдельный пакет **`@deepseek-ai/dsh-skill`** — «agent skill provider registry»: скиллы каталогом SKILL.md-файлов |
| Провайдеры моделей | «только DeepSeek official» | `llm-pi-ai.providers.<id>`: `apiKeyEnv`, `api: openai-completions`, `baseURL`, `models[]`; дефолтная модель — `agent-default-model` в `settings.yaml` |
| Песочница | «контейнер на задачу» | Пресеты процесса: `read-only` / `workspace-write` / `danger-full-access` (`permission.defaultPreset`); изоляция — процессная, не отдельный под |
| Образ | «есть официальный» | В Docker Hub и ghcr официального образа нет (ghcr на `deepseek-ai/dsh` отвечает `401`, Hub по «deepseek harness» — мимо) → **образ собираем сами** |

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Образ | **свой**: `ghcr.io/msklv/dsh:v0.2.2-rc.1` — `FROM node:24-slim` + `npm i -g @deepseek-ai/dsh@0.2.2-rc.1` (integrity пакета `sha512-ijR9UEVYkG15Q/Q79JzvzLBzQOQfc63VLr9n6flpwHPhr5IKn2UxthnSoto/P9l7qGd7pPvI1Ra6TW7LH3oKpg==`) | официального образа нет; пин по версии + пуш в ghcr, деплой по **дигесту** (прецедент — форк-образы (`ghcr.io/msklv/…`), снятые вместе с QM; правило «тег двигается, дигест нет» остаётся) |
| Namespace | `dsh` | паттерн «один ns на сервис» |
| Реплики | **1**, `strategy: Recreate` | состояние — каталог `/opt/data` на PVC; два писателя в один том не поддерживаются |
| Размещение | **приоритет — k8s-05** (`preferred`, вес 100), альтернатива k8s-01 | решение владельца; 05 без GPU и без шлюза, там же RAGFlow и Firecrawl — RAM-бюджет §5 `architecture/ARCHITECTURE.md` |
| Ресурсы | requests `250m/512Mi`, limits `1/2Gi` | веб-UI + Node-рантайм агента без локальных моделей; замер в W3 |
| Данные | PVC **5 Gi** `longhorn` (r=2), `mountPath: /opt/data` | сессии, память, скиллы, плагины профиля |
| Web | `dsh --profile web --public-url https://dsh.demo-ai-lab.ru/ --trusted-host dsh.demo-ai-lab.ru`, слушатель `127.0.0.1:3080` | штатный режим из `public-deployments`; порт наружу не публикуется, доступ — только из пода авторизации |
| SSO | **`oauth2-proxy` перед dsh**: Keycloak realm `dev`, клиент **`dsh`** (confidential), redirect `https://dsh.demo-ai-lab.ru/oauth2/callback`; upstream `http://dsh.dsh.svc:3080` | у dsh нет OIDC (§0); в Higress из OIDC-login нет ничего (установлены только `jwt-auth`, `key-auth`, `opa`, `ip-restriction`, ai-\* — 17.11), поэтому гейт делает прокси, а не шлюз |
| Публичность | снаружи — **только после приёмки гейта** (W7); до неё — LAN (`lan-only-ui`) | правило E6/ADR-0004: сначала LAN, потом край |
| Модели | локальная **`Qwen3.8-27B-UD`** через `api.`; внешняя **`deepseek-flash`** через `llm-svc.` (DLP + страж fail-closed) | §4 |
| MCP | мост `@deepseek-ai/dsh-mcp-client`; серверы стенда — `doc.`, `ysrch.`, `mon.`, `rag.` (после деплоя), `github-mcp` (после установки) | §6; набор инструментов общий с Hermes (ADR-0012) |
| Каталоги | **каталог MCP** — чтение `https://mcp.demo-ai-lab.ru/v0/servers`; **каталог скиллов** — GitHub-репо `msklv/skills-demo-ai-lab` по пину коммита | ADR-0005 (каталог), ADR-0010 (скиллы = отдельный репозиторий) |
| Песочница | `permission.defaultPreset: workspace-write`; `danger-full-access` **запрещён** | агент исполняет чужой текст; полный доступ = «шелл по HTTP» |

## 2. Предпосылки (проверить до W1)

| Что | Состояние | Проверка |
|---|---|---|
| Реестры при сборке | сборка образа требует доступа к npm-реестру и ghcr | сборочная машина/CI: `npm view @deepseek-ai/dsh@0.2.2-rc.1 version`; push в `ghcr.io/msklv/` |
| Node-версия | `engines >= 24.9.0` | `node --version` в образе ≥ 24.9 |
| Keycloak | клиент `dsh` **не заведён**; нужен confidential + redirect `/oauth2/callback` | §5, `scripts/keycloak_seed.py` |
| Внешняя модель | `llm-svc.` работает со статическим ключом; страж fail-closed | `POST /v1/chat/completions` → 200; без стража → `503 guard unavailable` |
| Локальная модель | `Qwen3.8-27B-UD` в GPUStack, резидентной не держим (ADR-0007) | в кейсе 06 карта занята стражем `Qwen3Guard-Gen-4B` ≈12,7 GiB → 27B только когда карта свободна |
| MCP-серверы | `doc.`, `ysrch.`, `mon.` живы; `rag.` — после `rag-spec` R1–R8; `github-mcp` — после раскатки §7.1 `hermes-spec` | вызов `initialize` по in-cluster DNS из пода `dsh` |
| Каталог скиллов | репозиторий `msklv/skills-demo-ai-lab` опубликован (ADR-0010) | `git ls-remote` + фиксация коммита в `values` |
| Узел 05 | 30,5 GiB allocatable, занято Firecrawl ≈5 GiB + Kuvasz/Postgres ≈1 GiB + RAGFlow (по `rag-spec`) | `kubectl describe node k8s-05` |

## 3. Секреты (`dsh.local.md`, gitignored)

| Ключ | Куда идёт |
|---|---|
| `oidc-client-secret` (клиент `dsh`) | Secret `dsh-oidc` |
| `cookie-secret` (32 байта, base64) | Secret `dsh-oidc` (oauth2-proxy), `openssl rand -base64 32` |
| `gpustack-api-key` (ключ `dsh`, allowed-models: `Qwen3.8-27B-UD`) | Secret `dsh-models` |
| `llm-svc-api-key` (статический ключ стенда, общий) | Secret `dsh-models` |
| `github-pat` (для `github-mcp`, если включён) | Secret `dsh-mcp` |
| `kuvasz-api-key` (`X-API-KEY` для `mon./mcp`) | Secret `dsh-mcp` |

Скрипт `scripts/dsh_secrets.sh` (по образцу `her_secrets.sh`) создаёт Secret'ы **до** первого синка.

## 4. Модели и конфигурация

Слои конфигурации dsh: патч профиля (`cordis.patch.yml`, статика деплоера) → `settings.yaml`
(то, что меняет пользователь в UI). Провайдеры — в `settings.yaml`, монтируется из ConfigMap.

```yaml
# settings.yaml (фрагмент; значения ключей — из env, см. Secret dsh-models)
agent-default-model:
  provider: llm-pi-ai
  model: deepseek-flash            # дефолт для демо — внешний маршрут через шлюз
llm-pi-ai:
  providers:
    gpustack:                       # локальная 27B (кейс 01, карта свободна)
      apiKeyEnv: GPUSTACK_API_KEY
      api: openai-completions
      baseURL: https://api.demo-ai-lab.ru/v1
      models: [{id: Qwen3.8-27B-UD}]
    llm-svc:                        # внешняя модель: DLP + страж fail-closed + лимиты
      apiKeyEnv: LLM_SVC_API_KEY
      api: openai-completions
      baseURL: https://llm-svc.demo-ai-lab.ru/v1
      models: [{id: deepseek-flash}]
permission:
  defaultPreset: workspace-write
```

| Роль | Модель | Маршрут | Ограничение |
|---|---|---|---|
| Дефолт | `deepseek-flash` (128K) | `llm-svc.` | страж `Qwen3Guard-Gen-4B` (≈12,7 GiB на 5070 Ti) должен быть поднят, иначе `503` |
| Локальная | `Qwen3.8-27B-UD` (128K) | `api.` / GPUStack | резидентной нет (ADR-0007): доступна, когда карта не занята стражем/генерацией |

## 5. SSO-гейт

`oauth2-proxy` в ns `dsh`, версия `v7.15.6` (quay.io, дигест снять при W1 и зафиксировать в манифесте):

| Параметр | Значение |
|---|---|
| `--provider` | `keycloak-oidc`, issuer `https://auth.demo-ai-lab.ru/realms/dev` |
| `--client-id` / secret | `dsh` / из Secret `dsh-oidc` |
| `--redirect-url` | `https://dsh.demo-ai-lab.ru/oauth2/callback` |
| `--upstream` | `http://dsh.dsh.svc:3080` (штатный listener dsh) |
| `--cookie-secret` | из Secret `dsh-oidc`; cookie `Secure`, `SameSite=Lax` |
| `--email-domain` | `*` (пул демо-учёток `demo01…`, как у остальных сервисов) |
| Порт | 4180; наружу не публикуется — Ingress ведёт на него |

Ingress: host `dsh.demo-ai-lab.ru`, `/` → `dsh-auth:4180`, TLS `Certificate dsh-demo-tls`
(`letsencrypt-http01`), до W7 — под `lan-only-ui`.

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

Правило ADR-0012: **MCP смотрят только внутрь** — все адреса in-cluster, внешних маршрутов у MCP нет.

Мост включается патчем профиля (статика, не UI):

```yaml
# cordis.patch.yml (фрагмент)
- insert:
    - id: mcp-client
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        servers:
          - {name: docling, url: 'http://docling.doc.svc:8000/mcp', transport: streamable-http}
          - {name: yandex-search, url: 'http://yandex-search.ysrch.svc:8766/mcp', transport: streamable-http}
          - {name: kuvasz, url: 'http://kuvasz.monitoring.svc:8080/mcp', transport: streamable-http,
             headers: {X-API-KEY: '${KUVASZ_MCP_KEY}'}}
```

**Каталоги:**

- **MCP-каталог** — чтение `GET https://mcp.demo-ai-lab.ru/v0/servers` (4 записи: docling, yandex-search,
  kuvasz, ragflow); агент получает список инструментов и ссылки, сами вызовы — по адресам выше.
  Второй реестр (плагин `dsh-mcp-registry` из npm) **не берём**: сторонний код в горячем пути агента.
- **Каталог скиллов** — репозиторий `msklv/skills-demo-ai-lab` (ADR-0010). Копируется в образ
  initContainer'ом `git clone` по **пину коммита** в `/opt/data/skills`; полный каталог не кладём — стартовый
  набор 3–5 скиллов (иначе системный промпт раздувается).

## 7. Состав каталога `gitops/apps/dsh/` и образ

| Файл | Что | sync-wave |
|---|---|---|
| `00-namespace.yaml` | Namespace `dsh` | −1 |
| `10-pvc.yaml` | PVC 5Gi Longhorn (`/opt/data`) | 0 |
| `20-config.yaml` | ConfigMap: `settings.yaml` (§4), `cordis.patch.yml` (§6) | 0 |
| `30-dsh.yaml` | Deployment `dsh` (образ по дигесту, `Recreate`), Service `dsh:3080` | 1 |
| `40-auth.yaml` | Deployment `dsh-auth` (oauth2-proxy) + Service `dsh-auth:4180`, `envFrom` Secret `dsh-oidc` | 1 |
| `50-ingress.yaml` | `Certificate dsh-demo-tls` + Ingress `/` → `dsh-auth:4180` (+ `lan-only-ui` до W7) | 2 |
| `image/Dockerfile` | `FROM node:24-slim`, `npm i -g @deepseek-ai/dsh@0.2.2-rc.1`, `USER node`, `WORKDIR /opt/data` | сборка |

Сборка: `docker build -t ghcr.io/msklv/dsh:v0.2.2-rc.1 gitops/apps/dsh/image` → `docker push` →
дигест из `docker inspect`/`skopeo inspect` в `30-dsh.yaml`. Обновление рантайма — новая версия пакета →
новый тег/дигест → синк Argo (обновление «на месте» запрещено: `/opt/hermes`-подобной самозаписи нет).

## 8. Фазы W1–W8 (каждая — приёмка командами)

| # | Что | Приёмка |
|---|---|---|
| **W1** | `scripts/dsh_secrets.sh`, каталог `gitops/apps/dsh/`, образ собран и запушен, пин по дигесту | Secret'ы на месте; `skopeo inspect docker://ghcr.io/msklv/dsh:v0.2.2-rc.1` → дигест в манифесте; Argo Synced |
| **W2** | PVC, ConfigMap (`settings.yaml`, `cordis.patch.yml`) | под `dsh` 1/1 Running; `dsh --profile web` слушает `127.0.0.1:3080` (лог старта печатает URL) |
| **W3** | web за прокси без SSO (внутренняя проверка) | `kubectl -n dsh port-forward svc/dsh 3080` → UI отдаёт документ; WebSocket `/api/ws` поднимается; замер `kubectl top` → ресурсы §1 уточнены |
| **W4** | модели (§4) | prompt в UI → ответ `deepseek-flash` через `llm-svc.` (в access-логе шлюза виден вызов, страж включён); переключение на `Qwen3.8-27B-UD` → ответ от `api.` |
| **W5** | MCP (§6) | в UI виден список инструментов моста; вызов `docling` (разбор PDF) и `web_search` (`ysrch.`) проходит; `kuvasz` — с `X-API-KEY` |
| **W6** | каталоги | агент читает `mcp./v0/servers` и показывает 4 записи; из каталога скиллов доступны 3–5 скиллов (список в UI/системном промпте) |
| **W7** | SSO-гейт и TLS | `curl -I https://dsh.demo-ai-lab.ru/` → 302 на `auth.demo-ai-lab.ru`; после входа `demo01` — 200; без cookie — `401/302`; `Certificate` Ready; через туннель до приёмки — `403` |
| **W8** | песочница и границы | `workspace-write`: запись вне `/opt/data` отклонена; `danger-full-access` недоступен из UI; `NetworkPolicy` — egress только к `api.`, `llm-svc.`, MCP-сервисам, `mcp.` |

## 9. Риски

| ID | Риск | Митигация |
|---|---|---|
| **R-W1** | Рантайм на **release-candidate** (`0.2.2-rc.1`, `next` уже `rc.3`) — API плагинов может разъехаться | фиксируем версию в образе; обновление — отдельным тегом после проверки W2–W5 |
| **R-W2** | dsh **single-identity**: SSO пускает людей, но внутри все работают под одной учёткой | ограничение рантайма, не гейта; на сцене проговариваем; на демо — один гость за раз |
| **R-W3** | Песочница процессная: агент видит ФС пода | `workspace-write` + PVC только `/opt/data` + `NetworkPolicy`; `danger-full-access` запрещён |
| **R-W4** | Внешняя модель уходит через `llm-svc.`, но 27B не влезает при поднятом страже | дефолт — `deepseek-flash`; локальную включаем только в кейсе 01 |
| **R-W5** | `Host`/WebSocket за прокси: любая правка `Host` → `403` на все API | прокси не переписывает `Host` (штатный `oauth2-proxy` upstream), проверка в W3/W7 |
| **R-W6** | RAM на 05: Firecrawl + Kuvasz + RAGFlow + dsh | `preferred`, а не `nodeSelector`; замер в W3, при нехватке — k8s-01 |

## 10. Открытые вопросы

| ID | Вопрос |
|---|---|
| **Q-W1** | Нужен ли `headless`-профиль (one-shot задачи) параллельно с web — или демо ограничивается UI |
| **Q-W2** | Оставляем ли доступ к `github-mcp` (PAT per-request) на сцене или только в artisan-режиме |
| **Q-W3** | Сколько скиллов в стартовом наборе (3 или 5) — зависит от объёма системного промпта |

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
| v1.0 | 2026-11-17 | спека создана: свой образ `ghcr.io/msklv/dsh:v0.2.2-rc.1` (node 24, пин по дигесту), один под + PVC `/opt/data`, SSO-гейт `oauth2-proxy` (Keycloak, клиент `dsh`), две модели (`Qwen3.8-27B-UD` через `api.`, `deepseek-flash` через `llm-svc.` со стражем и DLP), мост `@deepseek-ai/dsh-mcp-client` на 5 MCP-серверов, каталог MCP и каталог скиллов (GitHub-репо, пин коммита), песочница `workspace-write`, размещение — k8s-05 |
