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
| This Mac | DHCP | — | — | консоль: ssh, kubectl, диаграммы |

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
| Вспомогательные | **внутренний MCP-реестр** (self-hosted `modelcontextprotocol/registry`, публикация через Keycloak OIDC) — каталог сервисов и MCP-серверов; каталог скиллов, Langfuse, Data Catalog | инфраструктура агентов, трассировка LLM, каталог данных |
| Данные и интеграции | Keycloak (SSO), Qdrant, PostgreSQL/ClickHouse, S3 | идентичность, векторы, реляционное/колоночное, объекты |
| Вычислительный | **GPUStack v2.2.3** (on-prem LLM, OpenAI-API; версия зафиксирована, ADR-0001), vLLM/SGLang (RTX 5060 Ti — план), Лайт-LLM прокси | инференс |
| Guardrail | **guard-маршрут** на Higress (Wasm `ai-security-guard`); классификатор — **отложен** (2026-10-23: Prompt Guard 2 не относится к поддерживаемым типам моделей GPUStack, CPU-раннера в каталоге 2.2.x нет) | модерация входа: инъекции/джилбрейк; рубильник — аннотация Ingress |
| Кластер и эксплуатация | Argo CD (GitOps), k8s ingress, Мониторинг (метрики/логи/трейсы) | деплой и наблюдаемость |

**Лайт-LLM прокси** — внешний эgress к публичным LLM с сокрытием содержимого
запросов (когда on-prem модели недостаточны).

**Внутренний MCP-реестр** (план) — self-hosted официальный `modelcontextprotocol/registry`
(Go + PostgreSQL, лицензии Apache-2.0/MIT): в закрытый контур ставится как есть, БД пустая —
публикуются только свои серверы; верификация неймспейсов наружу (GitHub OAuth/OIDC, DNS/HTTP)
в изолированном контуре заменяется `MCP_REGISTRY_OIDC_*` → Keycloak; публикация —
`mcp-publisher` c `--registry <внутренний URL>`; опционально зеркало официального реестра
силом через машину с egress. Размещение — вместе с каталогами (k8s-02).

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
   образы — из реестра (Docker Hub / зеркала).
7. **Наблюдаемость**: Мониторинг → метрики/логи/трейсы кластера и сервисов;
   LLM-трейсинг — Langfuse.
8. **Доступ к стенду**: наружу выставлен `api.demo-ai-lab.ru` (GPUStack API).
9. **Guardrail (опциональный лег, модельный бэкенд отложен 2026-10-23)**: сервис/агент →
   guard-маршрут Higress (Wasm `ai-security-guard`) → классификатор → в GPUStack только чистые
   запросы; рубильник — аннотация Ingress (план 2026-10-18). Классификатор Prompt Guard 2 — не
   поддерживаемый тип модели: каталог раннеров 2.2.3 это vLLM/SGLang на CUDA/ROCm/CANN, CPU-варианта
   нет — вернуться при подтверждённом поддерживаемом пути.

## 5. Размещение сервисов по узлам (план, ADR-0003 от 2026-10-17)

Железо (пересмер 2026-10-17, SSH, после переустановки 02/03): все четыре узла NVMe 477G,
root-LV 100G, ~374G свободно в VG. k8s-01 — лидер по RAM (32Gi) и одновременно самый
изношенный диск стенда (ZSPEED, 11% по SMART, резерв TBW ≈100 TB против ≈250+ TB у AirDisk,
`hardware-inventory.md`). Принцип разделения: **k8s-01 — память, 02/03/04 — диски Longhorn**.

