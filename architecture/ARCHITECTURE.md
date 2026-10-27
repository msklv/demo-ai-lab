# demo-ai-lab — Архитектура стенда

> Демонстрационный AI Lab: визуализация работы ИИ-агентов и on-prem LLM-инференса.
> `network-map-detail.md` (живой аудит, актуализировано 2026-10-18),
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
  подключён к Tenda (L2, статическая агрегация портов 7–8, без LACP); ноды — на портах 1–6 Tenda.
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
| `k8s-04` | 192.168.10.252 | `enp3s0` — **не используется** | R7 H255 8C/16T · **28Gi** · NVMe 477G (root-LV 100G) · **GPU RTX 5060 Ti 16G** | worker: LLM-инференс + сервисы (ADR-0003) |
| This Mac | 192.168.10.188 (статик-лиз) | — | — | консоль: ssh, kubectl, диаграммы |

_Диск (пересмер 2026-10-17): на всех нодах NVMe 512GB-класса (476.9G, «AirDisk 512GB SSD»,
на k8s-01 — «ZSPEED SSD 512GB»). После переустановки 02/03 все четыре узла однотипны:
root-LV 100G, свободно в VG ~374G. Целевые LV 250G на 02/03/04; k8s-01 вне пула Longhorn
(износ диска) — ADR-0002 + ADR-0003._
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
| Пользовательские сервисы | Speakr, RAGFlow, Open WebUI, OCR·Docling, BI | транскрибация, RAG, UI к LLM, разбор документов, отчёты |
| Вспомогательные | **MCP Registry** (`mcp.`, self-hosted `modelcontextprotocol/registry`) — каталог MCP-серверов (публикация — доменная проверка `demo-ai-lab.ru`; Keycloak — админ/права публикации; вызовы — Higress); каталог скиллов, Langfuse, Data Catalog | инфраструктура агентов, трассировка LLM, каталог данных |
| Данные и интеграции | Keycloak (SSO), Qdrant, PostgreSQL/ClickHouse, S3 | идентичность, векторы, реляционное/колоночное, объекты |
| Вычислительный | **GPUStack v2.2.3** (on-prem LLM, OpenAI-API; версия зафиксирована, ADR-0001); инференс — раннер каталога GPUStack: выбран **vLLM** `gpustack/runner:cuda13.0-vllm0.25.1`, SGLang доступен, не используем; Лайт-LLM прокси | инференс |
| Guardrail | **Higress + `ai-data-masking` + Qwen3Guard-Gen-0.6B** (ADR-0006, 2026-10-24): маскирование ПДн и словарный блок на шлюзе, классификация `Safe/Controversial/Unsafe` моделью-стражем 0.6B (Apache-2.0, 1.41 GiB, категории `PII`/`Jailbreak`) через кастомный Wasm-плагин `ai-qwen-guard`; отдельного guard-сервиса нет | модерация входа: ПДн, инъекции/джилбрейк; рубильник — аннотация Ingress |
| Кластер и эксплуатация | Argo CD (GitOps), k8s ingress, Мониторинг (метрики/логи/трейсы) | деплой и наблюдаемость |

**Лайт-LLM прокси** — внешний эgress к публичным LLM с сокрытием содержимого
запросов (когда on-prem модели недостаточны).

**MCP Registry** (решение 2026-10-24: **ставим для демо**) — self-hosted официальный
`modelcontextprotocol/registry` (Go + PostgreSQL): каталог MCP-серверов, публикация своих серверов,
API `/v0` + `/docs`; внешний адрес `mcp.demo-ai-lab.ru`, ns `mcp-registry`, пара k8s-02/03,
развёртывание через Argo CD. **Роль строго каталог:** вызовы инструментов идут через Higress
(`mcp-server`: REST→MCP, `mcp-proxy` по `remotes`-URL из реестра, `allowTools`). Публикация —
доменная проверка `demo-ai-lab.ru` (неймспейс `ru.demo-ai-lab`); **OIDC в реестре
(`MCP_REGISTRY_OIDC_*`) закрывает только админский доступ и права публикации** — владение
неймспейсом через Keycloak не выдаётся. Пины, env, приёмка — `architecture/mcp-registry-spec.md`;
ADR — `adr/adr-0005-mcp-registry-and-higress.md`.

