# demo-ai-lab — Архитектура стенда

> Демонстрационный AI Lab: визуализация работы ИИ-агентов и on-prem LLM-инференса.
> `network-map-detail.md` (живой аудит, актуализировано 2026-10-29),
> `architecture/architecture-c1.excalidraw` (контекст C1) и
> `architecture/architecture-c2.excalidraw` (целевой контейнер C2), `IDEAS.md`,
> `inventory.local.md` (скрытый — MAC/доступы, не публикуется).
> Диаграмма: `demo-ai-lab-architecture.html` (открывается в любом браузере).

## 1. Концепция

- Публичное имя лаборатории — **`demo-ai-lab.ru`** (разглашение и публикация допустимы).
- Закрытая демо-сеть (LAN `192.168.10.0/24`) на 4 узлах GMKtec (Ubuntu 24.04.4)
  + шлюз MikroTik + Mac-консоль.
- Целевое состояние — «контейнер C2»: Kubernetes-кластер с LLM-инференсом,
  агентами, RAG, транскрибацией и observability.
- Задача (IDEAS.md): демо работы ИИ-агентов и on-prem вычислений; принцип
  утилитарности — локальная обработка предпочтительна, наружу передаётся
  только то, что не представляет ценности.

## 2. Физический слой (проверено живым аудитом)

### 2.1 Сегменты

| Сегмент | Назначение | Детали |
|---|---|---|
| Uplink (сеть площадки) | сеть за шлюзом, выдаётся площадкой конференции | её адреса не публикуются |
| `192.168.10.0/24` | LAN (демо-сеть) | шлюз `192.168.10.1`; DHCP pool `.10–.229,.231–.239,.241–.254` (`.240` API-VIP, `.230` ingress-VIP — выведены из пула); Wi-Fi (2.4GHz-n) + bridge; split-DNS: `demo-ai-lab.ru` + regexp-wildcard → `.230` (`mikrotik-setup.md`) |
| `10.20.20.0/26` | Backend p2p | k8s-02 `.2` ↔ k8s-03 `.3`, 2.5G, MTU 1500; L2 проверен (2026-10-12); netplan восстановлен 2026-10-18 (`ansible/pb-net-p2p.yaml`, приёмочный взаимный ping) |

### 2.2 Шлюз

- **MikroTik L009UiGS-2HaxD** (identity `gw-demo-ai-lab`), RouterOS **7.24.5**.
- LAN: `bridge` → `192.168.10.1/24`; WAN: `ether1` = uplink площадки (адреса не публикуются).
- **Link aggregation до коммутатора**: `bond1` = ether7+ether8 (mode `balance-xor`), порт бриджа —
  подключён к Tenda **TEM2010X** (8 × 2.5 Гбит/с + 2 × SFP+; L2, статическая агрегация портов 7–8,
  без LACP); ноды — на портах 1–6 Tenda.
  Проверено 2026-10-12: все три ноды пингуются через bond (роутер и Mac), оба линка 1G, 0 ошибок.
- Маршрут: default через шлюз площадки; NAT: masquerade на WAN (LAN → интернет).
- Firewall: защита WAN (input drop из не-LAN, drop invalid, fasttrack),
  изоляция стенда: forward drop LAN → uplink-сеть (другие стенды недоступны с LAN, интернет работает).
  mDNS в bridge разрешён.
- Управление: Winbox (8291) / REST (8080, основной канал) / API (8728) / SSH (22, запасной, разовые команды), вход `admin`;
  Изменения — владельцем через UI, не API (правило).

### 2.3 Узлы (GMKtec, Ubuntu 24.04.4)

| Узел | LAN IP (DHCP) | 2-й интерфейс | CPU / RAM / Диск | Целевая роль |
|---|---|---|---|---|
| `k8s-01` | 192.168.10.250 | `enp3s0` — **не используется** (down) | R7 7840HS 8C/16T · **32Gi** (30Gi usable) · NVMe 477G (root-LV 100G) | **control-plane #1 + компьют-heavy** (ADR-0003); подготовка F0 выполнена (2026-10-17) |
| `k8s-02` | 192.168.10.253¹ | `enp2s0` — p2p `10.20.20.2` (восстановлен 2026-10-18) | R5 7640HS 6C/12T · 14Gi · NVMe 477G (root-LV 100G) | **control-plane #2** + **ingress-пара с 03 (VIP .230)** + GitOps + cloudflared; **переустановлена 2026-10-17** |
| `k8s-03` | 192.168.10.254¹ | `enp2s0` — p2p `10.20.20.3` (восстановлен 2026-10-18) | R5 7640HS 6C/12T · 14Gi · NVMe 477G (root-LV 100G) | **control-plane #3** + **ingress-пара с 02 (VIP .230)** + cloudflared + лёгкие сервисы; **переустановлена 2026-10-17** |
| `k8s-04` | 192.168.10.252 | `enp3s0` — **не используется** | R7 H255 8C/16T · **28Gi** · NVMe 477G (root-LV **210G** с 2026-10-27) · **GPU RTX 5070 Ti 16G** | worker: LLM-инференс + сервисы (ADR-0003) |
| `k8s-05` | 192.168.10.251 | `enp2s0` — **не используется** (down) | R7 H255 8C/16T · 14Gi · NVMe **1T** (root-LV 100G · ~828G в VG) | **worker без taint'а (введена 2026-11-08)**: F0 + kubeadm join выполнены, роль «компьют»; Longhorn-планирование off до решения по диску (§7 #26) |
| This Mac | 192.168.10.200 (статик-лиз; замер 02.11.2026) | — | — | консоль: ssh, kubectl, диаграммы |

_Диск (пересмер 2026-10-17): на всех нодах NVMe 512GB-класса (476.9G, «AirDisk 512GB SSD»,
на k8s-01 — «ZSPEED SSD 512GB»). После переустановки 02/03 все четыре узла однотипны:
root-LV 100G, свободно в VG ~374G. Целевые LV 250G на 02/03/04; k8s-01 вне пула Longhorn
(износ диска) — ADR-0002 + ADR-0003. **Уточнение 2026-10-27:** на k8s-04 root-LV расширен
150 → 210 GB (`lvextend -r -L +60G`, ФС 207G — ADR-0007); живой замер 02.11.2026: занято 157G,
свободно 40G (80 %). **Уточнение 2026-11-08:** добавленная `k8s-05` — исключение из «однотипности»:
NVMe 1 TB «Netac NVMe SSD 1TB» (диск новый, износ 0 %), root-LV 100G, ~828G свободно в VG
(замер — `hardware-inventory.md`, снимок 2026-11-08).**
_¹ После переустановки 02/03 резервации на время не срабатывали (грабля client-id/DUID —
`mikrotik-setup.md` §3.5); восстановлены 2026-10-17, узлы на .253/.254._

Износ/ресурс NVMe, прошивки и документация по дискам (TBW) — хронологический журнал:
[`hardware-inventory.md`](hardware-inventory.md).

Доступ: SSH по ключу (владелец), sudo на нодах — детали в
`inventory.local.md` (в `.gitignore`, не публикуется).

## 3. Логический слой — целевое состояние (контейнер C2)

Контейнер C2 = Kubernetes на k8s-01/02/03/04 + ingress. Слои:

