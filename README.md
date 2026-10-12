# demo-ai-lab — демонстрационный AI Lab

Публичный стенд **demo-ai-lab.ru**: on-prem LLM-инференс, RAG, транскрибация и ИИ-агенты
на собственном Kubernetes-кластере из трёх мини-ПК. Принцип утилитарности:
**локальная обработка предпочтительна** — наружу уходит только то, что не представляет ценности.

## Документация

| Файл | Что это |
|---|---|
| `architecture/ARCHITECTURE.md` | архитектура C2, размещение сервисов по узлам, статус строительства (§7) |
| `network-map-detail.md` | живая карта сети стенда |
| `mikrotik-setup.md` | рецепт настройки MikroTik (для повторения стенда) |
| `adr/` | реестр ключевых архитектурных решений (Higress, дисковая модель) |
| `AGENTS.md` | правила работы с репозиторием (что публикуем, что нет) |

## Исходная точка демо

К началу выступления на стенде **уже развёрнуто и проверено** (это не часть демо):

| Слой | Что стоит | Где зафиксировано |
|---|---|---|
| Железо | 3× GMKtec (Ubuntu 24.04.4), containerd 2.2.1 + CRI, swap off; NVMe 477G: root 100G + longhorn LV 250G на каждой ноде | `ARCHITECTURE.md` §2.3, ADR-0002 |
| Кластер | kubeadm (≥1.30), CNI Cilium; роли: k8s-02 — control-plane + ingress + GitOps, k8s-03 — данные, k8s-04 — LLM (taint `dedicated=llm`) | `ARCHITECTURE.md` §5 |
| Хранилище | **Longhorn**: default StorageClass, replica=2, анти-аффинити; данные сервисов — PVC, модели — hostPath на k8s-04 | ADR-0002 |
| Ingress | **Higress** — единственный контроллер; NAT 80/443 → k8s-02 | ADR-0001 |
| Сеть | MikroTik `gw-demo-ai-lab`, LAN `192.168.10.0/24`, LAG до коммутатора, Wi-Fi для аудитории | `network-map-detail.md`, `mikrotik-setup.md` |
| Доступ | DNS `*.demo-ai-lab.ru`, cert-manager + Let's Encrypt, hairpin для LAN-клиентов | `ARCHITECTURE.md` §6 |
| Подготовка сцены | образы pre-pull на узлы; модели в кэше k8s-04; база RAGFlow проиндексирована заранее | — |

На стенде до демо **не установлено**: GPUStack, сервисы шага 2 и агенты шага 3 — их
разворачивают прямо во время выступления.

## Три шага демо

### Шаг 1 — Инфраструктура во главе с GPUStack

- Установка GPUStack 2.2 helm-чартом (вместе с ним поднимается Higress): server
  (StatefulSet, данные в Longhorn) + CPU-worker на LLM-ноде k8s-04;
- Бекенд — llama.cpp/llama-box (GGUF, инференс на CPU); vLLM/SGLang — «GPU-ready»
  повестка (дискретного GPU на стенде нет, инференс CPU-first);
- Модели из кэша: qwen3-8b/14b (GGUF Q4, tool-calling) + bge-m3 (эмбеддинги);
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
  Open WebUI), каждый вызов модели виден в трассах.

---

Актуальный статус строительства стенда — `architecture/ARCHITECTURE.md` §7 (на момент
написания: кластер и Longhorn ещё поднимаются). Репозиторий публичный; публикуются только
нечувствительные данные (секреты, MAC-адреса и адреса uplink — вне репозитория).