## 4. Ключевые потоки

1. **Интерактивный LLM**: пользователь → ingress (SSO через Keycloak) →
   Open WebUI → GPUStack (OpenAI-API) → модель (on-prem).
2. **Агент**: Hermes Agent → каталог скиллов / MCP-серверов → вынесенные
   рантаймы (ограниченное исполнение) → инструменты и пользовательские
   сервисы; все LLM-вызовы → трейсы в Langfuse.
3. **RAG**: документ → OCR·Docling → RAGFlow → Qdrant;
   запрос к LLM → retrieval → ответ (Open WebUI / агент).
4. **Транскрибация**: аудио → Speakr → текст → S3 → BI (отчёты).
5. **Внешний LLM** (опционально): сервис → Лайт-LLM прокси (сокрытие
   содержимого) → внешний поставщик; инференс наружу.
6. **GitOps**: GitHub (репозитории, Actions) → Argo CD → k8s (деплой);
   образы — **прямо из облачных реестров** (Docker Hub / ghcr / quay) pull'ом с ноды, локального
   зеркала и склада предзагрузки нет (решение 2026-10-24).
7. **Наблюдаемость**: Мониторинг → метрики/логи/трейсы кластера и сервисов;
   LLM-трейсинг — Langfuse.
8. **Доступ к стенду**: наружу выставлен `api.demo-ai-lab.ru` (GPUStack API).
9. **Guardrail (ADR-0006, решение 2026-10-24)**: сервис/агент → guard-маршрут Higress →
   `ai-data-masking` (маскирование и блок ПДн/словарных запретов, `restore` в ответе) →
   кастомный Wasm-плагин `ai-qwen-guard` → Qwen3Guard-Gen-0.6B в GPUStack
   (`Safety: Safe|Controversial|Unsafe`, категории `PII`/`Jailbreak`) → в модель идут только
   прошедшие проверку запросы; рубильник — аннотация Ingress, событие — в логе шлюза.
   Облачных модераторов и отдельного «guard-сервиса» в архитектуре нет: всё, что проверяет контент
   моделью через внешний сервис (endpoint + ключи + egress), отклонено по условиям закрытого контура.
   Альтернативы (класс `guardrails-ai`, NeMo Guardrails, FMS Guardrails Orchestrator, Presidio,
   модели Llama-Guard / ShieldGemma / Granite Guardian / WildGuard) — `adr/adr-0006-guardrail-higress-qwen3guard.md`.

## 5. Размещение сервисов по узлам (план, ADR-0003 от 2026-10-17)

Железо (пересмер 2026-10-17, SSH, после переустановки 02/03): все четыре узла NVMe 477G,
root-LV 100G, ~374G свободно в VG. k8s-01 — лидер по RAM (32Gi) и одновременно самый
изношенный диск стенда (ZSPEED, 11% по SMART, резерв TBW ≈119 TB против ≈250+ TB у AirDisk,
`hardware-inventory.md`). Принцип разделения: **k8s-01 — память, 02/03/04 — диски Longhorn**.

