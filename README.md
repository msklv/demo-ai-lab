# demo-ai-lab — демонстрационный AI Lab

Публичный стенд **demo-ai-lab.ru**: on-prem LLM-инференс, RAG, транскрибация и ИИ-агенты
на собственном Kubernetes-кластере из четырёх мини-ПК. Принцип утилитарности:
**локальная обработка предпочтительна** — наружу уходит только то, что не представляет ценности.

## Документация

| Файл | Что это |
|---|---|
| `architecture/ARCHITECTURE.md` | архитектура C2, размещение сервисов по узлам, статус строительства (§7) |
| `network-map-detail.md` | живая карта сети стенда |
| `mikrotik-setup.md` | рецепт настройки MikroTik (для повторения стенда) |
| `adr/` | реестр ключевых архитектурных решений (Higress, дисковая модель, три control-plane) |
| `AGENTS.md` | правила работы с репозиторием (что публикуем, что нет) |

## Исходная точка демо

К началу выступления на стенде **уже развёрнуто и проверено** (это не часть демо):

| Слой | Что стоит | Где зафиксировано |
|---|---|---|
| Железо | 4× GMKtec (Ubuntu 24.04.4) — **подготовлены (F0 2026-10-17)**: containerd 2.2.1 + CRI, swap off на всех; LV Longhorn 250G на 02/03/04 (k8s-01 вне пула); NVMe 477G на всех | `ARCHITECTURE.md` §2.3, ADR-0002 |
| Кластер | kubeadm 1.35.9 (пин спеки §3), CNI Cilium; роли (ADR-0003): **k8s-01/02/03 — control-plane ×3** (компьют на 01, GitOps на 02, **ingress — пара 02/03 на VIP `.230`**, лёгкие сервисы на 03), k8s-04 — LLM-инференс **и** data-heavy сервисы (без taint'а; nodeSelector + priorityClass) | `ARCHITECTURE.md` §5, ADR-0003 |
| Хранилище | **Longhorn**: default StorageClass, replica=2, анти-аффинити; пул LV 250G на 02/03/04, k8s-01 вне пула (износ диска); данные сервисов — PVC, модели — hostPath на k8s-04 | ADR-0002, ADR-0003 |
| Ingress | **Higress** — единственный контроллер; целевая точка — ingress-VIP `.230` на паре k8s-02/03 (NAT с .253 переедет туда) | ADR-0001, спека §10 |
| Сеть | MikroTik `gw-demo-ai-lab`, LAN `192.168.10.0/24`, LAG до коммутатора, Wi-Fi для аудитории | `network-map-detail.md`, `mikrotik-setup.md` |
| Доступ | снаружи — Cloudflare Tunnel (ADR-0004); TLS Full strict: edge (Universal SSL) + origin LE wildcard (cert-manager DNS-01, ADR-0004 ревизия); LAN — split-DNS → `.230`, тот же https | `ARCHITECTURE.md` §6, ADR-0004 |
| Подготовка сцены | образы pre-pull на узлы; модели в кэше k8s-04; база RAGFlow проиндексирована заранее | — |

На стенде до демо **не установлено**: GPUStack, сервисы шага 2 и агенты шага 3 — их
разворачивают прямо во время выступления.

## Три шага демо

### Шаг 1 — Инфраструктура во главе с GPUStack

- Установка GPUStack **v2.2.3** helm-чартом `gpustack-chart:2.2.3` (вместе с ним
  поднимается Higress): server
  (StatefulSet, данные в Longhorn) + worker на LLM-ноде k8s-04;
- Бекенд — llama.cpp/llama-box (GGUF): инференс на **GPU k8s-04 (RTX 5060 Ti 16G,
  driver 595-open)**; в k8s-инсталляции LLM исполняется только через GPUStack (решение
  2026-10-18), хостовый BeeLlama-прогон остаётся примером вне кластера;
- Модели из кэша: qwen3-8b/14b (GGUF Q4, tool-calling) + bge-m3 (эмбеддинги);
- guardrail-подготовка: **Prompt Guard 2** (86M GGUF) **CPU-worker'ом GPUStack** на k8s-01
  (не занимает VRAM k8s-04) + **guard-маршрут** на Higress — Wasm-плагин `ai-security-guard`,
  бэкенд модерации = тот же Prompt Guard через OpenAI-API; рубильник — аннотация Ingress;
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
- **демо guardrail:** в RAGFlow грузится документ с prompt-injection → запрос агента идёт
  через guard-маршрут → Prompt Guard детектит инъекцию, блокировка с событием в логах Higress;
  снятие аннотации — инъекция проходит (контраст «без guardrail агент ведётся»).

---

Актуальный статус строительства стенда — `architecture/ARCHITECTURE.md` §7 (на момент
написания: кластер и Longhorn ещё поднимаются). Репозиторий публичный; публикуются только
нечувствительные данные (секреты, MAC-адреса и адреса uplink — вне репозитория).