# ADR-0001: Higress — единственный ingress-контроллер стенда

- Дата: 2026-10-12
- Статус: Accepted
- Ревизия: 2026-10-18 — привязка ingress решена: **пара k8s-02+k8s-03**, ingress-VIP `.230` (см. «Открытые вопросы» ниже; решение владельца). Контекст ниже — история на дату ADR, не меняется.
- Ревизия: 2026-10-18 (2) — уточнена атрибутировка требования по докам и чарту GPUStack 2.2.3: GPUStack **не** запрещает другие ingress-контроллеры в кластере; Higress обязателен только для собственных маршрутов GPUStack. «Единственный контроллер на весь стенд» — решение стенда (см. «Решение»).
- Ревизия: 2026-10-19 (3) — **способ установки решён: Higress standalone** (chart `higress.io/higress-core` **2.1.9** — тот же пин, что сабчарт GPUStack 2.2.3), установка в рамках `architecture/specs/k8s-install-spec.md` **F7/F8** (VIP `.230` + gateway на паре 02/03). Формулировка «через GPUStack-chart» в «Решении» снята: GPUStack ставится позже с `higress-core.enabled=false` + `gateway.ingressClassname=higress` — это документированный путь доков GPUStack (Installation via Helm → Limitations: «если ingress-контроллер уже установлен, отключите bundled sub-chart и укажите существующий»), ингресс перестаёт зависеть от выхода GPUStack. Версия стендового Higress пинится вручную = версии сабчарта GPUStack; bump GPUStack ⇒ сверка пина Higress.
- Ревизия: 2026-10-29 (4) — добавлено **сравнение Envoy Proxy / Higress / Bifrost**, оценка **agentgateway как единственного ingress** и отказ от **LiteLLM как второго LLM-гейтвея** (см. «Сравнение шлюзов», «agentgateway…», «LiteLLM рядом с Higress»). Решение не пересматривается: Bifrost, agentgateway и LiteLLM отклонены, Envoy остаётся data plane под Higress.

## Контекст

Демо делится на 3 части: (1) установка инфраструктуры «во главе с GPUStack»
(бекенды, рантаймы), (2) простые сервисы (Open WebUI, RAGFlow, Docling, Speakr),
(3) агентские сервисы. Кластер — kubeadm на k8s-02/03/04, NAT 80/443 на MikroTik
уже проброшен на k8s-02 (192.168.10.253) — узел, отведённый под ingress.

GPUStack ≥ 2.2 в k8s-режиме ставится официальным helm-чартом
(`oci://registry-1.docker.io/gpustack/gpustack-chart`) и включает собственный
in-cluster API-шлюз **Higress** (Envoy). Чарт позволяет отключить встроенный
Higress (`higress-core.enabled=false`), но тогда в кластере обязан быть **свой**
Higress — параметр `gateway.ingressClassname` принимает только Higress; Traefik/
NGINX в этой схеме не участвуют. Требования чарта: Kubernetes ≥ 1.30, default
StorageClass (Longhorn), Node Feature Discovery для GPU-нод.

## Решение

На стенде ставится **один** ingress-контроллер — **Higress**, **standalone** (ревизия 3):
чарт `higress.io/higress-core` **2.1.9** на паре k8s-02/03, вне установки GPUStack.
Версия зафиксирована: **GPUStack v2.2.3**, чарт
`oci://registry-1.docker.io/gpustack/gpustack-chart:2.2.3` (последний стабильный релиз
на 2026-10-18; 2.3.0 — только rc-пре-релизы). Версия higress-core пинится по версии
чарта GPUStack. Traefik/NGINX не
устанавливаются и не планируются. Это **решение стенда, а не ограничение
GPUStack**: соседство других ingress-контроллеров в кластере допустимо (чарт
прямо предусматривает `higress-core.enabled=false` при уже работающем контроллере),
но **свои маршруты** GPUStack обязан обслуживать Higress — сервер создаёт Ingress'ы
с аннотациями `higress.io/*` и CRD `networking.higress.io`/`extensions.higress.io`,
которые понимает только Higress. Один контроллер на весь стенд — наш выбор: один NAT
на :80/:443, единая точка роутинга и рубильник guard-маршрута. Все сервисы частей 2/3
публикуются роутами
Higress: `api.`, `openwebui.`, `ragflow.`, `docling.`, `speakr.`, `argo.`
на `*.demo-ai-lab.ru`. Higress слушает :80/:443 на ingress-VIP `192.168.10.230` (kube-vip LB-инстанс пары 02/03) —
один адрес и для LAN (split-DNS), и для внешнего пути (Cloudflare Tunnel).