| Узел | Роль в кластере | Что размещать | Почему |
|---|---|---|---|
| k8s-01 (.250) | **control-plane #1** + **компьют** | RAGFlow (разбор/индексация), OCR·Docling, qm + вынесенные рантаймы, BI, Langfuse (guardrail — плагины Higress, отдельного классификатора на узле нет, см. §4 поток 9) | 32Gi + 8C/16T — лидеры стенда; **вне пула реплик Longhorn** (износ диска): считаем здесь, данные — на томах 02/03/04 |
| k8s-02 (.253) | **control-plane #2** + **ingress (пара с 03)** + GitOps | apiserver/etcd/scheduler/CM; ingress-controller (**Higress** — ADR-0001) на ingress-VIP `.230`; Argo CD; qm; каталоги (сервисов, скиллов); **MCP Registry** (`mcp.`, ns `mcp-registry`); Лайт-LLM прокси | Маршрутизация сервисов — ingress-VIP `.230` + Higress (проброс WAN 80/443 отключён 2026-10-19); из 14Gi после control-плоскости (~2,5–3 Gi) остаётся ~11 Gi — ingress+лёгкие сервисы |
| k8s-03 (.254) | **control-plane #3** + **ingress (пара с 02, VIP `.230`)** + вспомогательные | Open WebUI, каталоги, лёгкие stateless-сервисы; Higress-gateway | Замыкает etcd-кворум 3/3; тот же бюджет ~11 Gi; second kube-vip (LB, `.230`) только на 02/03 |
| k8s-04 (.252) | **LLM-инференс + сервисы** (без taint'а) | GPUStack (RTX 5060 Ti, nodeSelector; BeeLlama в кластере не исполняется); **data-heavy: PostgreSQL, ClickHouse, Qdrant, MinIO (S3)**; Keycloak (SSO) — **не здесь**: по `keycloak-spec.md` §4.0 — пара 02/03, чтобы логин не конкурировал с инференсом | 28Gi — вторая RAM стенда; диск в пуле Longhorn → БД локальны к репликам; инференс защищается priorityClass + requests/limits сервисов, а не изоляцией; модели — hostPath; LV Longhorn 250G |

Ключевые правила (реализуются через taints/nodeSelector):
- **taint control-plane снять на k8s-01/02/03**; k8s-04 **без taint'а** (ADR-0003,
  правка владельца 2026-10-17) — сервисы живут и на нём. Размещение — nodeSelector по таблице.
- Инференс на k8s-04 защищается **приоритетом, не изоляцией**: nodeSelector закрепляет
  GPUStack, priorityClass выше сервисного (preemption при нехватке RAM),
  сервисы — строго с requests/limits.
- **Longhorn-реплики не на k8s-01**: `node.longhorn.io/create-default-disk="false"`,
  пул 02/03/04 × 250G (≈750G, ~375G полезных при replica=2).
- Подготовка нод закрыта **F0 (2026-10-17)**: swap off, containerd 2.2.1+CRI, `/etc/hosts`
  на всех четырёх (`pb-k8s-prep.yaml` прогнан, LV Longhorn нарезаны).
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