| Узел | Роль в кластере | Что размещать | Почему |
|---|---|---|---|
| k8s-01 (.250) | **control-plane #1** + **компьют** | RAGFlow (разбор/индексация), OCR·Docling, qm + вынесенные рантаймы, BI, Langfuse (guardrail-классификатор — отложен, см. §4 поток 9) | 32Gi + 8C/16T — лидеры стенда; **вне пула реплик Longhorn** (износ диска): считаем здесь, данные — на томах 02/03/04 |
| k8s-02 (.253) | **control-plane #2** + **ingress (пара с 03)** + GitOps | apiserver/etcd/scheduler/CM; ingress-controller (**Higress** — ADR-0001) на ingress-VIP `.230`; Argo CD; qm; каталоги (сервисов/MCP, скиллов); Лайт-LLM прокси | Проброс WAN 80/443 переедет на ingress-VIP `.230` (решение 2026-10-18); из 14Gi после control-плоскости (~2,5–3 Gi) остаётся ~11 Gi — ingress+лёгкие сервисы |
| k8s-03 (.254) | **control-plane #3** + **ingress (пара с 02, VIP `.230`)** + вспомогательные | Open WebUI, каталоги, лёгкие stateless-сервисы; Higress-gateway | Замыкает etcd-кворум 3/3; тот же бюджет ~11 Gi; second kube-vip (LB, `.230`) только на 02/03 |
| k8s-04 (.252) | **LLM-инференс + сервисы** (без taint'а) | BeeLlama/GPUStack (RTX 5060 Ti, nodeSelector); **data-heavy: PostgreSQL, ClickHouse, Qdrant, MinIO (S3), Keycloak (SSO)** | 28Gi — вторая RAM стенда; диск в пуле Longhorn → БД локальны к репликам; инференс защищается priorityClass + requests/limits сервисов, а не изоляцией; модели — hostPath; LV Longhorn 250G |

Ключевые правила (реализуются через taints/nodeSelector):
- **taint control-plane снять на k8s-01/02/03**; k8s-04 **без taint'а** (ADR-0003,
  правка владельца 2026-10-17) — сервисы живут и на нём. Размещение — nodeSelector по таблице.
