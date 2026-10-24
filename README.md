# demo-ai-lab — демонстрационный AI Lab

Публичный стенд **demo-ai-lab.ru**: on-prem LLM-инференс, RAG, транскрибация и ИИ-агенты
на собственном Kubernetes-кластере из четырёх мини-ПК. Принцип утилитарности:
**локальная обработка предпочтительна** — наружу уходит только то, что не представляет ценности.

## Документация

| Файл | Что это |
|---|---|
| `architecture/ARCHITECTURE.md` | архитектура C2, размещение сервисов по узлам, статус строительства (§7) |
| `architecture/k8s-install-spec.md` | спека установки кластера: kubeadm → Cilium → Longhorn → NFD → cert-manager → Argo CD → ingress-VIP `.230` + Higress (F0–F10) — грабли и приёмка каждой фазы |
| `architecture/external-access-spec.md` | внешний доступ: Cloudflare Tunnel, split-DNS, TLS Full strict; приёмка E1–E5 (E6 снят 2026-10-24: служебные — только LAN) |
| `architecture/keycloak-spec.md` | SSO: Keycloak 26.8.1 + PostgreSQL на k8s-04 через Argo CD, `auth.demo-ai-lab.ru`, realm `dev`, пользователи `user-test`/`admin-test`; приёмка K1–K7 (креды — в `*.local.md`, не в git) |
| `architecture/hardware-inventory.md` | инвентарь железа: диски и износ (SMART), прошивки, TBW — снимки по датам |
| `network-map-detail.md` | живая карта сети стенда |
| `mikrotik-setup.md` | рецепт настройки MikroTik (для повторения стенда) |
| `adr/` | реестр ключевых архитектурных решений (Higress, дисковая модель, три control-plane, внешний доступ) |
| `IDEAS.md` | принцип стенда + реестр идей для реализации (1–2 предложения на идею) |
| `AGENTS.md` | правила работы с репозиторием (что публикуем, что нет) |

### Операционное

| Что | Где | Зачем |
|---|---|---|
| Проверка состояния стенда | `scripts/k8s_health.py` (`--brief`, `--json`, `--tunnel`) | один прогон: API/VIP, ноды и pressure, поды, etcd, control-plane/kube-vip, Argo/Longhorn/Higress, SSH-замер, внешний путь (`scripts/README.md`) |
| Подготовка нод и кластера | `ansible/` — `site-cluster.yml`, `site-gpu.yml`, `pb-*.yaml`, `values-*.yaml` | детерминированная установка: containerd, p2p, kubeadm-пакеты, два kube-vip (`.240` API / `.230` ingress), GPU-драйвер (`ansible/README.md`) |
| GitOps | `gitops/` — app-of-apps + ApplicationSet | деплой = git push, статус по живым подам (`gitops/README.md`) |
| Локальный реестр образов | `preload-registry/` — `registry:2` на `192.168.10.188:5050` | предзагрузка образов, чтобы ноды не тянули из интернета (`preload-registry/README.md`) |

## Исходная точка демо

К началу выступления на стенде **уже развёрнуто и проверено** (это не часть демо):