- Egress LAN → интернет — только через MikroTik (NAT masquerade).
- **Внешняя доступность — Cloudflare Tunnel (ADR-0004, Accepted 2026-10-18)**: зона
  `demo-ai-lab.ru` в Cloudflare Free, публичный DNS = IP edge (адрес площадки не публикуется);
  туннель `demo-lab-ingress-v2`: коннектор `cloudflared` (systemd) с 2026-10-24 — на **внешней VM**
  (SberCloud), origin доводится SSH reverse-hop (`vmhop.service` на 02/03) → `haproxy` →
  `https://127.0.0.1:19443`; стендовые коннекторы на 02/03 выведены (`disable --now` — R1, uplink
  режет `7844`). Ингресс → **`https://192.168.10.230`** (ingress-VIP) + `originRequest.caPool`
  и `originServerName`. Соединения только исходящие (QUIC/TCP 7844) — входящие в uplink
  не требуются; TLS на edge (Universal SSL) + **Full(strict)**: origin-сертификат Let's Encrypt
  wildcard через cert-manager (DNS-01 через Cloudflare) — выпущен и работает с 2026-10-19
  (`external-access-spec.md` E5); остаточный риск R1 — шторм uplink (530-окна) — там же.
  **Контур внешнего доступа целиком специфицирован в `architecture/external-access-spec.md`**
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
  `hgc.demo-ai-lab.ru` (консоль Higress) публикуются во внешний интернет
  (`external-access-spec.md` E9) — маршруты в Higress заведены; Longhorn маршрута наружу не имеет,
  туннель для него отдаёт 404. Наружу публикуются также демо-сервисы шагов 1–3.
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
| 1 | K8s-кластер | **поднят, F0–F9 закрыты 2026-10-19**: kubeadm 1.35.9, 3 CP + worker 04, все Ready; kube-vip `.240` (лидер — один из CP), etcd ×3, Cilium 1.20.3 full-KPR; Longhorn 1.13.0 (SC default r=2, k8s-01 SCHED=false); NFD 0.20.0 + метка GPU; cert-manager v1.21.2 + ClusterIssuer Ready; Argo CD 10.10.5 Synced/Healthy (selfHeal); ingress-VIP `.230` + Higress 2.1.9; приёмка F9 — health-gate + drill мастера и ingress-пары; **F10 metrics-server 3.14.0 установлен 2026-10-24** (2/2 на 01/04, APIService AVAILABLE, `kubectl top` работает). Открытых фаз по кластеру нет — вне спеки остаются GPUStack и сервисы демо |
| 2 | второй NIC (enp3s0 01/04; enp2s0 02/03) | **готово (2026-10-18)**: backend 10.20.20.0/26 на 02/03 восстановлен (`ansible/pb-net-p2p.yaml`, netplan-файл 60-p2p-backend.yaml, приёмочный взаимный ping зелёный, 2.5G); 01/04 — не используется. Инцидент 2026-10-18: `netplan apply` ребайндит DHCP eno1 и рвёт SSH — плейбук применяет через `systemd-run`; были утеряны резервации .253/.254 (PUT-стирание полей lease), восстановлены на роутере (address/server/mac) |
| 3 | containerd / swap | **готово на всех четырёх** (F0 2026-10-17: pb-k8s-prep на 01/02/03; containerd 2.2.1 + CRI, swap off; на 04 дописан k8s-01 в /etc/hosts) |
| 4 | Дискретный GPU | **есть: RTX 5060 Ti 16G в k8s-04** (с 2026-10-15; driver 595-open, hold; `hardware-inventory.md`) — BeeLlama обкатана, в k8s-режим GPUStack ещё не вводился |
| 5 | DHCP-резервирование нод | **все четыре в силе и bound**: 01→.250, 02→.253, 03→.254, 04→.252 (грабля client-id/DUID при переустановках — `mikrotik-setup.md` §3.5) |
| 6 | Внешняя доступность | **Cloudflare Tunnel работает (ADR-0004), E1–E5 + E7**: зона demo-ai-lab.ru в Cloudflare (NS irena/newt, DNSSEC выключен), туннель `demo-lab-ingress-v2` (пересоздан 2026-10-23); **с 2026-10-24 коннектор живёт на внешней VM (SberCloud), стендовые коннекторы `disable --now`** — uplink площадки режет порт `7844` (R1: 530/1033 со всех точек, сессии по 1–10 мин), с сети VM те же 4 сессии стоят без ротаций. Origin доводится SSH reverse-hop (`vmhop.service` на 02/03) → `haproxy` (loopback VM) → `https://127.0.0.1:19443` в tunnel-ingress; зона **Full(strict)**, origin — LE wildcard, hop TLS не терминирует. Приёмка: 200 из 8 стран (check-host), дрилл отказа hop-а — failover за ~4 c. Остаток: VM — единая точка отказа; E6 (Access) снят 2026-10-24 — служебные хостнеймы только в LAN |
| 7 | Дисковая модель нод | **полностью готова (F0 2026-10-17)**: root-LV 100G ×4; LV longhorn 250G на 02/03/04, ext4, fstab, `/var/lib/longhorn` смонтирован; k8s-01 без LV — вне пула (ADR-0003); open-iscsi ×4 |
| 8 | k8s-01 (добавлена 2026-10-17) | роль назначена (ADR-0003): control-plane #1 + компьют-heavy; **подготовка узла закрыта F0 (2026-10-17)**: pb-k8s-prep прогнан (containerd 2.2.1+CRI, swap off, `/etc/hosts`) — см. #3 |
| 9 | Endpoint API (controlPlaneEndpoint) | **работает (2026-10-18): kube-vip VIP `.240`** (ADR-0003 вариант A, `ansible/pb-k8s-vip.yaml`); лидер — любой из CP (сейчас k8s-03), VIP выведен из DHCP-пула роутера |
| 10 | Guardrail: Higress + `ai-data-masking` + Qwen3Guard | **решение 2026-10-24, ADR-0006 — три части**: плагин `ai-data-masking` (маскирование ПДн со `restore` в ответе), модель **Qwen3Guard-Gen-0.6B** (1.41 GiB, Apache-2.0, `Safe/Controversial/Unsafe` + `PII`/`Jailbreak`) в GPUStack и кастомный Wasm-плагин `ai-qwen-guard` (готового плагина под модель в каталоге Higress нет); рубильник — аннотация Ingress. Класс `guardrails-ai`, NeMo Guardrails, FMS Guardrails Orchestrator, Presidio и модели Llama-Guard/ShieldGemma/WildGuard рассмотрены и не взяты (причины — ADR-0006). Спека развёртывания `architecture/guardrail-spec.md` **не написана** |
| 11 | Keycloak (SSO) | **спека готова (v1.2, 2026-10-24), не установлен**: `architecture/keycloak-spec.md` — Keycloak 26.8.1 ×2 + PostgreSQL 17.11 в ns `keycloak` на паре k8s-02/03 (soft-affinity; k8s-04 исключён — там GPUStack), Argo CD (`gitops/infra-apps/keycloak/`), `auth.demo-ai-lab.ru`, realm `dev` + `user-test`/`admin-test`; приёмка K1–K7. Решения 2026-10-24: **Keycloak доступен глобально, включая `/admin` (план Б, без Access)**; SSO — **GPUStack да, Argo CD нет**; **HA БД не делаем** (демо, не прод). Пины сверены на стенде, ничего не задеплоено |
| 12 | MCP Registry | **спека готова (2026-10-24), не установлен**: `architecture/mcp-registry-spec.md` — `modelcontextprotocol/registry` + PostgreSQL 16 в ns `mcp-registry` на паре k8s-02/03, адрес `mcp.demo-ai-lab.ru`, развёртывание Argo CD, публикация по доменному токену (`ru.demo-ai-lab`), админ — OIDC Keycloak (клиент `mcp`); приёмка M1–M5. Пины: образ `ghcr.io/…@sha256:c00bf81d…`, PG 16-alpine |

