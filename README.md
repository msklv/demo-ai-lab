# demo-ai-lab — демонстрационный AI Lab

Публичный стенд **demo-ai-lab.ru**: on-prem LLM-инференс, RAG, транскрибация и ИИ-агенты
на собственном Kubernetes-кластере из четырёх мини-ПК. Принцип утилитарности:
**локальная обработка предпочтительна** — наружу уходит только то, что не представляет ценности.

## Документация

| Файл | Что это |
|---|---|
| `architecture/README.md` | обзор каталога: рендеры диаграмм (C1, C2, полная схема) + индекс спек |
| `architecture/ARCHITECTURE.md` | архитектура C2, размещение сервисов по узлам, статус строительства (§7) |
| `architecture/specs/` | спецификации: установка кластера, внешний доступ, SSO и сервисы шагов 1–3 (по файлу на сервис, буквы фаз F/E/K/G/O/S/D/Y/M/L) |
| `architecture/specs/k8s-install-spec.md` | спека установки кластера: kubeadm → Cilium → Longhorn → NFD → cert-manager → Argo CD → ingress-VIP `.230` + Higress (F0–F10) — грабли и приёмка каждой фазы |
| `architecture/specs/external-access-spec.md` | внешний доступ: Cloudflare Tunnel, split-DNS, TLS Full strict; приёмка E1–E5, E7 (второй egress — коннектор на внешней VM + SSH-hop); E6 снят 2026-10-24: служебные — только LAN |
| `architecture/specs/keycloak-spec.md` | SSO: Keycloak 26.8.1 ×2 + PostgreSQL 17.11 на паре k8s-02/03 через Argo CD, `auth.demo-ai-lab.ru`, realm `dev`, пользователи `user-test`/`admin-test`; приёмка K1–K7 (креды — в `*.local.md`, не в git) |
| `architecture/endpoints.md` | все публичные адреса сервисов короткими именами (`owu`, `rag`, `doc`, `spk`, `qm`, `her`, `api`, `auth`) + кто за SSO |
| `architecture/specs/mcp-registry-spec.md` | каталог MCP-серверов (`mcp.demo-ai-lab.ru`): MCP Registry **1.8.6** + PostgreSQL 16 на паре k8s-02/03, **встроенная витрина на `/`**, публикация через доменную проверку, приёмка M1–M8 (спека v2.0, **не установлено**) |
| `architecture/specs/gpustack-spec.md` | GPUStack 2.2.3 (шаг 1 демо): helm-чарт, GPU-воркер на k8s-04, раннер vLLM, модели AWQ, `api.demo-ai-lab.ru`; приёмка G0–G8 (креды — `gpustack-admin.local.md`, не в git) |
| `architecture/specs/owu-spec.md` | Open WebUI (`owu.demo-ai-lab.ru`): чарт 17.0.0/образ 0.12.0, OIDC через Keycloak, ключ GPUStack, пробы/ресурсы; приёмка O1–O6 (развёрнуто 2026-10-28 через Argo, приёмка не снята) |
| `architecture/specs/spk-spec.md` | Speakr (`spk.demo-ai-lab.ru`): plain-манифесты, образ `0.10.16-alpha-lite`, ASR через GPUStack `openai_whisper`, SSO; приёмка S1–S6 (развёрнуто 2026-10-28 через Argo, приёмка не снята) |
| `architecture/specs/doc-spec.md` | Docling Serve + **MCP** (`doc.demo-ai-lab.ru`, MCP на `/mcp`): образ `-cpu` v1.38.2, OCR на CPU с русским (`eslav`/`rus`), второй контейнер `docling-mcp` в `remote`-режиме, кэш моделей Job-хуком; приёмка D1–D6 (развёрнуто 2026-10-28 через Argo, приёмка не снята) |
| `architecture/specs/ysearch-spec.md` | Yandex Search MCP (`ysrch.demo-ai-lab.ru`): форк `msklv/yandex-search-mcp-server` v1.3.1, StreamableHTTP `/mcp`, TCP-пробы, ConfigMap против `421 Invalid host`, ключ Search API в Secret; приёмка Y1–Y5 (развёрнут и опубликован в каталоге 2026-10-28) |
| `architecture/specs/langfuse-spec.md` | Langfuse (`lng.demo-ai-lab.ru`, шаг 2): чарт `langfuse` 2.1.7 / образ 4.70.1, свой ClickHouse 26.4 без оператора, PostgreSQL 18 + Valkey 8 + SeaweedFS, SSO Keycloak нативным OIDC-провайдером (без EE-лицензии), bootstrap через `LANGFUSE_INIT_*`; приёмка L1–L7 (спека, **не установлено**) |
| `architecture/hardware-inventory.md` | инвентарь железа: диски и износ (SMART), прошивки, TBW — снимки по датам |
| `network-map-detail.md` | живая карта сети стенда |
| `mikrotik-setup.md` | рецепт настройки MikroTik (для повторения стенда) |
| `adr/` | реестр ключевых архитектурных решений (Higress, дисковая модель, три control-plane, внешний доступ + VM-egress, MCP: реестр и Higress) |
| `references/` | операционные runbook'и: status-audit (health sweep), demo-plan, storage-model, gpu-scheduling-options, service-spec-authoring, keycloak-sso |
| `IDEAS.md` | принцип стенда + реестр идей для реализации (1–2 предложения на идею) |
| `AGENTS.md` | правила работы с репозиторием (что публикуем, что нет) |