| Слой | Что стоит | Где зафиксировано |
|---|---|---|
| Железо | 4× GMKtec (Ubuntu 24.04.4) — **подготовлены (F0 2026-10-17)**: containerd 2.2.1 + CRI, swap off на всех; LV Longhorn 250G на 02/03/04 (k8s-01 вне пула); NVMe 477G на всех | `ARCHITECTURE.md` §2.3, ADR-0002 |
| Кластер | kubeadm 1.35.9 (пин спеки §3), CNI Cilium; роли (ADR-0003): **k8s-01/02/03 — control-plane ×3** (компьют на 01, GitOps на 02, **ingress — пара 02/03 на VIP `.230`**, лёгкие сервисы на 03), k8s-04 — LLM-инференс **и** data-heavy сервисы (без taint'а; nodeSelector + priorityClass); Metrics API — metrics-server 3.14.0 (F10) | `ARCHITECTURE.md` §5, ADR-0003 |
| Хранилище | **Longhorn**: default StorageClass, replica=2, анти-аффинити; пул LV 250G на 02/03/04, k8s-01 вне пула (износ диска); данные сервисов — PVC, модели — hostPath на k8s-04 | ADR-0002, ADR-0003 |
| Ingress | **Higress** — единственный контроллер; ставится standalone (`higress-core` 2.1.9) на паре k8s-02/03, ingress-VIP `.230` (проброс WAN 80/443 отключён; внешний путь — Cloudflare Tunnel) | ADR-0001 (рев. 3), спека F7/F8 |
| Сеть | MikroTik `gw-demo-ai-lab`, LAN `192.168.10.0/24`, LAG до коммутатора, Wi-Fi для аудитории | `network-map-detail.md`, `mikrotik-setup.md` |
| Доступ | снаружи — Cloudflare Tunnel (ADR-0004); TLS Full strict: edge (Universal SSL) + origin LE wildcard (cert-manager DNS-01, ADR-0004 ревизия); LAN — split-DNS → `.230`, тот же https; служебные хостнеймы (`argocd.*` и пр.) — только LAN, наружу не публикуются | `ARCHITECTURE.md` §6, ADR-0004 |
| Смоук-маршрут | `echo.demo-ai-lab.ru` — постоянный тестовый контейнер: проверка LAN- и внешнего пути в любой момент | спека F8, external-access E5 |
| Подготовка сцены | образы pre-pull на узлы; модели в кэше k8s-04; база RAGFlow проиндексирована заранее | — |

На стенде до демо **не установлено**: GPUStack, сервисы шага 2 и агенты шага 3 — их
разворачивают прямо во время выступления. SSO (Keycloak, `auth.demo-ai-lab.ru`) — по спеке
`architecture/keycloak-spec.md`, ставится в кластер через Argo CD до демо, если решаем показывать
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
- Модели из кэша (safetensors): **qwen3-14b/8b AWQ 4-bit** (10.0 и 6.1 ГБ весов —
  обе влезают в 16 ГБ VRAM, tool-calling) + **bge-m3** (эмбеддинги, 2.27 ГБ);
- guardrail-подготовка: **guard-маршрут** на Higress — Wasm-плагин `ai-security-guard`,
  рубильник — аннотация Ingress. Модельный бэкенд модерации **отложен**: классификатор
  Prompt Guard 2 не относится к поддерживаемым типам моделей GPUStack (LLM/эмбеддинги/реранкер),
  CPU-раннера в каталоге 2.2.x нет — вернуться при подтверждённом пути;
- **Результат:** OpenAI-совместимый API `api.demo-ai-lab.ru` — единая точка инференса
  для всех сервисов стенда.

### Шаг 2 — Простые сервисы

| Сервис | Назначение | Адрес |
|---|---|---|
| Open WebUI | чат-UI к моделям GPUStack | `openwebui.` |
| RAGFlow | RAG: на сцене индексируется свежий документ, затем QA по базе | `ragflow.` |
| Docling | OCR и разбор документов (API для RAGFlow/агентов) | `docling.` |
| Speakr | транскрибация аудио (whisper) | `speakr.` |

Все роуты — через Higress на `*.demo-ai-lab.ru`, данные — в Longhorn, LLM — только GPUStack.

### Шаг 3 — Агентские сервисы

- **qm** — мультиагентный рантайм + вынесенные Hermes-рантаймы + каталог MCP-серверов;
- все LLM-вызовы агентов — через GPUStack (tool-calling: qwen3), состояние — PostgreSQL;
- трассировка LLM-вызовов (Langfuse) — опционально, если остаётся RAM;
- **демо:** агент выполняет задачу, вызывая сервисы стенда через MCP (RAGFlow / Docling /
  Open WebUI), каждый вызов модели виден в трассах;
- **демо guardrail (сценарий сохраняем, модельный бэкенд отложен 2026-10-23):** в RAGFlow
  грузится документ с prompt-injection → запрос идёт через guard-маршрут → классификатор блокирует,
  событие в логах Higress; снятие аннотации — инъекция проходит (контраст «без guardrail агент
  ведётся»). Пока классификатор не подтверждён на поддерживаемом раннере, показывать нечего.

---

Текущее состояние стенда — `architecture/ARCHITECTURE.md` §7 (единственный источник статуса:
что закрыто, что открыто); живая проверка — `python3 scripts/k8s_health.py`. Репозиторий
публичный; публикуются только нечувствительные данные (секреты, MAC-адреса и адреса uplink —
вне репозитория).
