# ADR — Architecture Decision Records (стенд demo-ai-lab)

Реестр ключевых архитектурных решений стенда. ADR фиксирует принципиальные решения,
которые трудно или дорого менять постфактум (компонент платформы, схема сети,
модель хранилища, распределение сервисов). Рядовой пункт чек-листа или настройка —
не ADR.

## Как добавлять

1. Номер: максимальный существующий `adr-NNNN` + 1.
2. Имя файла: `adr-NNNN-<короткий-slug>.md` (kebab-case, транслит/англ.).
3. Статусы: `Proposed` → `Accepted` → (при пересмотре) `Superseded by ADR-NNNN`.
   Решение считается принятым после явного согласия владельца стенда.
4. Факты — только проверенные (живой замер / вывод команды), с датой; разделяй
   «проверено» и «план/гипотеза».
5. Пересмотр решения — это НОВЫЙ ADR, старый помечается `Superseded` со ссылкой.
   Задним числом принятые записи не переписываются; **исключение** (решение владельца,
   2026-10-17): пока стенд не поднят, допустима актуализация ADR «на месте» ради
   консистентности — с строкой `Ревизия: <дата> — <почему>` в шапке записи.

## Шаблон записи

    # ADR-NNNN: <Заголовок>
    - Дата: YYYY-MM-DD
    - Статус: Accepted | Proposed | Superseded by ADR-NNNN

    ## Контекст
    ## Решение
    ## Последствия
    ## Альтернативы (рассмотрены и отклонены)

## Реестр

| ADR | Статус | Дата | Решение |
|---|---|---|---|
| [0001](adr-0001-higress-as-sole-ingress.md) | Accepted | 2026-10-19 | Higress — единственный ingress-контроллер стенда; **рев. 3: ставится standalone (higress-core 2.1.9, F7/F8 инсталл-спеки)**, GPUStack подключается через `gateway.ingressClassname`. Версия GPUStack зафиксирована — v2.2.3. **Рев. 4 (2026-10-29): сравнение Envoy Proxy / Higress / Bifrost — Bifrost отклонён (не ingress, AI-функции дублируются), Envoy остаётся data plane под Higress** |
| [0002](adr-0002-node-storage-model.md) | Accepted | 2026-10-12 | Дисковая модель: отдельный LV под Longhorn 250G; пул 02/03/04 (k8s-01 вне пула — ADR-0003); переустановка 02/03 (root 100G) и F0 (LV 250G ×3, ext4, смонтированы) выполнены 2026-10-17; актуализирован 2026-10-17, ревизия контекста 2026-10-18 |
| [0003](adr-0003-three-control-planes.md) | **Accepted** | 2026-10-17 | Три control-plane: k8s-01/02/03 (stacked etcd ×3); снятие CP-taint'ов; компьют на k8s-01; k8s-04 без taint'а — LLM+сервисы, data-heavy там же; Longhorn-пул 02/03/04×250G, k8s-01 вне пула (износ диска); endpoint API = **вариант A: kube-vip VIP .240** (принят владельцем 2026-10-17; .240 выведен из DHCP-пула) |
| [0004](adr-0004-external-access-tunnel-and-vm-egress.md) | **Accepted** | 2026-10-18 | Внешняя доступность — только через Cloudflare (Free): зона demo-ai-lab.ru в Cloudflare, публичный DNS = edge-адреса (IP площадки не публикуется), Tunnel `demo-lab-ingress-v2` → `https://.230` (Full strict, LE wildcard + caPool — E5); коннектор с 2026-10-24 — на внешней VM, origin через SSH-hop + haproxy (E7); входящие в uplink не нужны; TLS: edge Universal SSL + origin LE wildcard (cert-manager DNS-01, Full strict — ревизия 2026-10-18); Access опционально |
| [0005](adr-0005-mcp-registry-and-higress.md) | **Accepted** | 2026-10-24 | MCP: **реестр `modelcontextprotocol/registry` ставим** (каталог MCP-серверов, `mcp.demo-ai-lab.ru`, ns `mcp-registry`), вызовы и хостинг инструментов — **Higress** (`mcp-server`: REST→MCP, `mcp-proxy` по `remotes`, `allowTools`). Совместно: реестр-каталог + вызовы на шлюзе (схема 1) и реестр за шлюзом с OIDC/лимитами (схема 2); синхронизация реестр → Nacos 3.x (схема 3) отложена. Нативного чтения реестра Higress не умеет — MCP поддержан только у service source `nacos3`. Развёртывание — `architecture/mcp-registry-spec.md` |
| [0006](adr-0006-guardrail-higress-qwen3guard.md) | **Accepted** | 2026-10-24 | Guardrail = **Higress 2.1.9 + `ai-data-masking` + Qwen3Guard-Gen-0.6B** (Apache-2.0, 1.41 GiB) через кастомный Wasm-плагин `ai-qwen-guard`; рубильник — аннотация Ingress. облачные модераторы отклонены по условиям контура; класс `guardrails-ai`/LLM Guard, NeMo Guardrails, FMS Guardrails Orchestrator, Presidio и модели Llama-Guard/ShieldGemma/Granite Guardian/WildGuard — рассмотрены, в демо не берутся |
| [0007](adr-0007-model-roster-and-gpu-budget.md) | **Accepted** | 2026-10-24 | Модели и бюджет видеопамяти `k8s-04`: **RTX 5060 Ti (15.93 GiB VRAM)** — резидентно `gemma-4-12B-it-qat-w4a16-ct` (util 0.75) + ASR `whisper-large-v3-turbo` (util 0.15) = 13.91/15.93; **Radeon 780M (GTT 8 из 32 GB DDR5, gfx1103)** — vLLM-only: страж `Qwen3Guard-Gen-0.6B` + `bge-m3` + `bge-reranker-v2-m3` = 5.23/8 GiB (wheel `v0.25.1-rocm10.0.0-gfx1103-gfx1100-verified`), llama.cpp на узле не остаётся; OCR — CPU (Docling). Диск 04: root-LV расширен 2026-10-27 до 210 GB (свободно 109 GB) — после полного прогрева занято 39.19 GB, ограничение R-G5 снято |
