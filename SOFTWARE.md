# ПО стенда demo-ai-lab — реестр определяющих систем

Что стоит на стенде: платформы, сервисы и обвязка, которые **держат слой или видны снаружи**.
Транзитивные зависимости (CSI-sidecar'ы, Dex/Redis внутри Argo CD, библиотеки и протоколы) сюда не входят —
мельчить не нужно.

Снимок — **2026-11-25**: сверено с живым кластером (релизы, образы подов) и спеками.
Версия здесь — та, что исполняется; **пин, digest и причина выбора — в спеке или манифесте**.
Железо — `HARDWARE.md`; набор моделей и переключения — `cases/README.md`; статус стенда —
`architecture/ARCHITECTURE.md` §7.

Не входит по правилам публикации: значения и адреса (`inventory.local.md`), механика обхода
блокировок (`HYGIENE.md`).

## 1. Прикладной софт (платформы и сервисы демо)

| Компонент | Версия | Роль | Где | Спека |
|---|---|---|---|---|
| **GPUStack** | 2.2.3 (чарт `gpustack-chart`, OCI, под Argo) | инференс: UI и OpenAI-совместимый `/v1` (`chat`, `embeddings`, `rerank`, `audio`, `images`) | ns `gpustack`, `api.` | `gpustack-spec` |
| **vLLM (CUDA 13.0)** | `gpustack/runner:cuda13.0-vllm0.25.1` — vLLM 0.25.1 | основной GPU-раннер: чат и модель-страж на 5070 Ti | k8s-04 | `gpustack-spec` §4.6 |
| **vLLM (CUDA 13.0, GLM-OCR)** | `vllm/vllm-openai:v0.20.1-x86_64` — vLLM 0.20.1, кастомный бэкенд `vllm-custom` | OCR-VLM `GLM-OCR` (кейс 04) | k8s-04 | `glm-ocr-spec` |
| **vLLM (ROCm 7.2)** | `gpustack/runner:rocm7.2-vllm0.25.1` — vLLM 0.25.1, `HSA_OVERRIDE_GFX_VERSION=11.0.0` | iGPU 780M: `bge-m3` + реранк, эмбеддинги и RAG (кейс 05) | k8s-01 | `gpustack-spec` §4.6 |
| **vLLM-Omni (CUDA 13.0)** | `gpustack/runner:cuda13.0-vllm0.22.1` — vLLM 0.22.1 | генерация изображений: `Z-Image-Turbo` (кейс 07) | k8s-04 | `cases/07-image-gen.md` |
| **Keycloak** | 26.8.1, ×2 | SSO/OIDC: пользовательский вход и `client_credentials` для машин | ns `keycloak`, пара 02/03, `auth.` | `keycloak-spec` |
| **PostgreSQL** — Keycloak | 17.11, один экземпляр (HA нет — решение по демо) | БД realm'ов, клиентов и сессий SSO | ns `keycloak`, PVC 8Gi | `keycloak-spec` |
| **PostgreSQL** — MCP Registry | 16-alpine | БД каталога MCP-серверов (миграции на старте) | ns `mcp-registry`, PVC 8Gi | `mcp-registry-spec` |
| **PostgreSQL** — Kuvasz | 17.11 | БД монитора аптайма | ns `monitoring`, PVC 8Gi | ADR-0009 |
| **Open WebUI** | 0.12.0 (чарт 17.0.0) | чат к моделям, RAG-эмбеддинги через `api.` | ns `owu`, k8s-03, `owu.` | `owu-spec` |
| **Speakr** | 0.10.18-alpha-lite | транскрибация: ASR — GPUStack, саммари — внешняя модель | ns `spk`, k8s-03, `spk.` | `spk-spec` |
| **Docling Serve** | v1.39.0 (в образе же `docling-mcp`) | разбор документов и OCR; по умолчанию VLM → `GLM-OCR` | ns `doc`, k8s-03, `doc.` | `doc-spec` |
| **RAGFlow** | 1.0.0 (Go-сборка) — **не развёрнут** | RAG: индексация, векторный поиск, объекты внутри самого сервиса | ns `rag` | `rag-spec` |
| **MCP Registry** | 1.8.6 | каталог MCP-серверов: витрина `/`, API `/v0` | ns `mcp-registry`, `mcp.` | `mcp-registry-spec` |
| **Yandex Search MCP** | v1.3.1 (форк `msklv/`) | инструмент веб-поиска (Search API) | ns `ysrch`, только ClusterIP | `ysearch-spec` |
| **GitHub MCP** | v1.12.0 | инструмент агентов: read-only GitHub | ns `mcp-github`, только ClusterIP | `hermes-spec` §7.1 |
| **Firecrawl** | 2.10.19 + playwright-service + RabbitMQ 3.13.7 + Redis 8.10.1 + nuq-postgres; своя MCP-обёртка | URL → markdown для агентов и сервисов | ns `fc`, k8s-05 | `firecrawl-spec` |
| **Guardrail** | плагины Higress `ai-data-masking` + `ai-qwen-guard` (свой Wasm); модель-страж `Qwen3Guard-Gen-4B` | маскирование ПДн, блок словарных запретов, страж `Safe/Controversial/Unsafe` fail-closed | маршруты `llm.` / `llm-svc.` | ADR-0006 |
| **LLM-прокси** | `ai-proxy` (DeepSeek), `ai-token-ratelimit`, `jwt-auth`, `key-auth`, OPA 0.70.0, Valkey 8.1 | вход к внешней модели: DLP → страж → провайдер → лимиты | ns `llm`, `llm-svc.` | `llm-proxy-spec`, ADR-0008 |
| **nginx** | 1.27-alpine | smoke-контейнер `echo.`, раздача wasm, `plugin-server` плагинов | ns `demo-test`, `higress-system`, `llm` | `k8s-install-spec` |

## 2. Агенты

| Компонент | Версия | Роль | Где | Спека |
|---|---|---|---|---|
| **Hermes Agent** | v0.23.0 (пин по digest) | агент-платформа: панель, инструменты, скиллы; модели — `api.` и `llm-svc.` | ns `her`, k8s-04, `hm.` | `hermes-spec` |
| **DeepSeek Harness** | 0.2.2-rc.5 (`@deepseek-ai/dsh`, свой образ `ghcr.io/msklv/dsh` на `node:24-slim`, пин по digest) | агент-харнесс: web-UI, пресеты песочницы, плагины, MCP-мост | ns `dsh`, `dsh.`; развёрнут, под 1/1 (25.11) | `dsh-spec` |
| **Каталог скиллов** | репо `msklv/skills-demo-ai-lab`, пин коммита — не сервис | скиллы агентов живут отдельным публичным репозиторием | GitHub | ADR-0010 |

## 3. Системный софт

### Кластер

| Компонент | Версия | Роль | Где |
|---|---|---|---|
| **Kubernetes** | 1.35.9 (kubeadm/kubelet/kubectl, `apt-mark hold`), etcd 3.6.6, CoreDNS 1.13.1 | кластер: 3 control-plane + 2 worker'а | 5 узлов |
| **containerd** | 2.2.1 + runc, CRI, systemd-cgroup | контейнерный рантайм нод | 5 узлов |
| **Cilium** | 1.20.3, full KPR (+ cilium-envoy) | CNI, kube-proxy replacement, service-watch для VIP | ns `kube-system` |
| **Longhorn** | 1.13.0, SC default `replica=2` | блочные тома PVC; пул 02/03/04 ×250G + 05 ×500G, k8s-01 вне пула | ns `longhorn-system` |
| **kube-vip** | v0.9.2, два независимых инстанса | `.240` — только kube API, `.230` — только ingress (LB) | статические поды на CP / 02+03 |
| **Higress** | 2.1.9 (core: controller, pilot, gateway ×2) + console 2.1.9 | единственный ingress и AI-шлюз; VIP `.230` | ns `higress-system` |
| **cert-manager** | v1.21.2 | Let's Encrypt: HTTP-01 для новых хостов (зона на reg.ru — DNS-01 недоступен), wildcard — прежний выпуск; сертификат живёт в namespace Ingress'а | ns `cert-manager` |
| **metrics-server** | чарт 3.14.0 / app v0.9.0 | Metrics API для `kubectl top` (истории нет) | ns `kube-system` |
| **NFD** | 0.20.0 (стенд) и 0.18.3 (в бандле GPUStack) | метки железа: GPU-нода для DaemonSet'ов | ns `node-feature-discovery`, `gpustack` |
| **GPUStack operator** | 0.5.4 + kueue 0.17.6 + CSI S3 0.43.7 / NFS 4.13.2 | GPU-планирование и вспомогательные CSI; остаются helm-релизами | ns `gpustack` |

### Узлы и GPU

| Компонент | Версия | Роль | Где |
|---|---|---|---|
| **Ubuntu LTS** | 24.04.4; ядро 6.8.0-149 (k8s-04 — после клона диска) | ОС нод: swap off, open-iscsi, nfs-common | 5 узлов |
| **NVIDIA driver** | 595.99.02, open kernel modules (`-open` — обязателен для Blackwell) | драйвер RTX 5070 Ti, hold | k8s-04 |
| **nvidia-container-toolkit** | 1.20.1, CDI | проброс GPU в поды, `RuntimeClass nvidia` | k8s-04 |
| **ROCm userspace** | 7.2.3, `/opt/rocm` (14 МБ, только `amd-smi`/`rocm-smi`) | iGPU 780M под vLLM-раннером: эмбеддинги и реранк | k8s-01 |

### Сеть и внешний вход

| Компонент | Версия | Роль | Где |
|---|---|---|---|
| **MikroTik RouterOS** | 7.24.5 | LAN/DHCP-резервации, NAT, firewall, split-DNS зоны на ingress-VIP | `gw-demo-ai-lab`, L009UiGS-2HaxD |
| **haproxy** | пакет Ubuntu 24.04, `mode tcp` | публичный вход `:443` и ACME-redirect `:80`; TLS не терминирует, SNI-денилст служебных UI | внешняя VM (Cloud.ru) |
| **SSH reverse-hop** | `vmhop.service`, по одному на 02/03 | доводит origin с внешней VM до Higress | 02/03 → VM |

## 4. DevOps обвязка

| Компонент | Версия | Роль | Где |
|---|---|---|---|
| **Argo CD** | v3.5.5 (чарт 10.10.5) + ApplicationSet, app-of-apps | единственная точка деплоя: `git push` → кластер, prune + selfHeal | ns `argocd`, `argo.` (только LAN) |
| **Kustomize** | 5.8.1 (`--enable-helm`) | рендер чарта GPUStack внутри Argo | Argo CD |
| **Prometheus + Grafana + Loki** | 2.40.7 / 9.3.6 / 2.9.4 (бандл консоли, retention 6h) | метрики, логи, дашборд `demoai-gpu`; алертов нет | ns `higress-system` |
| **dcgm-exporter** | 4.7.0-4.9.0 (distroless, пин по digest) | GPU-телеметрия в Prometheus | ns `monitoring`, k8s-04 |
| **Kuvasz** | 4.6.0 (+ PostgreSQL 17) | black-box аптайм и TLS: 13 хостов зоны, MCP `/mcp` только из кластера | ns `monitoring`, `mon.` (UI — LAN) |

## 5. Внешние зависимости

| Система | Роль | Как подключено |
|---|---|---|
| **DeepSeek Platform** | внешняя модель `deepseek-flash` (кейсы 02/03/05) | `llm-svc.`: DLP → страж → `ai-proxy`, ключ в Secret |
| **Yandex Search API** | веб-поиск инструментом `ysrch` | ключ в Secret сервиса (`ysearch-spec`) |
| **GitHub** | код, релизы образов (ghcr), GitHub MCP | репозиторий; `mcp-github`, PAT на каждый запрос |
| **Cloud.ru** | внешняя VM: публичный вход, `haproxy`, hop-и | `external-access-spec` E7 |
| **reg.ru** | DNS зоны `demo-ai-lab.ru` (A + wildcard) | `external-access-spec` |
| **Реестры образов** | Docker Hub, ghcr, quay.io, registry.k8s.io | прямой pull с нод, локального зеркала нет |

## Как вести реестр

- **Строка = платформа или сервис**, который держит слой либо виден снаружи. Софт операторской
  консоли (kubectl, helm, ansible, скрипты на Mac) — не часть стенда и в реестр не входит. Sidecar'ы, библиотеки
  и внутренние зависимости (Dex и Redis внутри Argo CD, CSI-attacher) не перечисляем.
- **Версия — фактическая**, снятая с живого кластера. Пин и обоснование живут в спеке/манифесте;
  расхождение реестра и `helm list` — повод разобраться, а не молча обновить таблицу.
- **Новая строка** — когда компонент появился в кластере или в пути трафика; удаление — вместе
  с выводом компонента (запись в `architecture/ARCHITECTURE.md` §7). Модели, железо и адреса — не сюда.
- Правка ссылок проверяется `python3 scripts/check_doc_links.py`.