| 13 | GPUStack (инференс, шаг 1) | **установлен 2026-10-28, G0–G7 закрыты** (спека v1.6):`architecture/gpustack-spec.md` — чарт `gpustack-chart` 2.2.3 (OCI, helm с консоли; `higress-core.enabled=false`, `gateway.ingressClassname=higress`), ns `gpustack`, сервер StatefulSet ×1 + PVC 20Gi на паре 02/03, GPU-воркер `k8s-04` (`runtimeClassName: nvidia`, hostNetwork 10150), CPU-воркер только на 01, `api.demo-ai-lab.ru`, приёмка G0–G8. **Блокер, найденный замером:** handler `nvidia` в containerd не применён (старый `99-nvidia.toml` в схеме version 2 не читается containerd 2.2.1) — RuntimeClass создать мало, нужна правка drop-in (G1). Модели по ADR-0007: `gemma-4-12B` (9.59 GiB, util 0.75) + ASR `whisper-large-v3-turbo` (0.15) резидентно, запасная `Qwen3.5-9B-AWQ-4bit` — только весами на диске (`14B` снят); диск 04 расширен до 210 GB; раннер `cuda13.0-vllm0.25.1` (20.5 ГБ) — предтяжка обязательна. **Факт 28.10.2026:** чат `gemma-4-12B` (`--max-model-len 4096`, util 0.68, 12 668 MiB) + ASR `whisper-turbo` (CT2 int8, 2 294 MiB) резидентно на 5060 Ti = 14 977 из 16 311 MiB; SSO включён (клиент `gps`, issuer realm `dev`, Secret `gpustack-oidc`, апгрейд только через `ansible/gpustack-upgrade.sh`), API-путь `/v1/*` остаётся по ключу |