## Последствия

Плюсы:
- Ингресс не зависит от GPUStack: поднимается вместе с кластером (F7/F8) и переживает
  переустановку/апгрейд GPUStack; один контроллер на весь стенд.
- Маршрутизация одна и та же из LAN и снаружи: split-DNS и Cloudflare Tunnel смотрят
  на ingress-VIP `.230`; проброс портов на узел не нужен.

Минусы и риски:
- helm-режим GPUStack и связка с Higress в официальной документации помечены
  **experimental** → обязательная сквозная репетиция установки до демо.
- Higress-конфиг (Ingress + Higress CRD) — новая для нас поверхность.

Открытые вопросы — закрыты ревизией 2026-10-19 (3):
- ~~режим слушания gateway на bare-metal без MetalLB~~ → `Service type=LoadBalancer` +
  kube-vip LB-инстанс (pool `.230`, статподы 02/03), `externalTrafficPolicy: Local` —
  `architecture/specs/k8s-install-spec.md` F7/F8;
- ~~pin higress-core и порядок обновления~~ → **2.1.9** (= сабчарт GPUStack 2.2.3);
  bump GPUStack ⇒ сверка/подъём пина Higress одним чек-листом.

Референсы: [GPUStack Installation via Helm](https://docs.gpustack.ai/2.2/installation/helm/).

## Альтернативы

- **Traefik + GPUStack standalone (вне k8s)** — GPUStack ставится скриптом на
  k8s-04, наружу через Traefik-роут. Отклонено: ломает связный рассказ «вся
  инфраструктура в k8s», два способа установки GPUStack, лишняя точка отказа.
- **Traefik + GPUStack-helm + отдельный Higress** — два контроллера претендуют на
  :80/:443 одной ноды. Отклонено: конфликт и лишняя сложность без выигрыша.
- **Bifrost (`maximhq/bifrost`) как шлюз стенда** — LLM/MCP-гейтвей; ingress-функций
  нет (не закрывает `*.demo-ai-lab.ru`, TLS, не-AI маршруты), AI-функции дублируются
  плагинами Higress, второй гейтвей = новая точка отказа. Отклонено (ревизия 4),
  разбор — «Сравнение шлюзов» ниже.
- **agentgateway (`agentgateway/agentgateway`) как единственный ingress** — замысел
  ровно тот (общий HTTP/gRPC + LLM/MCP/A2A в одном data plane), но на нашем стенде
  два жёстких блокера: не обслуживает классический `Ingress` (только Gateway API) и
  не обслужит маршруты GPUStack, который требует Higress. Отклонено (ревизия 4),
  постатейная оценка — «agentgateway как единственный ingress» ниже.
- **LiteLLM (`BerriAI/litellm`) как LLM-гейтвей рядом с Higress** — проксирование к
  внешнему провайдеру и виртуальные ключи/бюджеты уже закрываются Higress'ом, а
  LiteLLM добавляет второй data plane с БД в LLM-путь. Отклонено (ревизия 4),
  разбор — «LiteLLM рядом с Higress» ниже.

## Сравнение шлюзов: Envoy Proxy / Higress / Bifrost

Ревизия 4 (2026-10-29). Сравнение добавлено к контексту выбора, решение ADR не меняется.
Проверено по живым источникам на 2026-10-29: репозитории `envoyproxy/envoy`,
`higress-group/higress`, `maximhq/bifrost`, `agentgateway/agentgateway` (GitHub API),
маркетплейс плагинов Higress (higress.ai, 41 плагин / 5 категорий), список реализаций
Gateway API (gateway-api.sigs.k8s.io — Higress есть), доки `docs.getbifrost.ai` и
`agentgateway.dev` (разделы Kubernetes, Gateway API, миграция ingress-nginx, TLS,
guardrails, rate limits). Цифры производительности Bifrost — заявка вендора, нами
не измерялись.

**Класс и общая механика**

| Критерий | Envoy Proxy | Higress 2.1.9 | Bifrost (maximhq) |
|---|---|---|---|
| Класс продукта | L7-прокси / data plane, конфиг через xDS | ingress-контроллер + API/AI-гейтвей | LLM/MCP/agent-гейтвей (роутер провайдеров) |
| Стек | C++ ядро, xDS, v3 API | Envoy (data plane) + Go control plane на Istio; консоль | Go, один бинарник + web UI (React), helm-чарт |
| Лицензия | Apache-2.0 | Apache-2.0 | Apache-2.0 (часть фич — платный enterprise-тир) |
| K8s Ingress / Gateway API | сам по себе нет: нужен control plane (Envoy Gateway, Istio, Higress) | да: `ingressClass=higress`, реализация Gateway API, CRD `networking.higress.io`/`extensions.higress.io` | нет: ставится подом/бинарём за существующим ingress |
| Не-AI трафик (хосты, TLS, веб-приложения) | да, но конфиг руками/xDS | да — основная роль на стенде | нет: только LLM/MCP API (OpenAI-контракт) |
| Управление конфигом | xDS, YAML, без UI | Ingress + CRD + аннотации (git-friendly), Higress Console | `config.json` / REST API / Web UI, helm values |
| Наблюдаемость | stats/Prometheus, access log, OTel через фильтры | `ai-statistics`, Prometheus, лог шлюза | Prometheus, OTel-трейсы, LLM-логи и аналитика в UI |
| Расширения | native-фильтры, Lua, Wasm, `ext_proc`/`ext_authz` | Wasm (Rust/Go/TinyGo) + plugin-server, 41 плагин в маркетплейсе | Go-плагины (custom plugins — enterprise), остальное в OSS-ядре |

**AI-функции**

| Критерий | Envoy Proxy | Higress 2.1.9 | Bifrost (maximhq) |
|---|---|---|---|
| Единый API к провайдерам LLM | нет; нужен Agent Router (бывший Envoy AI Gateway, теперь Agentic AI Foundation) или свой `ext_proc` | `ai-proxy`: OpenAI-контракт, несколько провайдеров, конверсия протоколов | ядро продукта: 23+ провайдера, 10 000+ моделей, drop-in замена OpenAI/Anthropic API |
| Failover / балансировка | outlier detection, retry, LB-политики по кластерам; между провайдерами — только готовым фильтром | `ai-proxy` + retry/health-check, веса инстансов | failover между провайдерами и моделями, LB по ключам/провайдерам; adaptive LB — enterprise |
| Semantic cache | нет | `ai-cache` (семантический + строковый матч) | semantic caching |
| Governance: ключи, квоты, бюджеты | нет; `ext_authz`/OPA своими руками | `ai-token-ratelimit`, `ai-quota`, `key-auth`/JWT/OIDC/OPA, cluster rate limit (Redis) | virtual keys, бюджеты (team/customer), rate limit; OIDC-провижининг — enterprise |
| Guardrail / маскирование ПДн | нет (только `ext_proc`/Wasm своей сборки) | `ai-data-masking` (Wasm; выбрано в ADR-0006), `ai-security-guard` — облачный сервис, в закрытом контуре не годится | guardrails — enterprise-тир |
| MCP | нет; вынесено в отдельный проект (Agent Router / MCP-прокси) | `mcp-server` (REST→MCP), `mcp-proxy` по `remotes`, RBAC инструментов `allowTools` — используется (ADR-0005) | MCP gateway: stdio/ws/http/openapi-серверы, MCP Code Mode |
| Multi-tenancy / учёт токенов | нет | consumer + `ai-statistics` | consumer/virtual key + бюджеты, детальная аналитика стоимости |

**Вывод для стенда**

| | Envoy Proxy | Higress 2.1.9 | Bifrost (maximhq) |
|---|---|---|---|
| Роль на стенде | data plane внутри Higress; отдельно не ставится | **выбран** (ADR-0001): единственный ingress на VIP `.230`, AI-периметр (ADR-0005/0006) | **не берём** (ревизия 4) |
| Почему | без control plane не даёт ingress; AI-функции — писать фильтры | закрывает и ingress, и AI-плагины, и MCP в одной точке, конфиг в git | не ingress; AI-функции дублируются; второй гейтвей — лишняя точка отказа и второй набор ключей/политик |

**Когда пересматривать.** Bifrost возвращается в рассмотрение, если понадобится
multi-provider LLM-роутинг поверх GPUStack (внешние API, failover по провайдерам,
квоты/бюджеты по потребителям, drop-in SDK) и `ai-proxy` + `ai-quota` Higress этого
не покроют. Тогда — новый ADR с выбором «`ai-proxy` Higress vs отдельный Bifrost за
ingress»; место Bifrost — за Higress, не вместо него. Риски Bifrost на сегодня:
вендорский проект (Maxim AI) с платным enterprise-тиром, молодой (первый коммит
2025-03), очень высокий темп релизов (2.x), а HA-часть — adaptive LB, clustering,
guardrails — заявлена в enterprise-тире (failover и LB по ключам/провайдерам есть
в OSS-ядре).

## agentgateway как единственный ingress (оценка)

`agentgateway/agentgateway` — Apache-2.0, Rust: control plane + data plane, «AI-first»
прокси, который по замыслу закрывает и обычный HTTP/gRPC, и LLM/MCP/A2A в одном
data plane — то есть заменяет пару «обычный шлюз + AI-шлюз». Управление:
Linux Foundation с 2025, с 2026 — проект **Agentic AI Foundation (AAIF)**; репозиторий
создан 2025-03, ~5,8k★, текущая версия **v1.7.0** (2026-10-27). По докам проекта —
единственная реализация Gateway API, проходящая все conformance-тесты **v1.3**.

| Критерий | Что даёт agentgateway | Для стенда |
|---|---|---|
| Классический `networking.k8s.io/v1 Ingress` | **не обслуживает**: источник маршрутов — только Gateway API (`GatewayClass=agentgateway`, `HTTPRoute`/`GRPCRoute`/`TLSRoute`) + свои CRD `AgentgatewayBackend`/`AgentgatewayPolicy`; существующие Ingress'ы переносятся конвертером `ingress2gateway` (в доках — маппинг аннотаций ingress-nginx) | все наши маршруты (`api.`, `openwebui.`, `ragflow.`, `docling.`, `speakr.`, `argo.`, MCP) — Ingress'ы → переписывание всех манифестов на Gateway API |
| Маршруты GPUStack | GPUStack 2.2.3 создаёт Ingress с аннотациями `higress.io/*` и CRD Higress, `gateway.ingressClassname` принимает только Higress | **жёсткий блокер**: маршруты GPUStack agentgateway не обслужит, Higress всё равно остаётся в кластере |
| Gateway API conformance | заявлены все conformance-тесты v1.3; из фич не поддержаны session persistence (GEP-1619), multi-cluster (GEP-1748), retry budgets (GEP-3388), core backend mTLS (есть в расширении) | сильная сторона; для наших сервисов не критично |
| TLS / сертификаты | терминация на listener'ах Gateway, интеграция с cert-manager, TLSRoute/passthrough | паритет с Higress (LE wildcard переносится) |
| Guardrail / маскирование ПДн | regex-фильтры, OpenAI moderation, AWS Bedrock Guardrails, Google Model Armor, свой webhook (Guardrail Webhook API); **Wasm-плагинов нет** | наш `ai-qwen-guard` — Wasm-плагин (ADR-0006) → не переносится, переписывать в webhook-сервис вокруг Qwen3Guard; облачные модераторы в контуре не годятся |
| WAF | не заявлен | минус: у Higress есть ModSecurity + OWASP CRS на интернет-входе |
| LLM-роутинг и governance | OpenAI-совместимый фасад к провайдерам, budget/spend limits, virtual keys, token rate limits, LB и failover, prompt enrichment | сильнее `ai-proxy` Higress, но у нас один провайдер (GPUStack) — избыточно |
| MCP / A2A | федерация MCP-серверов, stdio/HTTP/SSE/streamable HTTP, OpenAPI→MCP, OAuth, per-tool RBAC, A2A | сильнее нашего контура, но MCP уже закрыт Higress + реестром (ADR-0005) |
| Inference routing | Gateway API Inference Extension: роутинг по GPU-утилизации, KV-cache, LoRA, очереди | дублирует планировщик GPUStack, на демо не нужно |
| Наблюдаемость / authN | OTel (метрики, логи, трейсы), JWT / API keys / OAuth, RBAC на CEL, rate limits | паритет |
| Режимы развёртывания | cluster-mode controller (Gateway API) и standalone (один бинарь + YAML, UI) | standalone-режим удобен, но нам нужен именно ingress-контроллер |
| Зрелость | 1.x, ~1,5 года истории, быстрые релизы, LF/AAIF-управление, ~5,8k★ | нейтрально-плюс, но для «единственного входа» молод |

**Итог.** Как **единственный ingress на текущем стенде — неприменим**: (1) не
обслуживает `Ingress`, а вся публикация сервисов у нас на Ingress'ах; (2) не обслужит
маршруты GPUStack, который требует Higress — значит Higress остаётся, и «единственный
контроллер» превращается в два. Отдельно: наш guardrail (Wasm, ADR-0006) не переносится,
WAF нет.

**Когда да.** Если стенд будет переезжать на Gateway API целиком и GPUStack перестанет
требовать Higress для своих маршрутов — agentgateway становится кандидатом №1 на роль
единственного входа: conformance v1.3, один data plane на обычный HTTP и на AI,
LLM-governance и MCP/A2A из коробки, управление в LF/AAIF. Тогда — новый ADR
(«Higress vs agentgateway как единственный ingress») с тестом миграции 6 маршрутов на
`HTTPRoute` и проверкой GPUStack-маршрутов. Ставить его **вторым** гейтвеем рядом с
Higress смысла нет: это дублирование MCP/LLM-функций и вторая точка отказа.

## LiteLLM рядом с Higress — не берём (ревизия 4)

`BerriAI/litellm` — не «лёгкий прокси», а полноценный LLM-гейтвей: MIT вне каталога
`enterprise/` (там коммерческая лицензия), ~62,3k★, версия **v1.106.6** (2026-10-28),
Python + **Postgres** (для virtual keys нужен `DATABASE_URL` + master key), официальный
helm-чарт в репо (`helm/litellm-helm`, с job'ом миграций Prisma). OSS-тир даёт
virtual keys, бюджеты и rate limits, spend tracking, Admin UI, load balancing,
guardrails, MCP gateway, 100+ провайдеров. Enterprise (ключ лицензии) — SSO/SCIM,
audit logs, org/team admins, **secret managers (Vault/AWS SM)**, IP allowlists,
per-team logging, multi-region, SLA.

| Что даёт LiteLLM | Вердикт для стенда |
|---|---|
| Прокси к внешнему провайдеру с сокрытием ключа | уже закрыто `ai-proxy` Higress |
| Маскирование ПДн / guard на Qwen3Guard | `ai-data-masking` + `ai-qwen-guard` (ADR-0006) на Higress; LiteLLM пришлось бы дублировать custom-webhook'ом |
| Virtual keys, бюджеты в деньгах, spend по ключу/команде, отчёты | **реально сильнее** `ai-token-ratelimit`/`ai-quota` — единственная фича, которой у нас нет |
| 100+ провайдеров, fallbacks между деплойментами | на демо один внешний провайдер → избыточно |
| Admin UI | плюс, но ценой второго компонента с БД |

**Почему не в дополнение к Higress.** (1) Второй data plane в LLM-пути:
`Higress → LiteLLM → провайдер`, guard и маскирование остаются на Higress → двойная
задержка на SSE-стримах и два конфига, которые надо держать согласованными.
(2) В OSS-тире безопасность не лучше Higress: Vault/AWS secret managers, SSO/SCIM и
audit logs — **Enterprise**, в OSS ключи провайдеров в `config.yaml`/env и master key;
Keycloak к его админке штатно не подключается — всё равно фронтить Higress'ом с `oidc`.
(3) Второй stateful-компонент: Postgres, миграции Prisma, master key, свой бэкап — на
стенде, где уже 4 компонента данных (Longhorn, PG Langfuse, ClickHouse, SeaweedFS).
(4) Темп релизов: 1 542 релиза, ломающие изменения — нужен пин и сопровождение.
(5) Логи промптов: LiteLLM умеет писать запросы/ответы в колбэки (Langfuse/S3 и др.) —
для ПДн это риск, который надо явно гасить (у нас трейсы идут из приложений в Langfuse).
(6) Проблему канала не решает: egress к внешнему провайдеру — это R1/E7, а не шлюз.

**Что проверено на стенде (2026-10-29).** В `higress-system` стоят AI-плагины поставки
GPUStack (`gpustack-ai-proxy 2.0.0-patched`, `ai-statistics 2.0.0`, `llm-ext-auth 2.0.0`,
`model-mapper`/`model-router`/`token-usage`), а маркетплейсных `ai-data-masking` и
`ai-token-ratelimit` нет. Значит для маршрута к внешнему провайдеру нужен **свой**
`WasmPlugin` (не правка `gpustack-*`, иначе снесётся апгрейдом GPUStack) + плагины
маскирования/лимитов; ключ — из приватного хранилища, не из git.

**Когда пересматривать.** Если понадобится governance, а не проксирование: несколько
внешних провайдеров, раздача ключей командам/сервисам, **бюджеты в деньгах и отчёты
spend**, единая точка «on-prem GPUStack + внешние модели» для агентов. Тогда — новый
ADR, и место LiteLLM **строго за Higress**: Higress = ingress, TLS, WAF, маскирование,
guard, egress-контроль; LiteLLM = ключи, бюджеты, spend, роутинг провайдеров.