| Слой | Компоненты | Назначение |
|---|---|---|
| Агентский | **Hermes Agent**; **qm** — multiplayer-харнесс агентов ([yc-software/qm](https://github.com/yc-software/qm)); вынесенные рантаймы (изолированные, с ограничениями) | автономный цикл: код, инструменты, скиллы |
| Пользовательские сервисы | Speakr, RAGFlow, Open WebUI | транскрибация, RAG, UI к LLM |
| MCP-сервисы | **OCR · Docling MCP** (`/mcp`), **Yandex Search MCP** (`ysrch.`), **Kuvasz MCP** (`mon./mcp`, только LAN) — три сервера в каталоге | инструменты агентов: разбор документов, веб-поиск, состояние мониторинга |
| Вспомогательные | **MCP Registry** (`mcp.`, self-hosted `modelcontextprotocol/registry`) — каталог MCP-серверов (публикация — доменная проверка `demo-ai-lab.ru`; Keycloak — админ/права публикации; вызовы — Higress); каталог скиллов | инфраструктура агентов |
| Данные и интеграции | Keycloak (SSO), Qdrant, PostgreSQL/ClickHouse, S3 | идентичность, векторы, реляционное/колоночное, объекты |
| Вычислительный | **GPUStack v2.2.3** (on-prem LLM, OpenAI-API; версия зафиксирована, ADR-0001); инференс — раннер каталога GPUStack: выбран **vLLM** `gpustack/runner:cuda13.0-vllm0.25.1`, SGLang доступен, не используем. Отдельного LLM-прокси/гейтвея в архитектуре нет (ADR-0001 рев. 4) | инференс |
| Guardrail | **Higress + `ai-data-masking` + Qwen3Guard** (ADR-0006, 2026-10-24; рев. 2026-11-02): маскирование ПДн и словарный блок на шлюзе, классификация `Safe/Controversial/Unsafe` моделью-стражем **`Qwen3Guard-Gen-4B` на 5070 Ti (≈12.7 GiB, `util 0.80`, Apache-2.0, категории `PII`/`Jailbreak`)**; в кейсе 03 рядом с ASR исполняет 0.6B под тем же внешним ID (ADR-0007) — через кастомный Wasm-плагин `ai-qwen-guard`; отдельного guard-сервиса нет | модерация входа: ПДн, инъекции/джилбрейк; рубильник — аннотация Ingress |
| Кластер и эксплуатация | Argo CD (GitOps), k8s ingress, Мониторинг (метрики/логи/трейсы) | деплой и наблюдаемость |

**LLM-трафик** идёт только через Higress: on-prem — к GPUStack, наружу — маршрутами `llm-svc.`
(статический ключ; основной в работе) и `llm.` (JWT; с 2026-11-02 на паузе)
(`ai-proxy` + `ai-data-masking` + страж fail-closed + лимиты того же шлюза, **ADR-0008**).
**Эндпоинты разведены по требованию ИБ** (`api.` — локальные модели, `llm.`/`llm-svc.` — проксирование
наружу):
разные политики (fail-open против fail-closed), разные счётчики и отдельное отключение. Второго
LLM-гейтвея (Bifrost,
agentgateway, LiteLLM) и отдельного «лёгкого LLM-прокси» в архитектуре нет — разбор и
причины в `adr/adr-0001-higress-as-sole-ingress.md` (ревизия 4).

**MCP Registry** (решение 2026-10-24: **ставим для демо**) — self-hosted официальный
`modelcontextprotocol/registry` (Go + PostgreSQL): каталог MCP-серверов, публикация своих серверов,
API `/v0` + `/docs`; внешний адрес `mcp.demo-ai-lab.ru`, ns `mcp-registry`, пара k8s-02/03,
развёртывание через Argo CD. **Роль строго каталог:** вызовы инструментов идут через Higress
(`mcp-server`: REST→MCP, `mcp-proxy` по `remotes`-URL из реестра, `allowTools`). Публикация —
доменная проверка `demo-ai-lab.ru` (неймспейс `ru.demo-ai-lab`); **OIDC в реестре
(`MCP_REGISTRY_OIDC_*`) закрывает только админский доступ и права публикации** — владение
неймспейсом через Keycloak не выдаётся. Пины, env, приёмка — `architecture/specs/mcp-registry-spec.md`;
ADR — `adr/adr-0005-mcp-registry-and-higress.md`.

## 4. Ключевые потоки

1. **Интерактивный LLM**: пользователь → ingress (SSO через Keycloak) →
   Open WebUI → GPUStack (OpenAI-API) → модель (on-prem).
2. **Агент**: Hermes Agent → каталог скиллов / MCP-серверов → вынесенные
   рантаймы (ограниченное исполнение) → инструменты и пользовательские
   сервисы; все LLM-вызовы → `ai-statistics` и access-лог шлюза.
3. **RAG**: документ → OCR·Docling → RAGFlow → Qdrant;
   запрос к LLM → retrieval → ответ (Open WebUI / агент).
4. **Транскрибация**: аудио → Speakr → текст → S3.
5. **Внешний LLM — сценарий демо (ADR-0008, развёрнуто 2026-10-29)**: сервис → `llm-svc.` (статический
   `x-api-key`) → `ai-proxy` (`provider.type: deepseek`, ключ в Secret) + `ai-data-masking` + `ai-qwen-guard`
   (**fail-closed** на внешнем маршруте) + `ai-token-ratelimit` → `api.deepseek.com`. Второй вход —
   `llm.` (JWT Keycloak `client_credentials`, `jwt-auth` + `opa`): **с 2026-11-02 на паузе**, маршрут не снят.
   Наружу уходит только обезличенное; egress подов проверен 2026-10-29 (401 за 0.44 s).
   Средства защиты (DLP, страж, лимиты, аудит) — только на стенде, облачных нет (ADR-0008).
   Отдельного LLM-прокси/гейтвея нет — ADR-0001 рев. 4.
6. **GitOps**: GitHub (репозитории, Actions) → Argo CD → k8s (деплой);
   образы — **прямо из облачных реестров** (Docker Hub / ghcr / quay) pull'ом с ноды, локального
   зеркала и склада предзагрузки нет (решение 2026-10-24).
7. **Наблюдаемость**: Мониторинг → метрики/логи/трейсы кластера и сервисов;
   LLM-вызовы — access-лог Higress (`ai-statistics`: кто, модель, токены, вердикт стража);
   отдельного трейсинг-сервиса в архитектуре нет.
8. **Доступ к стенду**: наружу выставлены `api.demo-ai-lab.ru` (GPUStack API) и демо-сервисы шагов 1–4;
   служебные UI (`argo`, `hgc`, `lng`, `mon`) — **только LAN** через allowlist Higress (§6.2, E9/E9.2):
   маршруты в туннеле есть, снаружи `403`.
9. **Guardrail (ADR-0006, решение 2026-10-24)**: сервис/агент → guard-маршрут Higress →
   `ai-data-masking` (маскирование и блок ПДн/словарных запретов, `restore` в ответе) →
   кастомный Wasm-плагин `ai-qwen-guard` → страж в GPUStack (внешний ID `Qwen3Guard-Gen-4B`; исполнитель 4B, в кейсе 03 — 0.6B)
   (`Safety: Safe|Controversial|Unsafe`, категории `PII`/`Jailbreak`) → в модель идут только
   прошедшие проверку запросы; рубильник — аннотация Ingress, событие — в логе шлюза.
   Облачных модераторов и отдельного «guard-сервиса» в архитектуре нет: всё, что проверяет контент
   моделью через внешний сервис (endpoint + ключи + egress), отклонено — ограниченный egress
   (белый список, §6.2) и внешняя зависимость в горячем пути: контент не должен уходить на сторону.
   Альтернативы (класс `guardrails-ai`, NeMo Guardrails, FMS Guardrails Orchestrator, Presidio,
   модели Llama-Guard / ShieldGemma / Granite Guardian / WildGuard) — `adr/adr-0006-guardrail-higress-qwen3guard.md`.

## 5. Размещение сервисов по узлам (план ADR-0003 от 2026-10-17; роль k8s-05 добавлена 2026-11-08)

Железо (пересмер 2026-10-17, SSH, после переустановки 02/03): все четыре узла NVMe 477G,
root-LV 100G (k8s-04 — 210 GB с 2026-10-27, ADR-0007), ~374G свободно в VG на 01/02/03
(**k8s-05, 2026-11-08** — NVMe 1 TB, root-LV 100G, ~828G в VG, в Longhorn-пул не входит). k8s-01 — лидер по RAM (32Gi) и одновременно самый
изношенный диск стенда (ZSPEED, 11% по SMART, ресурс TBW ≈119 TB (остаток ≈106 TB) против ≈250+ TB у AirDisk,
`hardware-inventory.md`). Принцип разделения: **k8s-01 — память, 02/03/04 — диски Longhorn**.

| Узел | Роль в кластере | Что размещать | Почему |
|---|---|---|---|
| k8s-01 (.250) | **control-plane #1** + **компьют** | RAGFlow (разбор/индексация), qm + вынесенные рантаймы (guardrail — плагины Higress, отдельного классификатора на узле нет, см. §4 поток 9) | 32Gi + 8C/16T — лидеры стенда; **вне пула реплик Longhorn** (износ диска): считаем здесь, данные — на томах 02/03/04 |
| k8s-02 (.253) | **control-plane #2** + **ingress (пара с 03)** + GitOps | apiserver/etcd/scheduler/CM; ingress-controller (**Higress** — ADR-0001) на ingress-VIP `.230`; Argo CD; qm; каталоги (сервисов, скиллов); **MCP Registry** (`mcp.`, ns `mcp-registry`) | Маршрутизация сервисов — ingress-VIP `.230` + Higress (проброс WAN 80/443 отключён 2026-10-19); из 14Gi после control-плоскости (~2,5–3 Gi) остаётся ~11 Gi — ingress+лёгкие сервисы |
| k8s-03 (.254) | **control-plane #3** + **ingress (пара с 02, VIP `.230`)** + вспомогательные | Open WebUI, Docling + его MCP-сервер (фактически с 28.10 — на k8s-03), каталоги, лёгкие stateless-сервисы; Higress-gateway | Замыкает etcd-кворум 3/3; тот же бюджет ~11 Gi; second kube-vip (LB, `.230`) только на 02/03 |
| k8s-04 (.252) | **LLM-инференс + сервисы** (без taint'а) | GPUStack (RTX 5070 Ti, nodeSelector; BeeLlama в кластере не исполняется); **data-heavy: PostgreSQL, ClickHouse, Qdrant, MinIO (S3)**; Keycloak (SSO) — **не здесь**: по `architecture/specs/keycloak-spec.md` §4.0 — пара 02/03, чтобы логин не конкурировал с инференсом | 28Gi — вторая RAM стенда; диск в пуле Longhorn → БД локальны к репликам; инференс защищается priorityClass + requests/limits сервисов, а не изоляцией; модели — hostPath; LV Longhorn 250G |
| k8s-05 (.251) | **worker без taint'а** (введена 2026-11-08) | Firecrawl (`fc`, 5 подов, hard-pin), Kuvasz + Postgres мониторинга (`monitoring`); **не** инференс и не шлюз | 14Gi RAM свободны от инференса и ingress — Chromium-стек и JVM-монитор не конкурируют с GPUStack; **вне пула реплик Longhorn** (LV не резан, `allowScheduling=false`) |

### RAM-бюджет размещения

| Узел | Allocatable | Что снимает бюджет | Остаток / вывод |
|---|---|---|---|
| k8s-01 | 30,5 GiB | компьют-heavy: RAGFlow-стек ≈10–12 GiB (ES-heap 2G, replicas=0), OCR·Docling, рантаймы агентов; до сервисов занято ~6 GiB | единственный узел, куда RAGFlow влезает целиком; Qdrant — отдельный бюджет |
| k8s-02/03 | 14,8 GiB каждая | control-plane ≈2,5–3 GiB; OWU ≈1 GiB (03), Speakr ≈2 GiB (03), Docling + MCP ≈3,3 GiB (03 — замер 02.11: под docling на k8s-03), PostgreSQL qm ≈1,5 GiB (03), каталог MCP ≈1 GiB (02/03: PG 768Mi + реестр 256Mi) | на 03 после каталога и Docling остаётся ≈1.7 GiB — RAGFlow-стек туда точно не встаёт (R-M11: первым уходит RAGFlow) |
| k8s-04 | 28,1 GiB | GPUStack + инференс, data-heavy (PostgreSQL, ClickHouse, Qdrant, MinIO) | инференс защищается priorityClass и requests/limits сервисов, а не изоляцией |

Цифры по сервисам — в их спеках (`owu-spec`, `spk-spec`, `doc-spec`, `mcp-registry-spec`);
проверка «влезет ли» — слоями по `architecture/specs/health-check-spec.md`. Тяжёлые дополнительные
сервисы вне этого бюджета (BI и пр.) — слайдом, не на стенде.

Ключевые правила (реализуются через taints/nodeSelector):
- **taint control-plane снять на k8s-01/02/03**; k8s-04 **без taint'а** (ADR-0003,
  правка владельца 2026-10-17) — сервисы живут и на нём. Размещение — nodeSelector по таблице.
- Инференс на k8s-04 защищается **приоритетом, не изоляцией**: nodeSelector закрепляет
  GPUStack, priorityClass выше сервисного (preemption при нехватке RAM),
  сервисы — строго с requests/limits.
- **Longhorn-реплики не на k8s-01**: исполненный механизм — `allowScheduling: false` на объекте
  `nodes.longhorn.io/k8s-01` (замер 02.11.2026), а не аннотация: `create-default-disk="false"`
  диск НЕ предотвратила — на узле остался дефолтный диск ≈85G, он просто не планируется
  (`hardware-inventory.md`). Пул 02/03/04 × 250G (≈750G, ~375G полезных при replica=2).
- Подготовка нод закрыта **F0 (2026-10-17)**: swap off, containerd 2.2.1+CRI, `/etc/hosts`
  на всех четырёх (`pb-k8s-prep.yaml` прогнан, LV Longhorn нарезаны). **k8s-05 — 2026-11-08**:
  F0 тем же плейбуком, LV не резан, Longhorn-планирование off (вне пула).
- Backend p2p 02↔03: узел с основными данными (k8s-04) второй карты не имеет — трафик
  WAN→данные идёт через LAN/LAG 2×1G, для демо-объёмов достаточно; линк остаётся
  внутренней магистралью 02↔03 (восстановление netplan — отложенный пункт).

## 6. Сеть и безопасность

### 6.1 Виртуальные IP (VIP) — два, плоскости не склеивать

| VIP | Назначение | Механизм | Кто держит/обслуживает | Защита от выдачи DHCP | Ссылаются из |
|---|---|---|---|---|---|
| `192.168.10.240` | `controlPlaneEndpoint` — только kube API `:6443` (ADR-0003, вариант A) | kube-vip, статический под, режим ARP + control-plane/leaderElection | все три мастера (k8s-01/02/03) | выведен из DHCP-пула роутера (lease-резерв без MAC RouterOS не принимает) | kubeconfig консоли `~/.kube/demo-ai-lab.conf` |
| `192.168.10.230` | ingress-VIP — HTTP(S)-вход сервисов (Higress-gateway) | kube-vip, второй инстанс, режим LB (ARP, pool `.230`); `externalTrafficPolicy: Local` | пара k8s-02+k8s-03 (gateway закреплен nodeSelector'ом; VIP отвечает там, где живой endpoint) | выведен из DHCP-пула (2026-10-18) | split-DNS MikroTik (`demo-ai-lab.ru` + regexp-wildcard → `.230`); Cloudflare Tunnel-ингресс → `https://.230` (Full strict, LE wildcard + caPool) |

- Итоговый DHCP-пул: `.10–.229,.231–.239,.241–.254` — `.230` и `.240` не выдаются никогда.
- Плоскости разделены намеренно (решение владельца 2026-10-18): деградация ingress не должна
  влиять на API кластера и наоборот; статический `.253` как endpoint отклонён (ADR-0003, вариант B).

### 6.2 Доступность и периметр

- Egress LAN → интернет — через MikroTik (NAT masquerade). **Стенд не закрытый контур: доступ в
  интернет есть, а белый список реализуется на уровне ISP и внешних роутеров** (решение владельца
  2026-10-29) — на самом стенде фильтр не настраивается и не проверяется замером из пода (из пода
  egress выглядит открытым: `example.com` → 200). Наружу ходит только разрешённое и обезличенное
  (внешний LLM — ADR-0008). **Все средства защиты — внутри
  лаборатории** (DLP, контент-страж, аутентификация, лимиты, аудит — на стенде); облачных средств
  защиты в контуре нет, отсутствующее пишется своё (ADR-0006, ADR-0008).
- **Внешняя доступность — Cloudflare Tunnel (ADR-0004, Accepted 2026-10-18)**: зона
  `demo-ai-lab.ru` в Cloudflare Free, публичный DNS = IP edge (адрес площадки не публикуется);
  туннель `demo-lab-ingress-v2`: коннектор `cloudflared` (systemd) с 2026-10-24 — на **внешней VM**
  (SberCloud), origin доводится SSH reverse-hop (`vmhop.service` на 02/03) → `haproxy` →
  `https://127.0.0.1:19443`; стендовые коннекторы на 02/03 выведены (`disable --now` — R1, uplink
  режет `7844`). Ингресс → **`https://192.168.10.230`** (ingress-VIP) + `originRequest.caPool`
  и `originServerName`. Соединения только исходящие (QUIC/TCP 7844) — входящие в uplink
  не требуются; TLS на edge (Universal SSL) + **Full(strict)**: origin-сертификат Let's Encrypt
  wildcard через cert-manager (DNS-01 через Cloudflare) — выпущен и работает с 2026-10-19
  (`architecture/specs/external-access-spec.md` E5); остаточный риск R1 — шторм uplink (530-окна) — там же.
  **Контур внешнего доступа целиком специфицирован в `architecture/specs/external-access-spec.md`**
  (E1–E5: Cloudflare, MikroTik, split-DNS, TLS — с критериями приёмки; E7 — второй egress
  через внешнюю VM + SSH-hop; E6 Access снят 2026-10-24: служебные хостнеймы — только LAN).
- **LAN-путь (основной для демо)**: split-DNS на MikroTik — `demo-ai-lab.ru` и regexp
  wildcard → `.230`, работает с 2026-10-18; аудитория Wi-Fi не зависит от внешних NS/DNS.
  С 2026-10-27 зона отдаёт и **AAAA → `::1`** (apex + wildcard): без этого AAAA уходил в публичный
  резолвер и возвращал anycast Cloudflare, и клиенты с IPv6-предпочтением шли не на `.230`, а наружу.
- **Постоянный smoke-маршрут** — `echo.demo-ai-lab.ru` (ns `demo-test`): тестовый контейнер
  живёт всегда и проверяется и из LAN, и снаружи (решение владельца 2026-10-24).
- **Служебные хостнеймы: админки — наружу, Longhorn — только LAN** (решение 2026-10-24,
  уточнено 2026-10-28): `argo.demo-ai-lab.ru` (Argo CD, до 2026-10-28 — `argocd.`) и
  `hgc.demo-ai-lab.ru` (консоль Higress) имеют маршрут в туннеле
  (`architecture/specs/external-access-spec.md` E9) — **с 2026-11-04 доступ к ним ограничен allowlist'ом
  Higress: только локальные сети (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.10.0/24`), снаружи `403`**
  (решение владельца; E9 рев. 2026-11-04, правило — для всех непользовательских UI, включая `mon.`
  и `lng.`); **Longhorn UI с 2026-11-04 тоже получает маршрут — `lng.demo-ai-lab.ru`, под тем же
  allowlist'ом** (своей авторизации у UI нет, поэтому сеть — единственный гейт). Наружу публикуются также демо-сервисы шагов 1–4.
- Проброс `WAN 80,443 → .253` (2026-10-12) **отключён** 2026-10-19: маршрутизация сервисов —
  только через ingress-VIP `.230` и Higress; входящие в uplink не используются.
- WAN-защита: input drop новых соединений из не-LAN; управление роутером —
  только из LAN (Winbox/REST; SSH — запасной канал для разовых команд).
- Backend `10.20.20.0/26` — изолированный L2 p2p, без маршрута в LAN.
- В целевом состоянии: SSO — Keycloak; секреты не в репозитории (`inventory.local.md` в `.gitignore`,
  public IP — confidential).


## 7. Текущее состояние и пробелы

| # | Пункт | Статус |
|---|---|---|
| 1 | K8s-кластер | **поднят, F0–F9 закрыты 2026-10-19**: kubeadm 1.35.9, 3 CP + worker 04 (**+ worker 05 с 2026-11-08**), все Ready; kube-vip `.240` (лидер — один из CP), etcd ×3, Cilium 1.20.3 full-KPR; Longhorn 1.13.0 (SC default r=2, k8s-01 SCHED=false); NFD 0.20.0 + метка GPU; cert-manager v1.21.2 + ClusterIssuer Ready; Argo CD 10.10.5 Synced/Healthy (selfHeal); ingress-VIP `.230` + Higress 2.1.9; приёмка F9 — health-gate + drill мастера и ingress-пары; **F10 metrics-server 3.14.0 установлен 2026-10-24** (2/2 на 01/04, APIService AVAILABLE, `kubectl top` работает). Открытых фаз по кластеру нет — вне спеки остаются GPUStack и сервисы демо |
| 2 | второй NIC (enp3s0 01/04; enp2s0 02/03) | **готово (2026-10-18)**: backend 10.20.20.0/26 на 02/03 восстановлен (`ansible/pb-net-p2p.yaml`, netplan-файл 60-p2p-backend.yaml, приёмочный взаимный ping зелёный, 2.5G); 01/04 — не используется. Инцидент 2026-10-18: `netplan apply` ребайндит DHCP eno1 и рвёт SSH — плейбук применяет через `systemd-run`; были утеряны резервации .253/.254 (PUT-стирание полей lease), восстановлены на роутере (address/server/mac) |
| 3 | containerd / swap | **готово на всех пяти** (F0 2026-10-17: pb-k8s-prep на 01/02/03; containerd 2.2.1 + CRI, swap off; на 04 дописан k8s-01 в /etc/hosts; **k8s-05 — F0 2026-11-08** тем же плейбуком) |
| 4 | Дискретный GPU | **есть: RTX 5070 Ti 16G в k8s-04** — плата **MAXSUN GeForce RTX 5070 Ti iCraft OC** (`MS-RTX5070Ti iCraft OC16G`; сверка `nvidia-smi` 2026-11-09: 16 303 MiB, VBIOS `98.03.58.40.34`; в доках до 09.11 значилась 5060 Ti — `hardware-inventory.md`, хронология 09.11; driver 595-open, hold) — BeeLlama обкатана на bare-metal; её конфиг `Qwen3.8-27B-UD` в GPUStack ещё не заведён (блокер кейса 01, SPEC B0–B7) |
| 5 | DHCP-резервирование нод | **все пять в силе и bound**: 01→.250, 02→.253, 03→.254, 04→.252, **05→.251 (2026-11-08)** (грабля client-id/DUID при переустановках — `mikrotik-setup.md` §3.5) |
| 6 | Внешняя доступность | **Cloudflare Tunnel работает (ADR-0004), E1–E5 + E7**: зона demo-ai-lab.ru в Cloudflare (NS irena/newt, DNSSEC выключен), туннель `demo-lab-ingress-v2` (пересоздан 2026-10-23); **с 2026-10-24 коннектор живёт на внешней VM (SberCloud), стендовые коннекторы `disable --now`** — uplink площадки режет порт `7844` (R1: 530/1033 со всех точек, сессии по 1–10 мин), с сети VM те же 4 сессии стоят без ротаций. Origin доводится SSH reverse-hop (`vmhop.service` на 02/03) → `haproxy` (loopback VM) → `https://127.0.0.1:19443` в tunnel-ingress; зона **Full(strict)**, origin — LE wildcard, hop TLS не терминирует. Приёмка: 200 из 8 стран (check-host), дрилл отказа hop-а — failover за ~4 c. Остаток: VM — единая точка отказа; E6 (Access) снят 2026-10-24 — служебные хостнеймы только в LAN |
| 7 | Дисковая модель нод | **полностью готова (F0 2026-10-17)**: root-LV 100G на 01/02/03, 210G на k8s-04 (2026-10-27); LV longhorn 250G на 02/03/04, ext4, fstab, `/var/lib/longhorn` смонтирован; k8s-01 без LV — вне пула (ADR-0003); open-iscsi ×4 |
| 8 | k8s-01 (добавлена 2026-10-17) | роль назначена (ADR-0003): control-plane #1 + компьют-heavy; **подготовка узла закрыта F0 (2026-10-17)**: pb-k8s-prep прогнан (containerd 2.2.1+CRI, swap off, `/etc/hosts`) — см. #3 |
| 9 | Endpoint API (controlPlaneEndpoint) | **работает (2026-10-18): kube-vip VIP `.240`** (ADR-0003 вариант A, `ansible/pb-k8s-vip.yaml`); лидер — любой из CP (сейчас k8s-03), VIP выведен из DHCP-пула роутера |
| 10 | Guardrail: Higress + `ai-data-masking` + Qwen3Guard | **решение 2026-10-24, ADR-0006 — три части**: плагин `ai-data-masking` (маскирование ПДн со `restore` в ответе), модель-страж **`Qwen3Guard-Gen-4B`** (≈12.7 GiB на 5070 Ti, `util 0.80`; рев. 2026-11-02 — 4B вместо 0.6B, 0.6B остаётся исполнителем кейса 03 под тем же внешним ID, Apache-2.0, `Safe/Controversial/Unsafe` + `PII`/`Jailbreak`) в GPUStack и кастомный Wasm-плагин `ai-qwen-guard` (готового плагина под модель в каталоге Higress нет); рубильник — аннотация Ingress. Класс `guardrails-ai`, NeMo Guardrails, FMS Guardrails Orchestrator, Presidio и модели Llama-Guard/ShieldGemma/WildGuard рассмотрены и не взяты (причины — ADR-0006). Спека развёртывания `architecture/specs/guardrail-spec.md` **не написана** |
| 11 | Keycloak (SSO) | **установлен 2026-10-27, K1–K7 закрыты — каноническая строка #15 ниже** (спека `architecture/specs/keycloak-spec.md`): `architecture/specs/keycloak-spec.md` — Keycloak 26.8.1 ×2 + PostgreSQL 17.11 в ns `keycloak` на паре k8s-02/03 (soft-affinity; k8s-04 исключён — там GPUStack), Argo CD (`gitops/infra-apps/keycloak/`), `auth.demo-ai-lab.ru`, realm `dev` + `user-test`/`admin-test`; приёмка K1–K7. Решения 2026-10-24: Keycloak доступен глобально без Access (план Б), **сужен 2026-11-04: пользовательские пути публичны, `/admin*` и `/realms/master*` — только LAN**; SSO — **GPUStack да, Argo CD нет**; **HA БД не делаем** (демо, не прод). Пины сверены на стенде. |
| 12 | MCP Registry (каталог MCP-серверов) | **установлен 2026-10-28** (`kubectl apply -f gitops/infra-apps/mcp-registry/`, ns `mcp-registry`; Application `mcp-registry` под Argo — Synced/Healthy, замер 02.11): поды 2/2 Running, `Certificate mcp-demo-tls` Ready (LE YR1), `/v0/health` → 200, `/v0/version` = 1.8.6, `/docs` → 200, витрина `/` отдаёт HTML, PG — 17 миграций, `top`: registry 9Mi / postgres 43Mi; из LAN (`.230`) и через edge — 200. **каталог наполнен 2026-10-28**: `ru.demo-ai-lab/docling@1.0.0` (`remotes[0].url = https://doc.demo-ai-lab.ru/mcp`) опубликован через DNS-проверку (apex-TXT в Cloudflare), `server.json` — `gitops/mcp-servers/docling/`. Приёмка: M1–M5, M7 зелёные; M6 (OIDC-обмен) красная из-за M-O1; M8 не снята. Argo: каталог в git, Application `mcp-registry` создан ApplicationSet (selfHeal; объекты, поставленные kubectl до push, adopt'нуты). Спека: `architecture/specs/mcp-registry-spec.md` — `modelcontextprotocol/registry` **1.8.6** (индекс `sha256:f11600…`, amd64 `sha256:0901da…`, 7,7 MiB, Chainguard static) + PostgreSQL 16-alpine в ns `mcp-registry` на паре k8s-02/03, адрес `mcp.demo-ai-lab.ru`, развёртывание Argo CD (`gitops/infra-apps/mcp-registry/`), публикация по доменному токену (`ru.demo-ai-lab`), админ — OIDC Keycloak (клиент `mcp`). Сверено с исходниками: **health только `/v0/health`**, на `/` — **встроенная витрина** («Recently Updated» за час + поиск), `/metrics` и `/docs` на том же хосте, миграции БД на старте, образ без shell (пробы только `httpGet`). Приёмка M1–M8. Открыто: M-O1 — клиент `mcp` в сиде confidential, реестру нужен публичный (`id_token`) |
| 13 | GPUStack (инференс, шаг 1) | **установлен 2026-10-28, G0–G7 закрыты** (спека v1.10): `architecture/specs/gpustack-spec.md` — чарт `gpustack-chart` 2.2.3 (OCI, helm с консоли; `higress-core.enabled=false`, `gateway.ingressClassname=higress`), ns `gpustack`, сервер StatefulSet ×1 + PVC 20Gi на паре 02/03, GPU-воркер `k8s-04` (`runtimeClassName: nvidia`, hostNetwork 10150), CPU-воркер только на 01, `api.demo-ai-lab.ru`, приёмка G0–G8. **Блокер, найденный замером (снят в G1):** handler `nvidia` в containerd не применён (старый `99-nvidia.toml` в схеме version 2 не читается containerd 2.2.1) — RuntimeClass создать мало, нужна правка drop-in (G1). Первичный план ADR-0007 (util 0.75, резидентный набор) снят ревизией 2026-11-02: набор переключается по кейсам, чат идёт на util 0.68 (при 0.75 ASR падает по OOM); диск 04 расширен до 210 GB; раннер `cuda13.0-vllm0.25.1` (20.5 ГБ) — предтяжка обязательна. **Факт 28.10.2026:** чат `gemma-4-12B` (`--max-model-len 4096`, util 0.68, 12 668 MiB) + ASR `whisper-turbo` (CT2 int8, 2 294 MiB) резидентно на 5070 Ti, всего на карте = 14 943 из 16 311 MiB; SSO включён (клиент `gps`, issuer realm `dev`, Secret `gpustack-oidc`, апгрейд только через `ansible/gpustack-upgrade.sh`), API-путь `/v1/*` остаётся по ключу |
| 14 | Доставка образов | **прямой pull из облачных реестров (2026-10-24)**: локальный реестр (`preload-registry` на консоли, порт 5050; адрес консоли с 28.10 — `.200`) и склад предзагрузки сняты — preload-registry/ и references/preload-registry.md удалены из репо, `env_health.py` больше реестр не проверяет. Mirror-конфиги containerd (`/etc/containerd/certs.d/*/hosts.toml` на всех 4 нодах + остаток `192.168.10.199:5050` на k8s-04) удалены, бэкап — `/root/certs.d.bak-20261024` на каждой ноде. Приёмка: `ctr -n k8s.io images pull docker.io/library/hello-world:latest` идёт напрямую, 9–24 с на ноду; контейнер реестра на консоли удалён, том `preload_registry` оставлен |
| 15 | Keycloak (SSO, `auth.demo-ai-lab.ru`) | **установлен 2026-10-27, K1–K7 закрыты**: `gitops/infra-apps/keycloak/` под Argo CD (Application `keycloak` — Synced/Healthy): Keycloak 26.8.1 ×2 на паре **k8s-02/03** (`jdbc-ping`, сессии в БД) + PostgreSQL 17.11 (PVC 8Gi Longhorn, SPOF принят), PriorityClass `demo-stand-critical`, отдельный `Certificate auth-demo-tls` (LE YR1) + Ingress Higress. Realm `dev`: роли `app-user`/`app-admin`(⊃)/`agent-service`, `user-test`/`admin-test`, клиенты `smoke-cli`/`gps`/`agent-runtime`/`mcp`; brute-force 5/60 c проверен живьём. **Пользовательские пути публичны, `/admin*` и `/realms/master*` — только LAN** (с 2026-11-04: Ingress `auth-admin` + два `WasmPlugin` `auth-admin-lan*`, `gitops/infra-apps/keycloak/31-ingress-admin-lan.yaml`; снаружи `403`, из LAN консоль работает). `KC_BOOTSTRAP_ADMIN_*` сняты, пароль админа ротирован (32 симв.). Drill: потеря пода и переход на 1 реплику — discovery LAN/edge 200 всё время. Secret'ы вне git (`scripts/keycloak_secrets.sh`), seed — `scripts/keycloak_seed.py`, бэкап `pg_dump` вне репо. |
| 16 | Open WebUI (`owu.demo-ai-lab.ru`, шаг 2) | **развёрнут 2026-10-28 через Argo CD** (`gitops/apps/owu`, Application `owu` — Synced/Healthy): чарт `open-webui` 17.0.0 / appVersion 0.12.0, **отрендерен в plain-манифесты** (у ApplicationSet `apps` нет helm-источника), values — `gitops/values/owu.yaml`; StatefulSet `owu-open-webui` ×1 на k8s-03, PVC 5Gi Longhorn, Service 80→8080, свой `Certificate owu-demo-tls` (LE). Факт рендера: при `persistence.enabled` чарт создаёт **StatefulSet**, а Service слушает **80**; `sso.oidc` → `OAUTH_*` из Secret `owu-oidc`. Ключ модели GPUStack — `demo-step2` (id 5, `gemma-4-12B` + `whisper-turbo`): из пода `owu` `/v1/models` → 200; LAN `/` → 200, `/api/config` отдаёт `oauth.providers.oidc=Keycloak`, `enable_signup=false`. Клиенты Keycloak `owu`/`spk` заведены сидом, `redirectUris` сверены admin-API. **Чат (28.10.2026):** Open WebUI прикладывает `tools` + `tool_choice: "auto"` к каждому запросу, и vLLM отвечал `400 "auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set` — падал любой диалог; вылечено на стороне GPUStack (модель `gemma-4-12B`: `--enable-auto-tool-choice`, `--tool-call-parser gemma4`; применение — только пересозданием инстанса), в `owu` правок нет. Проверка API: `tools`+`auto` → 200 с `tool_calls`, стрим 200. **Список моделей (28.10.2026):** whisper убран — ключ `owu-gemma` (только gemma, whisper → 403) + `model_ids` на подключении; `BYPASS_MODEL_ACCESS_CONTROL=true`, иначе внешняя модель видна только админу (SSO-юзер видел пустой список). `max_tokens` чата — `DEFAULT_MODEL_PARAMS` плоским словарём (`{"max_tokens": 2048}`), проверено обрывом на 2048. Тип остаётся `external` — «внутренняя» в owu = Ollama, у GPUStack такого API нет. Приёмка O4–O6 (вход SSO, edge, диалог в UI) не снята. **2026-11-03: RAG Open WebUI переведён на модели 780M через env** — `RAG_EMBEDDING_ENGINE=openai` + `bge-m3` (dim 1024), гибридный поиск + `RAG_RERANKING_ENGINE=external` + `bge-reranker-v2-m3`; 10 строк-перекрытий `rag.*` удалены из `webui.db`, ключ OWU переведён на `owu-all` (старым `demo-step2` эмбеддинги давали `403`). Спека — `architecture/specs/owu-spec.md` §7.4 |
| 17 | Speakr (`spk.demo-ai-lab.ru`, шаг 2) | **развёрнут 2026-10-28 через Argo CD** (`gitops/apps/spk`): PVC 20Gi Longhorn, Deployment `speakr` ×1 (`strategy: Recreate`, TCP-пробы 8899), Service, `Certificate spk-demo-tls`. ASR — GPUStack (`openai_whisper` → `/v1/audio/transcriptions`, `whisper-turbo`), ключ `demo-step2` доступен из пода (200); тексты (саммари, заголовки) **с 2026-11-02 — внешняя `deepseek-flash` через `llm-svc.`** (DLP `ai-data-masking` + страж fail-closed, ключ `llm-svc` в Secret `spk-secrets`): при лежащем страже маршрут отдаёт `503`, транскрипт при этом живёт. LAN: `/` → 302 на `/login`, `/login` 200; вход — SSO **и** локальная форма по `admin@demo-ai-lab.ru` (`SSO_DISABLE_PASSWORD_LOGIN=false`, решение владельца 28.10.2026: пароль — запасной вход на демо; при `true` форма отключена целиком). **28.10.2026:** вход «не проходил» из-за rate-limit `10/мин` на `/auth/sso/login`, который из-за `TRUSTED_PROXY_HOPS=2` считался на адрес пода Higress (общее ведро на всех) — hops → **1**, лимит стал по клиенту (`ratelimit ... (192.168.10.200)`); полный SSO-цикл `user-test`/`admin-test` → 200 на дашборде. Секреты — `Secret spk-secrets`/`spk-oidc` вне git (`spk-admin.local.md`, gitignored). **Транскрибация (28.10.2026):** `.aac` из диктофона валился не по звуку — GPUStack не принимает `audio/aac` и отвечает `400` **в теле при HTTP 200**, поэтому добавлен `AUDIO_UNSUPPORTED_CODECS=aac` (конвертация в mp3); вторым блокером были `TITLE/SUMMARY_MAX_TOKENS` 5000/3000 больше ctx модели — выставлены 1000/2500/1500, ctx GPUStack поднят 4096 → 8192. Запись 1 (24 мин): `COMPLETED`, транскрипт 14 835 симв., саммари 4 463 симв., 55 с. Осталось из S5–S6: загрузка 100+ МБ через edge и лимиты Higress |
| 18 | Docling Serve + MCP (`doc.demo-ai-lab.ru`, шаг 2) | **развёрнут 2026-10-28 через Argo CD** (`gitops/apps/doc`): под `docling` 2/2 (`docling-serve` 5001 + `docling-mcp` 8000 в `CONVERSION_MODE=remote` через loopback), PVC 10Gi Longhorn `/modelcache` = 851 MiB (layout, tableformer, rapidocr `eslav`+`ch`, easyocr, tessdata `rus`/`eng`), предзагрузка — **Argo-hook** `Sync` wave -1 (обычный Job не годится: `spec.template` иммутабелен после того, как контроллер дописал `controller-uid`, ArgoCD падал на патче), Ingress `/mcp`→8000 и `/`→5001, `Certificate doc-demo-tls`. Факт: `/health` `/ready` `/livez` → 200, MCP `initialize` → 200; русский скан → кириллица в `md_content` за ~4 с с `ocr_preset=ru-en` (tesserocr `rus+eng`) и `rapid-ru` (RapidOCR `eslav`); **без `ocr_preset` сервер идёт `auto`** (RapidOCR `ch`) — кириллица распознаётся плохо, `default_ocr_preset=ru-en` работает только для UI/явного пресета, MCP-адаптер пресет не передаёт (открытый пункт D4) |
| 19 | Yandex Search MCP (`ysrch.demo-ai-lab.ru`, шаг 2) | **развёрнут и опубликован 2026-10-28** (`gitops/apps/ysrch`, ns `ysrch`): `msklv/yandex-search-mcp-server` **v1.3.1** (индекс `sha256:6e0127…`, amd64 `sha256:2d3e08…`, 63,3 MiB, `python:3.10-slim`) — StreamableHTTP `/mcp`, порт 8766, TCP-пробы (`GET /mcp` = 406 by design), `PriorityClass demo-stand-critical`, soft-affinity на пару 02/03, `Certificate ysrch-demo-tls` Ready + Ingress Higress. Ключ Yandex Search API — Secret `yandex-search` (`scripts/yandex_search_secrets.sh`, файл `yandex-search.local.md` вне git). **Грабля:** SDK `mcp` 1.29.1 валидирует Host → через Higress `421 Invalid Host header`, поэтому запуск идёт ConfigMap-обёрткой с `transport_security = None` (правка в форке — открытый пункт Y-O1 спеки). Факт: `initialize`/`tools/list` (`web_search`, `gen_search`, `image_search`, `web_search_async`, `get_operation`, `image_search_by_image`), `web_search` → 694 симв., `gen_search` → 3,4 КБ с `FOLDER_ID`; из LAN и через edge — 200. В каталоге MCP — `ru.demo-ai-lab/yandex-search@1.0.0`. Спека — `architecture/specs/ysearch-spec.md` |
| 21 | Проксирование внешнего LLM (`llm.` и `llm-svc.`, шаг 3) | **развёрнуто 2026-10-29, два входа**: `llm.` — JWT Keycloak realm `dev` (`client_credentials`) → `jwt-auth` + `opa` (`aud`/роль); `llm-svc.` — статический `x-api-key` (consumer `llm-svc`, переименован из `llm-test.` 2026-11-01) для сервисов без Keycloak-клиента; на обоих — `ai-data-masking` → `ai-qwen-guard` (fail-closed) → `ai-proxy` (`provider.type: deepseek`, ключ в Secret) → `ai-token-ratelimit`. Факт 2026-11-01: `llm-svc` `/v1/models` → `200` с ключом и `401` без, `llm.` без токена → `401`. Спека `architecture/specs/llm-proxy-spec.md` (v1.3), решение ADR-0008; **не снято только P4-стрим** (SSE ≥180 с, критерии в §4 спеки). **2026-11-02: развитие JWT-пути `llm.` приостановлено (ревизия ADR-0008) — в работе и в демо только `llm-svc.` со статическим ключом; маршрут `llm.` не снят, `/v1/models` без токена по-прежнему `401`**. Побочное 2026-11-01: reload конфига шлюза добил Higress-gateway на лимите 2048Mi (OOM) — лимит поднят до 3072Mi в `ansible/values-f8.yaml`, там же `rollingMaxSurge: 0` (дефолтные 100% с anti-affinity давали мёртвый rollout). **2026-11-05:** предел тела запроса на llm-хостах 32 768 B (h1) / 65 535 B (h2) → **1 МиБ** — шлюз отбивал RAG-чаты OWU локальным `413 Payload Too Large` (тело 33 617 B; OWU ходит aiohttp по HTTP/1.1). Правка в `higress-config` подхвачена через xDS без пересоздания подов; замеры, обоснование размера и оговорка о дрейфе с helm-релизом — `architecture/specs/llm-proxy-spec.md` §2.1, симптом в OWU — `architecture/specs/owu-spec.md` §7.6 |
| 23 | RAG-пара на 780M (k8s-01) | **`bge-m3` + `bge-reranker-v2-m3` — модели GPUStack, `running` на 780M узла k8s-01**: бэкенд `vllm-rocm-igpu-custom` (образ `runner:rocm7.2-vllm0.25.1`, `HSA_OVERRIDE_GFX_VERSION=11.0.0`), селектор `k8s-01:rocm:0`, fp16-веса (`claim` 1.77 GiB), флаги `util 0.12 / ctx 4096 / max-num-seqs 8` (снижено с 32 — большие батчи эмбеддингов давали `MES timeout` → `GPU reset`). Предпосылки на ноде: ROCm userspace в `/opt/rocm` (14 МБ) и **UMA 8G в BIOS** (стоково 512 MiB — карта 0.5 GiB и `No suitable workers`); после ребута vram 8.00 GiB, ОС 23.26 GiB, GTT 11.63 GiB. Замер 04.11: GTT **2.77 из 11.63 GiB** на пару, `/v1/embeddings` 200 (dim 1024, тёплый 0.10–0.13 с), `/v1/rerank` 200 (тёплый 0.13–0.21 с) через `api.demo-ai-lab.ru`; 5070 Ti не задействована. Процедура и грабли — `gpustack-spec` §4.6, ADR-0007 рев. 2026-11-04, замеры — `hardware-inventory.md` снимок 2026-11-04 |
| 22 | Набор моделей на сцене (2026-11-02) | **переключение моделей — механика показа, а не скрытая настройка** (решение владельца; ADR-0007, рев. 2026-11-02): человек в UI GPUStack (`Model Service → Deployments → Stop/Start`) ставит набор кейса — 01 `Qwen3.8-27B-UD` (15.1–15.6 GiB, эксклюзивно), 02/05/06 страж `Qwen3Guard-Gen-4B` (≈12.7 GiB, `util 0.80`), 03 страж `0.6B` + `whisper-turbo` (≈3.7 GiB), 04 `GLM-OCR` (**в каталоге GPUStack ещё нет**), 05 дополнительно `bge-m3` + реранк на 780M; `gemma-4-12B` — резерв вне сцены (util 0.68 + ASR = 14 943 из 16 311 MiB). Порядок и сетка переключений — `cases/README.md` |

| 24 | Гейт служебных UI + `lng.` (2026-11-04) | **`argo.`, `hgc.`, `lng.`, `mon.` — только LAN** (решение владельца, `external-access-spec` E9): два `WasmPlugin` `ip-restriction` в `higress-system` (`gitops/infra-apps/infra/lan-only-ui.yaml`) — allow по `X-Forwarded-For` + страховка по настоящему peer'у без `172.16.0.0/12` (там лежат адреса edge Cloudflare); плагин собран из тега `v2.1.9` и раздаётся из тома `wasm-store` (`scripts/infra_wasm_plugins.sh`, OCI-реестр Higress анонимно не тянется). **Longhorn UI опубликован как `lng.demo-ai-lab.ru`** (`Certificate longhorn-demo-tls`, LE `YR2` до 02.02.2027; Ingress в ns `longhorn-system` → `longhorn-frontend:80`). Факт 2026-11-04: из LAN `argo`/`hgc`/`lng` → `200` (у `lng` SPA и `/v1/volumes`), через edge → `403` `{"message":"LAN only"}` (детали и замеры — локальный отчёт ИБ 2026-11-05); пользовательские хосты не задеты (`owu` 200, `doc` 307, `mcp` 200). Проверка — строка `Allowlist служебных UI` в `k8s_health.py`; грабли (`defaultConfig` глобальный, `matchRules[].config` обязателен) — `external-access-spec` E9.2. **Longhorn UI дополнительно закрыт логином** (E9.3): `WasmPlugin basic-auth`, из LAN без кредов `401`, с кредами `200`; креды — `lng-admin.local.md` (gitignored), объект рендерит `scripts/longhorn_ui_auth.sh` вне Argo; остаточные риски зафиксированы в E9.3 и локальном отчёте ИБ. Тем же днём закрыты админ-пути `auth.`: Ingress `auth-admin` (ns `keycloak`) + `auth-admin-lan*`, скоуп по имени Ingress — из LAN `/admin/` 302, через edge `403`, `/realms/dev/*` публичен (`keycloak-spec` §4.5) |
| 25 | Кейс 07: картинка на своей карте (2026-11-04) | **развёрнут и подтверждён**: `Z-Image-Turbo` — модель GPUStack id 15 (источник HF `Tongyi-MAI/Z-Image-Turbo`, 32.9 GB FP32 на диске), бэкенд `vLLM 0.22.1 --omni`, раннер `gpustack/runner:cuda13.0-vllm0.22.1`; публикация наружу — `ModelRoute` id 12 (без маршрута `/v1/*` даёт `404 Model not found` — в GPUStack 2.2 имена в `/v1` живут только маршрутами). VRAM: `claim` снижен 23 → **15 GiB** (`GPUSTACK_MODEL_VRAM_CLAIM`), факт **12.4 GiB** простой / **15.3 GiB** пик на 1024². Замер через `api.demo-ai-lab.ru`: `POST /v1/images/generations` → 200; **сценический режим — 8 шагов и 512×512: 3.0–3.6 с** (решение владельца 04.11, текст в кадре читается); 1024×1024 при 8 шагах — 12.8–13.4 с, 6 шагов — 10.4 с, 4 — 7.7 с; `tea_cache` выигрыша не даёт. **Квант — только fp8:** `--quantization int8` падает на sm_120 (`Int8 not supported on SM120`), хотя документация vLLM-Omni помечает Blackwell как поддерживаемый. Диск: перед деплоем 81 GB свободно, после весов и раннера 63 GB; по ходу pull kubelet выселил под по `ephemeral-storage` (порог 15 % = 35.4 GB) и image-GC снёс образы раннеров остановленных моделей (rocm `bge`, vLLM 0.25.1 стража/`gemma`, VoxBox, beellama) — перекачиваются при старте. Критерий «1024², ≤10 с» из первой редакции снят замером: выбраны 8 шагов и 512×512 (≤4 с). Детали, рецепт и грабли — `cases/07-image-gen.md`; ADR-0007 рев. 2026-11-04 |
| 26 | k8s-05 (добавлена 2026-11-08) | **введена в кластер как worker без taint'а (2026-11-08)**: GMKtec NucBox K12 (R7 H 255 8C/16T, iGPU Radeon 780M / Phoenix3 — тот же SoC, что k8s-04, дискретной GPU нет), 16 GB DDR5-5600 (1×16 из 2 слотов, max 64 GB), NVMe 1 TB Netac (износ 0 %, power-on 0 ч), 2× Realtek RTL8125 2.5GbE (`eno1` 2500 Мбит/с, `enp2s0` down); DHCP-резервация `.251` `bound`, hostname `k8s-05`. **F0 выполнен** (`pb-k8s-prep`, 2026-11-08: swap off, containerd 2.2.1+CRI systemd-cgroup, modules/sysctl, `/etc/hosts` всех нод), **kubeadm/kubelet/kubectl 1.35.9-1.1** (hold, репо pkgs.k8s.io v1.35), join через VIP `.240` → `Ready`, taints нет. **Longhorn: `allowScheduling=false`** — LV под `/var/lib/longhorn` не резан, решение по диску за владельцем (сейчас нода вне пула реплик, как k8s-01). 48 пакетов апгрейда не применялись (вне F0). Замер железа — `hardware-inventory.md` (снимок 2026-11-08) |
| 27 | Восстановление 02/03 и отказ 04.11–08.11 (2026-11-08) | **корень четырёхдневной деградации — `base_runtime_spec` на k8s-02/03** (`/etc/containerd/base-ulimits.json`, внедрён 04.11 по рецепту F8 ради fd-лимита Envoy): в файле не было `process.cwd` → все новые контейнеры падали `runc create failed: Cwd property must not be empty` (Longhorn-менеджеры/CSI/instance-manager, шлюз, затем postgres и всё, что пересоздавалось); поле `hostname: "runc"` из `runc spec` уезжало в UTS песочницы hostNetwork-подов → **kernel hostname нод стал `runc`**, kube-vip на 02/03 получил одинаковую identity (лиз `plndr-cp-lock` = `runc`) и оба узла держали `.240`/`.230` → ARP-конфликт; caps CRI берёт **не** из базового спека, поэтому root в контейнерах потерял `CAP_FOWNER/CHOWN` (`postgres: chmod … Operation not permitted`). Лечение 2026-11-08: `base_runtime_spec=''`, рестарт containerd, `hostnamectl set-hostname`, пересоздание kube-vip (плюс добить orphan-процессы старых подов), CSI, longhorn-manager; `default_ulimits` в containerd 2.2 не существует (ключ игнорируется). Итог: **15 PASS / 1 WARN / 0 FAIL**, Longhorn Ready ×4, шлюз 2/2, Keycloak/MCP/GPUStack подняты. Разбор и грабли — `health-runbook` §10d, переписанный рецепт fd — `k8s-install-spec` F8 |
| 30 | Извлечение веб-страниц Firecrawl (`fc`, шаг 2+) | **развёрнут 2026-11-10 на k8s-05** (`gitops/apps/fc/`, ns `fc`, 5 подов; спека `architecture/specs/firecrawl-spec.md` v1.1): Firecrawl **2.10.19-production** + `playwright-service` + RabbitMQ 3.13.7 + `nuq-postgres` + Redis 8.10.1; все образы по amd64-дигесту (суммарно ≈5 GB, предтяжка на ноду ~90 с), PVC 5Gi (PG) и 2Gi (очередь) Longhorn, `PriorityClass demo-stand-critical`. **Размещение изменено против спеки v1.0:** все пять подов закреплены `required`-ом на **k8s-05** (32 Gi, без инференса и шлюза), anti-affinity api↔playwright снят — на `preferred`-скоринге он уводил api на k8s-04 к GPUStack. **Внешнего имени нет:** только `ClusterIP` (`firecrawl-api.fc.svc.cluster.local:3002`), доступ из подов стенда или `port-forward`; Ingress `fc.` с key-auth и MCP-обёртка — фаза C6. Приёмка C1–C5: scrape example.com → `success:true` 958 симв., SPA `quasar.dev` 6,9 КБ, ru-wiki «Москва» 632 КБ кириллицей, 5/5 параллельных scrape (0,6–2,5 с), `activePages` → 0; guard приватных адресов отбивает `192.168.10.230` и `*.svc.cluster.local` (ответ 500 `SCRAPE_ALL_ENGINES_FAILED`, в логах `Connection violated security rules`) — страницы стенда через него не читаются, для них Chromium в поде `her`. Память простоя: api 2,6 Gi (лимит поднят 2 → 3Gi: с 2Gi под уходил в `OOMKilled`), playwright 233 Mi, rabbitmq 142 Mi, pg 92 Mi, redis 5 Mi. Грабли установки: `nuq-postgres` требует `args`, а не `command` (иначе затирается `docker-entrypoint.sh` и postgres не стартует root'ом); у pg/rabbitmq снят контейнерный `securityContext`. Секреты — Secret `fc-secrets` из `scripts/firecrawl_secrets.sh` (`firecrawl.local.md`, gitignored). Ставили `kubectl apply`, затем каталог в git — Application `fc` создан ApplicationSet `apps` и Sync'нулся (adopt без пересоздания подов). Лицензия AGPL-3.0 (внутреннее использование). Открыто: Q-C1 (потребитель вне `her`), Q-C2…Q-C5, фаза C6 |
| 31 | k8s-05 после join: пороги kubelet | **на ноде дефолты** — `imageGCHigh/Low` 85/80, `imageMinimumGCAge` 2m, eviction `imagefs.available 15%`, `nodefs.available 10%` (замер 2026-11-10, `/api/v1/nodes/k8s-05/proxy/configz`); у 01–04 по `pb-kubelet-imagegc.yaml` — 90/85, 10m, 8%/8%. Плейбук на 05 не гонялся (join был позже прогона), в проверочном цикле плейбука нода теперь есть. Риск: kubelet на 05 выселяет поды раньше и агрессивнее чистит образы — Firecrawl (5 подов) и Kuvasz живут именно там. Действие: прогнать `ansible-playbook -i hosts.cluster.yml pb-kubelet-imagegc.yaml` (нужны `K8S05_USER` и sudo-пароль из приватного хранилища) |
_Номера пунктов — якоря ссылок из других доков и не переиспользуются: `#20` — Langfuse, выведен из
проекта 2026-11-02; `#29` — каталог скиллов SkillHub, снят 2026-11-10 (каталог скиллов живёт отдельным
репозиторием, ADR-0010), поэтому в таблице пропуск._

## 8. Файлы

- `architecture/README.md` — обзор каталога: рендеры диаграмм (C1, C2, полная схема) и индекс спек.
- `architecture/specs/` — спецификации сервисов и инфраструктуры (k8s-install, external-access,
  keycloak, gpustack, owu, spk, doc, ysearch, mcp-registry, llm-proxy, health-check).
- `README.md` — входная точка: стратегия выступления (семь кейсов), четыре части лаборатории
  и исходная точка демо.
- `cases/README.md` — программа выступления: порядок кейсов, наборы моделей, переключения, готовность.
- `architecture/specs/health-check-spec.md` — проверка готовности стенда слоями (образы, модели,
  прерогативы фичи, маршруты и доки).
- `references/health-runbook.md` — ручной проход слоя 1 и восстановление (power-cycle, VIP, вебхуки, туннель).
- `network-map-detail.md` — карта сети (живой аудит).
- `mikrotik-setup.md` — рецепт настройки MikroTik (для повторения стенда; без секретов).
- `inventory.local.md` — скрытая инвентаризация (MAC, доступы) — не в git.
- `architecture/architecture-c1.excalidraw` — контекст C1: стенд одним блоком, акторы
  (зритель, оператор), публичный вход через внешнюю VM (haproxy `:443`, SNI-passthrough → SSH-hop)
  и внешние системы (GitHub, реестры образов, Yandex Search API, DeepSeek Platform).
- `architecture/architecture-c2.excalidraw` — целевой C2 (исходник слоёв).
- `architecture/ARCHITECTURE.md` — этот документ.
- `architecture/endpoints.md` — все публичные адреса короткими именами + кто за SSO (`owu`, `rag`, `doc`, …).
- `architecture/equipment.md` — публичный список оборудования стенда: мини-ПК, GPU и док-станция с БП,
  сеть (роутер, коммутатор, IP-KVM), два выделенных БП, консоль, накопители.
- `architecture/hardware-inventory.md` — инвентарь железа: диски, износ/ресурс (SMART),
  прошивки, TBW-документация — снимки по датам.
- `architecture/demo-ai-lab-architecture.html` — диаграмма (физ. + логический слой).
- `architecture/specs/k8s-install-spec.md` — спецификация bootstrap'а кластера (kubeadm→CNI→хранилище).
- `architecture/specs/owu-spec.md`, `architecture/specs/spk-spec.md`, `architecture/specs/doc-spec.md` — спеки
  демо-сервисов шага 2 (Open WebUI, Speakr, Docling + его MCP-сервер на `/mcp`): пины, размещение,
  фазы O/S/D, риски.
- `architecture/specs/external-access-spec.md` — спецификация внешнего доступа (Cloudflare Tunnel,
  MikroTik split-DNS, TLS Full strict; приёмка E1–E5, ADR-0004; E6 Access снят; **E7 — второй egress
  через внешнюю VM + SSH-hop**).
- `architecture/specs/keycloak-spec.md` — спецификация SSO (Keycloak 26.8.1 ×2 + PostgreSQL 17.11 на паре k8s-02/03,
  деплой через Argo CD, `auth.demo-ai-lab.ru`, realm `dev`; приёмка K1–K7; креды — `*.local.md`, не в git).
- `architecture/specs/gpustack-spec.md` — спецификация GPUStack 2.2.3 (шаг 1 демо): helm-чарт + values в
  `ansible/values-gpustack.yaml`, сервер на паре 02/03, GPU-воркер `k8s-04` через `runtimeClassName: nvidia`,
  раннер `cuda13.0-vllm0.25.1`, модели AWQ, `api.demo-ai-lab.ru`; приёмка G0–G8, блокер G1 — handler
  `nvidia` в containerd; креды — `gpustack-admin.local.md`, не в git.
- `architecture/specs/ysearch-spec.md` — Yandex Search MCP (`ysrch.demo-ai-lab.ru`, шаг 2): форк
  `msklv/yandex-search-mcp-server` v1.3.1 по digest, StreamableHTTP `/mcp`, TCP-пробы,
  ConfigMap-обёртка против `421 Invalid Host header`, Secret ключа Search API; приёмка Y1–Y5.
- `architecture/specs/mcp-registry-spec.md` — каталог MCP-серверов (шаг 2): MCP Registry **1.8.6** + PostgreSQL 16
  в ns `mcp-registry` на паре 02/03, `mcp.demo-ai-lab.ru` (витрина на `/`, API `/v0`), публикация через
  доменную проверку `demo-ai-lab.ru`, админ — OIDC Keycloak; приёмка M1–M8, открытый пункт M-O1 (клиент
  `mcp`); креды — `mcp-registry.local.md`, не в git.
- `architecture/specs/firecrawl-spec.md` — Firecrawl self-host (`fc`, шаг 2+; **спека, не установлено**):
  «URL → markdown» для потребителей без браузера — api `2.10.19-production` + `playwright-service` +
  RabbitMQ + nuq-postgres + Redis, пины по amd64-дигестам, ClusterIP-only (Ingress и MCP — фаза C6),
  guard приватных/LAN-адресов включён; приёмка C1–C6, секреты — `firecrawl.local.md`, не в git.
- `architecture/specs/llm-proxy-spec.md` — проксирование LLM наружу (`llm.`/`llm-svc.`, шаг 3, ADR-0008):
  `jwt-auth`/`key-auth` + `opa`, `ai-data-masking`, `ai-qwen-guard` (fail-closed), `ai-proxy` (deepseek),
  `ai-token-ratelimit`; приёмка P1–P6 (не снят P4-стрим), с 2026-11-02 в работе `llm-svc.`.
- `adr/` — реестр архитектурных решений 0001–0010 (+ `adr/README.md` — правила и сводная таблица).
- `references/` — операционные runbook'и и справочники: `references/health-runbook.md`, `references/storage-model.md`,
  `references/gpu-scheduling-options.md`, `references/service-spec-authoring.md`, `references/keycloak-sso.md`.
- `beellama-rtx5060/` — справочник хостового прогона BeeLlama на RTX 16 ГБ (рецептура 5060 Ti, действующие замеры — 5070 Ti; не читать без явного запроса, AGENTS.md).
- `old/` — архив выведенных из эксплуатации материалов (не читать без явного запроса, AGENTS.md).
- `presentations/` — ассеты докладов (шаблон HighLoad++ 2026).
- `cases/01…07` — файлы семи кейсов (сценарий, блокеры, фолбэк).