### Операционное

| Что | Где | Зачем |
|---|---|---|
| Проверка кластера | `scripts/k8s_health.py` (`--brief`, `--json`) | один прогон: API/VIP, ноды и pressure, поды, etcd, control-plane/kube-vip, Argo/Longhorn/Higress, SSH-замер, origin в LAN (`scripts/README.md`) |
| Проверка обвязки | `scripts/env_health.py` (`--brief`, `--json`, `--no-vm`, `--no-check-host`) | внешняя VM-egress (cloudflared/haproxy/hop-и), Cloudflare-туннель через API, внешний путь с подтверждением check-host (`scripts/README.md`) |
| Подготовка нод и кластера | `ansible/` — `site-cluster.yml`, `site-gpu.yml`, `pb-*.yaml`, `values-*.yaml` | детерминированная установка: containerd, p2p, kubeadm-пакеты, два kube-vip (`.240` API / `.230` ingress), GPU-драйвер (`ansible/README.md`) |
| GitOps | `gitops/` — app-of-apps + ApplicationSet | деплой = git push, статус по живым подам (`gitops/README.md`) |

## Исходная точка демо

К началу выступления на стенде **уже развёрнуто и проверено** (это не часть демо):

| Слой | Что стоит | Где зафиксировано |
|---|---|---|
| Железо | 4× GMKtec (Ubuntu 24.04.4) — **подготовлены (F0 2026-10-17)**: containerd 2.2.1 + CRI, swap off на всех; LV Longhorn 250G на 02/03/04 (k8s-01 вне пула); NVMe 477G на всех | `architecture/ARCHITECTURE.md` §2.3, ADR-0002 |
| Кластер | kubeadm 1.35.9 (пин спеки §3), CNI Cilium; роли (ADR-0003): **k8s-01/02/03 — control-plane ×3** (компьют на 01, GitOps на 02, **ingress — пара 02/03 на VIP `.230`**, лёгкие сервисы на 03), k8s-04 — LLM-инференс **и** data-heavy сервисы (без taint'а; nodeSelector + priorityClass); Metrics API — metrics-server 3.14.0 (F10) | `architecture/ARCHITECTURE.md` §5, ADR-0003 |
| Хранилище | **Longhorn**: default StorageClass, replica=2, анти-аффинити; пул LV 250G на 02/03/04, k8s-01 вне пула (износ диска); данные сервисов — PVC, модели — hostPath на k8s-04 | ADR-0002, ADR-0003 |
| Ingress | **Higress** — единственный контроллер; standalone (`higress-core` 2.1.9) на паре k8s-02/03, ingress-VIP `.230`; внешний путь — Cloudflare Tunnel, плюс с 2026-10-28 включён прямой проброс WAN 80/443 → `.230` (работает из uplink-сети, снаружи пока не проброшен аплинком площадки) | ADR-0001 (рев. 3), спека F7/F8, `mikrotik-setup.md` §3.6 |
| Сеть | MikroTik `gw-demo-ai-lab`, LAN `192.168.10.0/24`, LAG до коммутатора, Wi-Fi для аудитории | `network-map-detail.md`, `mikrotik-setup.md` |
| Доступ | снаружи — Cloudflare Tunnel (ADR-0004); TLS Full strict: edge (Universal SSL) + origin LE wildcard (cert-manager DNS-01, ADR-0004 ревизия); LAN — split-DNS → `.230`, тот же https; наружу публикуются демо-сервисы шагов 1–3 **и админки** — Argo CD (`argo.`) и консоль Higress (`hgc.`), оба по решению 2026-10-28 (E9); Longhorn — только LAN | `architecture/ARCHITECTURE.md` §6, ADR-0004, `architecture/specs/external-access-spec.md` E8/E9 |
| Смоук-маршрут | `echo.demo-ai-lab.ru` — постоянный тестовый контейнер: проверка LAN- и внешнего пути в любой момент | спека F8, external-access E5 |
| Подготовка сцены | образы и веса прогреты на узлах прямым pull с ноды (склада предзагрузки нет); база RAGFlow проиндексирована заранее | — |

Статус на 2026-10-28: **GPUStack установлен** (`architecture/specs/gpustack-spec.md`, G0–G7 закрыты,
G8 — приёмка/репетиция), демо-сервисы шага 2 (`architecture/specs/owu-spec.md`, `architecture/specs/spk-spec.md`, `architecture/specs/doc-spec.md`) и каталог
MCP-серверов (`architecture/specs/mcp-registry-spec.md`) **развёрнуты 2026-10-28** (owu/spk/doc — Argo, каталог — `kubectl`
+ adoption в Argo), Yandex Search MCP (`architecture/specs/ysearch-spec.md`) развёрнут 2026-10-28; в каталоге опубликованы
`ru.demo-ai-lab/docling@1.0.0` и `ru.demo-ai-lab/yandex-search@1.0.0`; агенты шага 3 — план. Установка шага 2 идёт через Argo из
`gitops/apps/*`. SSO (Keycloak, `auth.demo-ai-lab.ru`) — по спеке
`architecture/specs/keycloak-spec.md`, **установлен 2026-10-27 через Argo CD** (K1–K7 закрыты)
вход через SSO.

## Три шага демо

### Шаг 1 — Инфраструктура во главе с GPUStack

- Установка GPUStack **v2.2.3** helm-чартом `gpustack-chart:2.2.3` (Higress в этот чарт
  не входит — он уже стоит вместе с кластером, F7/F8): server
  (StatefulSet, данные в Longhorn) + worker на LLM-ноде k8s-04;
- Бекенд — **только поддерживаемый GPUStack**: vLLM-раннер `gpustack/runner:cuda13.0-vllm0.25.1`
  из каталога образа-селектора (driver 595 → CUDA 13.x; GPUStack подставляет раннер сам по
  детекту железа, вручную не подменяем). Другие бэкенды не ставим — только раннеры каталога
  GPUStack 2.2.3 (решение 2026-10-23);
- Инференс — на **GPU k8s-04 (RTX 5060 Ti 16G, driver 595-open)**; в k8s-инсталляции LLM
  исполняется только через GPUStack (решение 2026-10-18), хостовый BeeLlama-прогон остаётся
  примером вне кластера;
- Модели по **ADR-0007** (safetensors): резидентно чат `gemma-4-12B-it-qat-w4a16-ct` (9.59 GiB,
  util 0.68–0.75) + ASR `whisper-large-v3-turbo` (1.51 GiB, 0.15); эмбеддинги `bge-m3`, реранк и
  страж `Qwen3Guard-Gen-0.6B` — на 780M (ADR-0006/0007); резервной модели в наборе нет;
- guardrail (**ADR-0006**, решение 2026-10-24): **Higress + `ai-data-masking` + Qwen3Guard-Gen-0.6B** —
  guard-маршрут, маскирование ПДн на шлюзе со `restore` в ответе и модель-страж на GPUStack
  (`Safe/Controversial/Unsafe`, категории `PII` и `Jailbreak`) через кастомный Wasm-плагин
  `ai-qwen-guard`; рубильник — аннотация Ingress. Все части — Apache-2.0, работают без интернета;
  облачные модераторы и класс `guardrails-ai` отклонены — `adr/adr-0006-guardrail-higress-qwen3guard.md`;
- **Результат:** OpenAI-совместимый API `api.demo-ai-lab.ru` — единая точка инференса
  для всех сервисов стенда.

### Шаг 2 — Простые сервисы

| Сервис | Назначение | Адрес (короткое имя) |
|---|---|---|
| Open WebUI | чат-UI к моделям GPUStack | `owu.` (SSO) |
| RAGFlow | RAG: на сцене индексируется свежий документ, затем QA по базе | `rag.` (SSO) |
| Docling | OCR и разбор документов (REST + **MCP-сервер** для агентов, `/mcp`), **без авторизации** — решение 2026-10-24, публичный маршрут | `doc.` |
| Speakr | транскрибация аудио (whisper) | `spk.` (SSO) |
| **Langfuse** | LLM-наблюдаемость: трейсы вызовов моделей (промпт/ответ/задержка/токены), промпты, оценки; свой стек PG + Valkey + ClickHouse + SeaweedFS | `lng.` (SSO) |
| Yandex Search MCP | веб-поиск для агентов: `web_search`, `gen_search`, `image_search` (MCP на `/mcp`), ключ Yandex Search API — в Secret | `ysrch.` |
| **MCP Registry** | каталог MCP-серверов стенда: витрина на `/`, API `/v0` — человек смотрит список, клиенты и агенты берут из него `remotes` серверов; в каталоге уже опубликован `ru.demo-ai-lab/docling` | `mcp.` |

Все роуты — через Higress на `*.demo-ai-lab.ru`, данные — в Longhorn, LLM — только GPUStack.
Полный список адресов и соответствие «хост ↔ клиент Keycloak» — `architecture/endpoints.md`.
Спеки: `architecture/specs/owu-spec.md`, `architecture/specs/spk-spec.md`, `architecture/specs/doc-spec.md`,
`architecture/specs/mcp-registry-spec.md`, `architecture/specs/langfuse-spec.md` (`rag` отдельной спекой не оформлен:
RAGFlow ждёт эмбеддинги/реранк на 780M и RAM на k8s-03).
Деплой каталога и порядок приёмки — `gitops/infra-apps/mcp-registry/README.md` (манифесты 10/20/30 +
`scripts/mcp_registry_secrets.sh`); **установлен 2026-10-28** (`kubectl`, ns `mcp-registry`: 2/2 пода,
`/v0/health` 200, витрина и `/docs` 200, серт LE Ready; Argo-приложение — после push манифестов) —
детали в `architecture/ARCHITECTURE.md` §7 п.12.

### Шаг 3 — Агентские сервисы

- **qm** — мультиагентный рантайм (`qm.`, SSO) + вынесенные Hermes-рантаймы (`her.`, SSO); каталог
  MCP-серверов (`mcp.`) показан в шаге 2 — здесь агент берёт из него `remotes` и вызывает серверы;
- все LLM-вызовы агентов — через GPUStack (tool-calling), состояние — PostgreSQL;
  инструменты разбора документов агенты получают **нативным MCP-сервером Docling** (`doc./mcp`,
  `architecture/specs/doc-spec.md`), остальной MCP-хостинг — `mcp-server` Higress (ADR-0005);
- трассировка LLM-вызовов — **Langfuse шага 2** (`lng.`, `architecture/specs/langfuse-spec.md`): агент шага 3
  пишет трейсы в тот же инстанс, отдельного трейсинг-стека в шаге 3 нет;
- **демо:** агент выполняет задачу, вызывая сервисы стенда через MCP (RAGFlow / Docling /
  Open WebUI), каждый вызов модели виден в трассах;
- **демо guardrail (ADR-0006):** в RAGFlow грузится документ с prompt-injection, а в запрос — ПДн →
  запрос идёт через guard-маршрут → `ai-data-masking` маскирует телефон/почту (и возвращает их в
  ответе), `ai-qwen-guard` спрашивает Qwen3Guard-Gen-0.6B и блокирует по `Unsafe`/`Jailbreak`,
  событие — в логе Higress; снятие аннотации — инъекция проходит (контраст «без guardrail агент ведётся»).

---

Текущее состояние стенда — `architecture/ARCHITECTURE.md` §7 (единственный источник статуса:
что закрыто, что открыто); живая проверка — `python3 scripts/k8s_health.py`. Репозиторий
публичный; публикуются только нечувствительные данные (секреты, MAC-адреса и адреса uplink —
вне репозитория).
