# Оборудование стенда demo-ai-lab (публичный список)

Состав физического стенда **demo-ai-lab.ru**: что стоит, сколько и зачем. Числа — только те,
которые сняты с живого железа или внесены владельцем; износ дисков, прошивки и датированные замеры —
`architecture/hardware-inventory.md`, размещение сервисов по узлам — `architecture/ARCHITECTURE.md` §2.3 и §5.

> **Границы публикации** (AGENTS.md): MAC-адреса, серийные номера, логины/пароли, адреса доступа к
> узлам и public IP площадки в этот файл не попадают никогда — они живут в приватном
> `inventory.local.md` (вне git). LAN-адреса `192.168.10.0/24` и IP узлов публикуются осознанно.

## Сводка

| Категория | Состав | Кол-во |
|---|---|---:|
| Вычисления | GMKtec NucBox (K6 / M6 Ultra / K12), Ubuntu 24.04.4, kubeadm 1.35 | 5 |
| GPU | **MAXSUN GeForce RTX 5070 Ti iCraft OC** 16 GB в док-станции AOOSTAR AG01S + **ASUS GeForce RTX 5060 Ti DUAL OC** 16 GB (первая карта стенда) | 2 |
| Питание | Baseus 240 W USB-C GaN + Huntkey 800 W в док-станции | 2 выделенных БП |
| Сеть | MikroTik L009UiGS-2HaxD (роутер), Tenda TEM2010X (коммутатор) | 2 |
| Консоль | JetKVM (IP-KVM) |  1 |

## 1. Вычисления — 5 мини-ПК GMKtec

| Узел | Модель | CPU | RAM | Диск | Роль в кластере |
|---|---|---|---:|---|---|
| `k8s-01` (`.250`) | GMKtec NucBox K6 | R7 7840HS, 8C/16T | 32 GiB | NVMe 477 G (ZSPEED) | control-plane #1 + компьют-heavy, iGPU Radeon 780M под RAG-пару |
| `k8s-02` (`.253`) | GMKtec NucBox M6 Ultra | R5 7640HS, 6C/12T | 14 GiB | NVMe 477 G (AirDisk) | control-plane #2 + ingress-пара (Higress, VIP `.230`) + GitOps |
| `k8s-03` (`.254`) | GMKtec NucBox M6 Ultra | R5 7640HS, 6C/12T | 14 GiB | NVMe 477 G (AirDisk) | control-plane #3 + ingress-пара + лёгкие сервисы |
| `k8s-04` (`.252`) | GMKtec NucBox K12 | R7 H 255, 8C/16T | 28 GiB | NVMe 1 TB (Netac) | GPU-нода: LLM-инференс + data-heavy сервисы |
| `k8s-05` (`.251`) | GMKtec NucBox K12 | R7 H 255, 8C/16T | 14 GiB | NVMe 1 TB (Netac) | worker без taint'а: Firecrawl, Kuvasz |

Все пять — Ubuntu 24.04.4, containerd 2.2.1 + CRI, swap off, kubeadm/kubelet/kubectl **1.35.9** (hold).
Два 2.5-гигабитных NIC в каждой (Realtek RTL8125); второй интерфейс задействован только на паре
`k8s-02`↔`k8s-03` — изолированный backend `10.20.20.0/26`. Модели/BIOS и история — `hardware-inventory.md`.

## 2. GPU — две карты, действующая во внешней док-станции

### Действующая карта (с 2026-11-09)

| Компонент | Модель | Заметки |
|---|---|---|
| Док-станция | **AOOSTAR AG01S eGPU**, порт **OCuLink** | карта вне корпуса `k8s-04`, подключение по OCuLink; `lspci` даёт **PCIe Gen4 x4** |
| Блок питания в док-станции | **Huntkey 800 W** (встроенный) | питает док и карту; отдельного БП у карты нет |
| Видеокарта | **MAXSUN GeForce RTX 5070 Ti iCraft OC** (`MS-RTX5070Ti iCraft OC16G`) | 16 GB GDDR7, Blackwell `sm_120`, 16 303 MiB по `nvidia-smi`, VBIOS `98.03.58.40.34`, power limit 300 W |
| Драйвер | `nvidia-driver-595-open` **595.99.02** (open kernel modules), пакет в `hold` | обязательны open-модули для Blackwell |