- Инференс на k8s-04 защищается **приоритетом, не изоляцией**: nodeSelector закрепляет
  BeeLlama/GPUStack, priorityClass выше сервисного (preemption при нехватке RAM),
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
| `192.168.10.230` | ingress-VIP — HTTP(S)-вход сервисов (Higress-gateway) | kube-vip, второй инстанс, режим LB (ARP, pool `.230`); `externalTrafficPolicy: Local` | пара k8s-02+k8s-03 (gateway закреплен nodeSelector'ом; VIP отвечает там, где живой endpoint) | выведен из DHCP-пула (2026-10-18) | split-DNS MikroTik (`demo-ai-lab.ru` + regexp-wildcard → `.230`); Cloudflare Tunnel-ингресс → `http://.230` |

- Итоговый DHCP-пул: `.10–.229,.231–.239,.241–.254` — `.230` и `.240` не выдаются никогда.
- Плоскости разделены намеренно (решение владельца 2026-10-18): деградация ingress не должна
  влиять на API кластера и наоборот; статический `.253` как endpoint отклонён (ADR-0003, вариант B).

### 6.2 Доступность и периметр

- Egress LAN → интернет — только через MikroTik (NAT masquerade).
- **Внешняя доступность — Cloudflare Tunnel (ADR-0004, Accepted 2026-10-18)**: зона
  `demo-ai-lab.ru` в Cloudflare Free, публичный DNS = IP edge (адрес площадки не публикуется);
  туннель `demo-lab-ingress` с коннекторами `cloudflared` (systemd) на k8s-02/03,
  active-active, ингресс → `http://192.168.10.230` (ingress-VIP). Соединения только
  исходящие (QUIC/TCP 7844) — входящие в uplink не требуются; TLS на edge (Universal SSL) + **Full(strict)**:
  origin-сертификат Let's Encrypt wildcard через cert-manager (DNS-01 через Cloudflare) —
  ADR-0004, ревизия 2026-10-18; переезд tunnel-ingress на `https://.230` — E5.
  **Контур внешнего доступа целиком специфицирован в `architecture/external-access-spec.md`**
  (E1–E6: Cloudflare, MikroTik, split-DNS, TLS, Access — с критериями приёмки).
- **LAN-путь (основной для демо)**: split-DNS на MikroTik — `demo-ai-lab.ru` и regexp
  wildcard → `.230`, работает с 2026-10-18; аудитория Wi-Fi не зависит от внешних NS/DNS.
- Исторический dstnat `WAN 80,443 → .253` — устарел (внешний путь — туннель),
  снятие на E5 (external-access-спека).
- WAN-защита: input drop новых соединений из не-LAN; управление роутером —
  только из LAN (Winbox/REST; SSH — запасной канал для разовых команд).
- Backend `10.20.20.0/26` — изолированный L2 p2p, без маршрута в LAN.
- В целевом состоянии: SSO — Keycloak; секреты не в репозитории (`inventory.local.md` в `.gitignore`,
  public IP — confidential).


## 7. Текущее состояние и пробелы

| # | Пункт | Статус |
|---|---|---|
| 1 | K8s-кластер | **поднят 2026-10-18 (F1+F2)**: kubeadm 1.35.9, 3 CP + worker 04, все Ready; kube-vip `.240` (лидер k8s-03), etcd ×3, Cilium 1.20.3 full-KPR (`cilium status: OK`); taints сняты (all-in-one, спека §4). Next: F3 Longhorn → F4 NFD → F5 cert-manager → F6 Argo CD → **F7 ingress-VIP `.230` → F8 Higress** (ингресс вернулся в инсталл-спеку 2026-10-19) → F9 приёмка |
| 2 | второй NIC (enp3s0 01/04; enp2s0 02/03) | **готово (2026-10-18)**: backend 10.20.20.0/26 на 02/03 восстановлен (`ansible/pb-net-p2p.yaml`, netplan-файл 60-p2p-backend.yaml, приёмочный взаимный ping зелёный, 2.5G); 01/04 — не используется. Инцидент 2026-10-18: `netplan apply` ребайндит DHCP eno1 и рвёт SSH — плейбук применяет через `systemd-run`; были утеряны резервации .253/.254 (PUT-стирание полей lease), восстановлены на роутере (address/server/mac) |
| 3 | containerd / swap | **готово на всех четырёх** (F0 2026-10-17: pb-k8s-prep на 01/02/03; containerd 2.2.1 + CRI, swap off; на 04 дописан k8s-01 в /etc/hosts) |
| 4 | Дискретный GPU | **есть: RTX 5060 Ti 16G в k8s-04** (с 2026-10-15; driver 595-open, hold; `hardware-inventory.md`) — BeeLlama обкатана, в k8s-режим GPUStack ещё не вводился |
| 5 | DHCP-резервирование нод | **все четыре в силе и bound**: 01→.250, 02→.253, 03→.254, 04→.252 (грабля client-id/DUID при переустановках — `mikrotik-setup.md` §3.5) |
| 6 | Внешняя доступность | **Cloudflare Tunnel работает (ADR-0004)**: зона demo-ai-lab.ru активирована 2026-10-18 (NS irena/newt видны с 1.1.1.1/8.8.8.8, DNSSEC выключен), туннель `demo-lab-ingress` healthy — 2 коннектора на 02/03 active-active; через edge путь живёт (5xx до Higress — штатно); осталось: прослушивание на `.230` (F7/F8 инсталл-спеки) и переезд туннель-ingress на `https://.230` (Full strict, §TLS ADR-0004, external-access E5) |
| 7 | Дисковая модель нод | **полностью готова (F0 2026-10-17)**: root-LV 100G ×4; LV longhorn 250G на 02/03/04, ext4, fstab, `/var/lib/longhorn` смонтирован; k8s-01 без LV — вне пула (ADR-0003); open-iscsi ×4 |
| 8 | k8s-01 (добавлена 2026-10-17) | роль назначена (ADR-0003): control-plane #1 + компьют-heavy; **подготовка узла закрыта F0 (2026-10-17)**: pb-k8s-prep прогнан (containerd 2.2.1+CRI, swap off, `/etc/hosts`) — см. #3 |
| 9 | Endpoint API (controlPlaneEndpoint) | **работает (2026-10-18): kube-vip VIP `.240`** (ADR-0003 вариант A, `ansible/pb-k8s-vip.yaml`); лидер — любой из CP (сейчас k8s-03), VIP выведен из DHCP-пула роутера |
| 10 | Guardrail: guard-маршрут + Prompt Guard 2 | **маршрут — в плане, модельный бэкенд отложен (2026-10-23):** классификатор не относится к поддерживаемым типам моделей GPUStack, CPU-раннера в каталоге нет; вернуться при подтверждённом пути, затем верифицировать `openaiCustomUrl` в плагине `ai-security-guard` |

## 8. Файлы

- `README.md` — входная точка: исходное состояние стенда и сценарий демо (3 шага).
- `network-map-detail.md` — карта сети (живой аудит).
- `mikrotik-setup.md` — рецепт настройки MikroTik (для повторения стенда; без секретов).
- `inventory.local.md` — скрытая инвентаризация (MAC, доступы) — не в git.
- `architecture/architecture-c2.excalidraw` — целевой C2 (исходник слоёв).
- `architecture/ARCHITECTURE.md` — этот документ.
- `architecture/hardware-inventory.md` — инвентарь железа: диски, износ/ресурс (SMART),
  прошивки, TBW-документация — снимки по датам.
- `architecture/demo-ai-lab-architecture.html` — диаграмма (физ. + логический слой).
- `architecture/k8s-install-spec.md` — спецификация bootstrap'а кластера (kubeadm→CNI→хранилище).
- `architecture/external-access-spec.md` — спецификация внешнего доступа (Cloudflare Tunnel,
  MikroTik split-DNS, TLS Full strict; приёмка E1–E6, ADR-0004).