| 14 | Доставка образов | **прямой pull из облачных реестров (2026-10-24)**: локальный реестр (`preload-registry` на консоли, `192.168.10.188:5050`) и склад предзагрузки сняты — `preload-registry/` и `references/preload-registry.md` удалены из репо, `env_health.py` больше реестр не проверяет. Mirror-конфиги containerd (`/etc/containerd/certs.d/*/hosts.toml` на всех 4 нодах + остаток `192.168.10.199:5050` на k8s-04) удалены, бэкап — `/root/certs.d.bak-20261024` на каждой ноде. Приёмка: `ctr -n k8s.io images pull docker.io/library/hello-world:latest` идёт напрямую, 9–24 с на ноду; контейнер реестра на консоли удалён, том `preload_registry` оставлен |

| 15 | Keycloak (SSO, `auth.demo-ai-lab.ru`) | **установлен 2026-10-27, K1–K7 закрыты**: `gitops/infra-apps/keycloak/` под Argo CD (Application `keycloak` — Synced/Healthy): Keycloak 26.8.1 ×2 на паре **k8s-02/03** (`jdbc-ping`, сессии в БД) + PostgreSQL 17.11 (PVC 8Gi Longhorn, SPOF принят), PriorityClass `demo-stand-critical`, отдельный `Certificate auth-demo-tls` (LE YR1) + Ingress Higress. Realm `dev`: роли `app-user`/`app-admin`(⊃)/`agent-service`, `user-test`/`admin-test`, клиенты `smoke-cli`/`gps`/`agent-runtime`/`mcp`; brute-force 5/60 c проверен живьём. Публично целиком, включая `/admin` (план Б). `KC_BOOTSTRAP_ADMIN_*` сняты, пароль админа ротирован (32 симв.). Drill: потеря пода и переход на 1 реплику — discovery LAN/edge 200 всё время. Secret'ы вне git (`scripts/keycloak_secrets.sh`), seed — `scripts/keycloak_seed.py`, бэкап `pg_dump` вне репо. |

## 8. Файлы

- `README.md` — входная точка: исходное состояние стенда и сценарий демо (3 шага).
- `network-map-detail.md` — карта сети (живой аудит).
- `mikrotik-setup.md` — рецепт настройки MikroTik (для повторения стенда; без секретов).
- `inventory.local.md` — скрытая инвентаризация (MAC, доступы) — не в git.
- `architecture/architecture-c2.excalidraw` — целевой C2 (исходник слоёв).
- `architecture/ARCHITECTURE.md` — этот документ.
- `architecture/endpoints.md` — все публичные адреса короткими именами + кто за SSO (`owu`, `rag`, `doc`, …).
- `architecture/hardware-inventory.md` — инвентарь железа: диски, износ/ресурс (SMART),
  прошивки, TBW-документация — снимки по датам.
- `architecture/demo-ai-lab-architecture.html` — диаграмма (физ. + логический слой).
- `architecture/k8s-install-spec.md` — спецификация bootstrap'а кластера (kubeadm→CNI→хранилище).
- `architecture/external-access-spec.md` — спецификация внешнего доступа (Cloudflare Tunnel,
  MikroTik split-DNS, TLS Full strict; приёмка E1–E5, ADR-0004; E6 Access снят; **E7 — второй egress
  через внешнюю VM + SSH-hop**).
- `architecture/keycloak-spec.md` — спецификация SSO (Keycloak 26.8.1 ×2 + PostgreSQL 17.11 на паре k8s-02/03,
  деплой через Argo CD, `auth.demo-ai-lab.ru`, realm `dev`; приёмка K1–K7; креды — `*.local.md`, не в git).
- `architecture/gpustack-spec.md` — спецификация GPUStack 2.2.3 (шаг 1 демо): helm-чарт + values в
  `ansible/values-gpustack.yaml`, сервер на паре 02/03, GPU-воркер `k8s-04` через `runtimeClassName: nvidia`,
  раннер `cuda13.0-vllm0.25.1`, модели AWQ, `api.demo-ai-lab.ru`; приёмка G0–G8, блокер G1 — handler
  `nvidia` в containerd; креды — `gpustack-admin.local.md`, не в git.
