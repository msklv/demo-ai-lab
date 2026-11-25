# architecture — каталог архитектуры стенда

Здесь два вида артефактов и один указатель:

- **диаграммы** — исходники (`.excalidraw`, `.html`, mermaid в `.md`) и рендеры `.jpg` (этот каталог);
- **спецификации сервисов** — `architecture/specs/` (пины, размещение, фазы, приёмка, риски);
- **архитектура и текущий статус** — `ARCHITECTURE.md` (§2–§6 — слои и размещение, §7 — что закрыто
  и что открыто, §8 — файлы). Диаграммы в тексте — там же; здесь только их каталог.

## Диаграммы

Рендер лежит рядом с источником, единственный формат — `.jpg`:

```bash
python3 scripts/render_diagrams.py            # architecture/, все источники
python3 scripts/render_diagrams.py network    # карта сети из network/map.md
python3 scripts/render_diagrams.py --changed  # только источники новее своего .jpg
```

Нужны node ≥ 18 и Chromium — `scripts/README.md`. Скрипт проверяет `index` элементов Excalidraw:
битый или дублирующийся ключ = файл не откроется в приложении, хотя JPEG соберётся. Правки JSON
руками заканчивать этим прогоном.

| Диаграмма | Источник | Рендер | Где в тексте |
|---|---|---|---|
| C1 — контекст (акторы, внешняя VM, внешние системы) | `architecture-c1.excalidraw` | `architecture-c1.jpg` | `ARCHITECTURE.md` §1 |
| C2 — целевой контейнер (слои и сервисы) | `architecture-c2.excalidraw` | `architecture-c2.jpg` | `ARCHITECTURE.md` §3 |
| Сеть (uplink, MikroTik, Tenda, узлы, backend p2p) | mermaid в `network/map.md` | `../network/map.jpg` | `ARCHITECTURE.md` §2 |
| Полная схема (физический + логический слой) | `demo-ai-lab-architecture.html` | `demo-ai-lab-architecture.jpg` | `ARCHITECTURE.md` §1 |

## Спецификации — `architecture/specs/`

| Спека | О чём | Фазы |
|---|---|---|
| `specs/k8s-install-spec.md` | установка кластера: kubeadm → Cilium → Longhorn → NFD → cert-manager → Argo CD → ingress-VIP `.230` + Higress; грабли и приёмка фаз | F0–F10 |
| `specs/external-access-spec.md` | внешний доступ: внешняя VM (`haproxy`, SNI passthrough) + SSH-hop'ы, split-DNS, TLS на origin; история туннельного периода — таблица в конце | E1–E5, E7 (E6 снят) |
| `specs/keycloak-spec.md` | SSO: Keycloak 26.8.1 ×2 + PostgreSQL 17.11 на паре 02/03, `auth.`, realm `dev` | K1–K7 |
| `specs/gpustack-spec.md` | GPUStack 2.2.3: чарт, GPU-воркер k8s-04, раннер vLLM, модели, `api.` | G0–G8 |
| `specs/owu-spec.md` | Open WebUI: чарт 17.0.0, OIDC Keycloak, ключ GPUStack, пробы/ресурсы | O1–O6 |
| `specs/spk-spec.md` | Speakr: plain-манифесты, ASR через GPUStack, SSO | S1–S6 |
| `specs/doc-spec.md` | Docling Serve + MCP: образ `-cpu`, OCR, кэш моделей Job-хуком; VLM-пресет `GLM-OCR` | D1–D6 |
| `specs/ysearch-spec.md` | Yandex Search MCP: форк 1.3.1, StreamableHTTP `/mcp`, TCP-пробы | Y1–Y5 |
| `specs/firecrawl-spec.md` | извлечение веб-страниц: Firecrawl 2.10.19 + playwright + RabbitMQ + PG + Redis, ClusterIP-only, guard приватных адресов | C1–C6 |
| `specs/mcp-registry-spec.md` | каталог MCP-серверов: Registry 1.8.6 + PG 16, витрина `/`, API `/v0` | M1–M8 |
| `specs/llm-proxy-spec.md` | проксирование LLM наружу (`llm.`, `llm-svc.`): JWT/ключ, `ai-proxy`, DLP, страж, лимиты | P1–P6 |
| `specs/dsh-spec.md` | DeepSeek Harness: образ node 24, SSO через `oauth2-proxy`, MCP-мост, песочница | W1–W8 |
| `specs/rag-spec.md` | RAGFlow 1.0.0: один под + MySQL/MinIO/Kvrocks/NATS/ES, SSO нет, вход по паролю; `bge-m3` + реранк на 780M | R1–R9 |
| `specs/glm-ocr-spec.md` | OCR-VLM `GLM-OCR` на 5070 Ti: веса, бэкенд `vllm-custom`, грабли раннера, smoke-скрипт | R1–R7 |
| `specs/health-check-spec.md` | проверка здоровья пятью слоями + формат ответа владельцу | — |
| `specs/hermes-spec.md` | Hermes Agent: образ по digest, SSO PKCE, MCP стенда + GitHub MCP, модели, обвязка | H1–H10 |
| `specs/monitoring-spec.md` | метрики: dcgm-exporter + job `dcgm_gpu` + дашборд; ограничения (retention, без алертов) | — |
| `specs/tts-spec.md` | TTS с клоном голоса: Qwen3-TTS + CosyVoice3, маршруты, бюджет VRAM, замеры | — (кейс 08) |
| `specs/gpustack-custom-backend-spec.md` | тестовый прогон BeeLlama как custom backend GPUStack (на архитектуру не влияет) | B0–B7 |
| `specs/gpustack-argocd-migration.md` | перенос релиза GPUStack под Argo CD: adopt без роллаута | — |

Фазы буквами не переиспользуются между спеками; правила оформления — `references/service-spec-authoring.md`.
Статус каждой спеки — `ARCHITECTURE.md` §7 (единственный источник).

## Что ещё в каталоге

`ARCHITECTURE.md`, `endpoints.md`, `hardware-inventory.md`, `architecture-*.{excalidraw,jpg}`,
`demo-ai-lab-architecture.{html,jpg}` — с назначением каждого файла: `ARCHITECTURE.md` §8.
