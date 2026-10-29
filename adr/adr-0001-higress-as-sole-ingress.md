# ADR-0001: Higress — единственный ingress-контроллер стенда

- Дата: 2026-10-12
- Статус: Accepted
- Ревизия: 2026-10-18 — привязка ingress решена: **пара k8s-02+k8s-03**, ingress-VIP `.230` (см. «Открытые вопросы» ниже; решение владельца). Контекст ниже — история на дату ADR, не меняется.
- Ревизия: 2026-10-18 (2) — уточнена атрибутировка требования по докам и чарту GPUStack 2.2.3: GPUStack **не** запрещает другие ingress-контроллеры в кластере; Higress обязателен только для собственных маршрутов GPUStack. «Единственный контроллер на весь стенд» — решение стенда (см. «Решение»).
- Ревизия: 2026-10-19 (3) — **способ установки решён: Higress standalone** (chart `higress.io/higress-core` **2.1.9** — тот же пин, что сабчарт GPUStack 2.2.3), установка в рамках `k8s-install-spec.md` **F7/F8** (VIP `.230` + gateway на паре 02/03). Формулировка «через GPUStack-chart» в «Решении» снята: GPUStack ставится позже с `higress-core.enabled=false` + `gateway.ingressClassname=higress` — это документированный путь доков GPUStack (Installation via Helm → Limitations: «если ingress-контроллер уже установлен, отключите bundled sub-chart и укажите существующий»), ингресс перестаёт зависеть от выхода GPUStack. Версия стендового Higress пинится вручную = версии сабчарта GPUStack; bump GPUStack ⇒ сверка пина Higress.
- Ревизия: 2026-10-29 (4) — добавлено **сравнение Envoy Proxy / Higress / Bifrost** (см. «Сравнение шлюзов»). Решение не пересматривается: Bifrost отклонён как замена ingress, Envoy остаётся data plane под Higress.

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
  `k8s-install-spec.md` F7/F8;
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

## Сравнение шлюзов: Envoy Proxy / Higress / Bifrost

Ревизия 4 (2026-10-29). Сравнение добавлено к контексту выбора, решение ADR не меняется.
Проверено по живым источникам на 2026-10-29: репозитории `envoyproxy/envoy`,
`higress-group/higress`, `maximhq/bifrost` (GitHub API), маркетплейс плагинов Higress
(higress.ai, 41 плагин / 5 категорий), список реализаций Gateway API
(gateway-api.sigs.k8s.io — Higress есть), доки `docs.getbifrost.ai`. Цифры
производительности Bifrost — заявка вендора, нами не измерялись.

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