На ней работают GPUStack/vLLM-раннеры (27B BeeLlama, страж `Qwen3Guard`, ASR, `GLM-OCR`,
`Z-Image-Turbo`) и модели кейсов. Из-за внешнего подключения по OCuLink линк x4, а не x16 — на замерах
это не является узким местом (декод упирается в ПСП карты, не в шину).

### Первая карта стенда — ASUS RTX 5060 Ti DUAL OC

| Параметр | Значение |
|---|---|
| Модель | **ASUS GeForce RTX 5060 Ti DUAL OC** (`DUAL-RTX5060TI-O16G`) |
| Память / чип | 16 GB GDDR7, GB206, Blackwell `sm_120`; 16 311 MiB по `nvidia-smi`, VBIOS `98.06.39.40.B1` |
| Роль | с неё начат стенд: на этой карте снят эталонный прогон 27B 16.10.2026 (`bench-results.json`) и прогон 02.11; с 2026-11-09 в узле стоит 5070 Ti |
| В документации | в действующих разделах картой стенда считается 5070 Ti; прогоны до 09.11 оставлены историей «было/стало» (decode 48.8 → 79.3 tok/s на 4K) |

Сравнение двух карт на одном конфиге (27B IQ3_S + MTP, kvarn4, 128K) и замеры второй карты —
`beellama-rtx5060/README.md` и `beellama-rtx5060/GPU-CHOICE-16GB.md`; бюджет VRAM — ADR-0007.

## 3. Сеть

| Устройство | Модель | Роль |
|---|---|---|
| Роутер | **MikroTik L009UiGS-2HaxD**, RouterOS 7.24.5, identity `gw-demo-ai-lab` | шлюз `192.168.10.1`: DHCP с резервациями всех нод, firewall, NAT, split-DNS зоны, Wi-Fi для аудитории |
| Коммутатор | **Tenda TEM2010X** — 8 портов 2.5 Гбит/с + 2 × SFP+ | L2 в LAN: порты 1–6 — ноды, порты 7–8 — статическая агрегация (без LACP) в `bond1` MikroTik (`balance-xor`), 2×1 Гбит/с со стороны роутера |
| IP-KVM | **JetKVM** (`192.168.10.10`, DHCP) | KVM-over-IP: HDMI-захват + USB HID, управление консолью ноды из браузера |

Логическая карта (VIP, ingress, внешний путь через Cloudflare Tunnel) — `network-map-detail.md`;
настройка роутера — `mikrotik-setup.md`. Модель коммутатора до 2026-11-10 в доках значилась как
«Tenda L2» без номера — зафиксирована `TEM2010X`.

## 4. Питание — два выделенных блока

| Блок питания | Модель | Что питает |
|---|---|---|
| Зарядная станция | **Baseus 240 W USB Type-C GaN** (для ноутбука, MacBook и телефона) | консоль/ноутбук и гаджеты по USB-C PD |
| Блок в док-станции | **Huntkey 800 W** (встроенный в AOOSTAR AG01S) | док-станция и RTX 5070 Ti |

Ноды GMKtec — на штатных адаптерах из комплекта (по одному на узел). Отдельного ИБП на стенде нет.

## Что здесь не публикуется

MAC-адреса и OUI-привязки, серийные номера узлов и дисков, логины и пути к SSH-ключам, пароли и
токены, содержимое `.env`, public IP и сведения о физической площадке — по правилам `AGENTS.md`.
Эти данные — в приватном `inventory.local.md` (вне git, не публикуется и не цитируется).
