# Железо стенда demo-ai-lab

Стенд **demo-ai-lab.ru** — пять мини-ПК, одна видеокарта в внешней док-станции, роутер,
коммутатор и KVM-over-IP. Собирался под локальный инференс: всё, что можно обработать на своём
железе, обрабатывается здесь. Ниже — что именно стоит, сколько это даёт и сколько стоило.

Все числа сняты с живого железа (или из спецификации вендора, где это отмечено).
Журнал замеров — износ дисков, датированные снимки, история замен — в
`architecture/hardware-inventory.md`; разметка дисков — `references/storage-model.md`;
размещение сервисов по узлам — `architecture/ARCHITECTURE.md` §2.3 и §5.

## Стенд целиком

| Параметр | Значение |
|---|---|
| Узлы | 5 мини-ПК GMKtec: NucBox K6 ×1, M6 Ultra ×2, K12 ×2 |
| Процессоры | **36 ядер / 72 потока** (R7 7840HS 8C/16T, R5 7640HS 6C/12T ×2, R7 H255 8C/16T ×2) |
| Память | **128 GB DDR5** (32 + 16 + 16 + 32 + 32 GB по узлам); ОС видит 114 GiB — вырезано под iGPU и прошивку |
| Накопители | **3.58 TB** NVMe: 512 GB ×3 + 1 TB ×2 |
| GPU | RTX 5070 Ti 16 GB (действующая) + RTX 5060 Ti 16 GB (историческая, снята) |
| VRAM | 16 GB на карту; в работе одновременно одна |
| Сеть | 2×2.5GbE на узел; коммутатор 8×2.5G + 2×SFP+, роутер 8×1G + SFP+ |
| Питание | Huntkey 800 W в док-станции GPU; 2 × Baseus 240 W GaN питают четыре узла и коммутатор |
| Консоль | JetKVM — HDMI-захват + USB HID, управление из браузера |

Итого: 36 ядер, 128 GB памяти, 3.58 TB быстрых дисков и 16 GB VRAM. Для LLM-нагрузки решает
не сумма ядер, а пропускная способность памяти карты — поэтому ниже отдельный раздел про GPU.

## Узлы

| Узел | Мини-ПК | CPU | RAM (планки) | NVMe | Роль |
|---|---|---|---|---|---|
| `k8s-01` | [GMKtec NucBox K6](https://www.gmktec.com/) | R7 7840HS, 8C/16T | 32 GB (ОС видит 23.3) | 512 GB ZSPEED | control-plane #1 + компьют-heavy; iGPU 780M — эмбеддинги и реранк |
| `k8s-02` | [GMKtec NucBox M6 Ultra](https://www.gmktec.com/) | R5 7640HS, 6C/12T | 16 GB (14.9) | 512 GB AirDisk | control-plane #2, ingress (Higress, VIP `.230`), GitOps |
| `k8s-03` | [GMKtec NucBox M6 Ultra](https://www.gmktec.com/) | R5 7640HS, 6C/12T | 16 GB (14.9) | 512 GB AirDisk | control-plane #3, вторая половина ingress-пары |
| `k8s-04` | [GMKtec NucBox K12](https://www.gmktec.com/) | R7 H255, 8C/16T | 32 GB (30.6) | 1 TB Netac | GPU-нода: инференс + data-heavy сервисы |
| `k8s-05` | [GMKtec NucBox K12](https://www.gmktec.com/) | R7 H255, 8C/16T | 32 GB (30.6) | 1 TB Netac | worker: Firecrawl, мониторинг |

Все пять — Ubuntu 24.04, containerd 2.2.1 + CRI, swap off, kubeadm/kubelet 1.35.9. Второй
2.5-гигабитный порт задействован только на паре `k8s-02`↔`k8s-03` — изолированный backend
`10.20.20.0/26`; остальной трафик идёт по LAN. Износ дисков и остаток ресурса — в журнале.

## Видеокарты: что даёт каждая

Стенд начинался с 16-гиговой карты среднего класса и перешёл на старшую в той же полосе памяти.
Обе — Blackwell (`sm_120`), обе по 16 GB; разница — в чипе и, главное, в пропускной способности.

| | RTX 5060 Ti 16 GB — история | RTX 5070 Ti 16 GB — сейчас |
|---|---|---|
| Плата | `ASUS DUAL-RTX5060TI-O16G` | `MS-RTX5070Ti iCraft OC16G` (MAXSUN) |
| Чип, техпроцесс | GB206, TSMC 4N | GB203, TSMC 4N |
| CUDA-ядра | 4 608 | 8 960 |
| RT / тензорные ядра | 36 / 144 | 70 / 280 |
| Boost | 2 572 МГц | 2 452 МГц |
| FP32 (расчётно) | **23.7 TFLOPS** | **43.9 TFLOPS** |
| AI TOPS (FP4, заявка вендора) | 759 | 1 406 |
| Память | 16 GB GDDR7, 128 бит, **448 ГБ/с** | 16 GB GDDR7, 256 бит, **896 ГБ/с** |
| Потребление | 180 Вт | 300 Вт |
| Подключение на стенде | PCIe Gen4 x4 (OCuLink) | PCIe Gen4 x4 (OCuLink) |
| VRAM под нагрузкой (замер) | 15.5 GiB | 15.6 GiB |

Спецификации — [NVIDIA RTX 5070](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/),
[NVIDIA RTX 5060](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5060-family/);
у партнёрских карт частоты выше референса. FP32 посчитан как «ядра × 2 × boost».

Обе карты работают вне корпуса ноды — в док-станции
[AOOSTAR AG01S](https://aoostar.com/) по OCuLink, поэтому линк Gen4 **x4**, а не x16. На замерах
это не узкое место: декод упирается в память карты, а не в шину.

## Память и накопители

| Что | Сколько | Заметки |
|---|---|---|
| RAM | 128 GB DDR5 | 32 + 16 + 16 + 32 + 32 GB по узлам; ОС видит 114 GiB — на k8s-01 8 GiB вырезано под iGPU (UMA, замер `mem_info_vram_total = 8 GiB`), остальное — резерв прошивки |
| NVMe | 3.58 TB | 512 GB ×3 (no-name ZSPEED/AirDisk) + 1 TB ×2 (Netac) |
| Longhorn | 1.25 TB сырых | LV 250G ×3 + 500G ×1, репликация ×2 → ≈625 GB полезных |

`k8s-01` выведен из пула реплик: у его диска самый скромный ресурс (≈119 TB против ≈250+ TB),
а узел несёт вычисления, не данные. Износ и остаток — `architecture/hardware-inventory.md`.

## Сеть, питание, консоль

| Устройство | Модель | Роль |
|---|---|---|
| Роутер | [MikroTik L009UiGS-2HaxD](https://mikrotik.com/product/l009uigs_2haxd_in), RouterOS 7.24.5 | LAN `192.168.10.0/24`, DHCP с резервациями, firewall, split-DNS зоны, Wi-Fi 2.4 ГГц для аудитории |
| Коммутатор | [Tenda TEM2010X](https://www.tendacn.com/product/TEM2010X.html) — 8×2.5 Гбит/с + 2×SFP+ | L2 в LAN; порты 7–8 — статическая агрегация в роутер (2×1 Гбит/с) |
| IP-KVM | [JetKVM](https://jetkvm.com/) | консоль любой ноды из браузера: HDMI + USB HID |
| Питание GPU | Huntkey 800 W в док-станции AOOSTAR AG01S | питает док и карту |
| Питание узлов | 2 × Baseus 240 W USB-C GaN | четыре мини-ПК и коммутатор; пятый узел — на штатном адаптере |
| Каркас | алюминиевый профиль 20×20 | открытая рама: узлы, роутер, коммутатор, док-станция с картой |

ИБП на стенде нет. Карта стоит вне корпуса, поэтому всё это живёт на открытой раме и
обслуживается без разборки.

## Сколько это стоило

Цены — то, за что покупалось, либо розница в России на **19.11.2026**, где цена покупки неизвестна;
без доставки и сборки. Отличия розничной конфигурации от нашего узла отмечены в строке.

| Позиция | Розничная конфигурация | Цена, ₽ | Где |
|---|---|---:|---|
| `k8s-01` — NucBox K6 | 32 GB + 512 GB | 50 000 | купил БУ по цене M6 |
| `k8s-02` — NucBox M6 Ultra | 16 GB + 500 GB | 55 000 | [gmktec.ru](https://gmktec.ru/m6) |
| `k8s-03` — NucBox M6 Ultra | 16 GB + 500 GB | 55 000 | там же |
| `k8s-04` — NucBox K12 | 32 GB + 1 TB | 104 500 | [gmktec.ru](https://gmktec.ru/gmktec-nucbox-k12) |
| `k8s-05` — NucBox K12 | 32 GB + 1 TB | 104 500 | там же |
| GPU — RTX 5070 Ti | MAXSUN iCraft OC 16 GB | 172 999 | [DNS](https://www.dns-shop.ru/product/e326bf911d19d9cb/videokarta-maxsun-geforce-rtx-5070-ti-icraft-oc-ms-rtx5070ti-icraft-oc16g/), под заказ |
| Док-станция GPU | AOOSTAR AG01S со встроенным БП Huntkey 800 W | 13 000 | [Ozon](https://www.ozon.ru/product/dok-stantsiya-aoostar-ag01s-egpu-s-portom-oculink-vstroennym-blokom-pitaniya-huntkey-moshchnostyu-2148210885/) |
| Роутер | MikroTik L009UiGS-2HaxD-IN | 12 699 | [DNS](https://www.dns-shop.ru/product/d691014e0110ed20/wi-fi-router-mikrotik-l009uigs-2haxd-in/) |
| Коммутатор | Tenda TEM2010X | 4 500 | [Ozon](https://www.ozon.ru/product/kommutator-tenda-tem2010x-8-portovyy-2-sfp-2500-mbit-s-chernyy-2351172330/) |
| Консоль | JetKVM | 11 000 | [Ozon](https://www.ozon.ru/product/pult-distantsionnogo-upravleniya-dlya-pk-s-otkrytym-ishodnym-kodom-jetkvm-4433027854/) |
| Питание узлов | 2 × Baseus 240 Вт USB-C GaN: четыре узла и коммутатор | 20 000 | [Ozon](https://www.ozon.ru/product/zaryadnaya-stantsiya-baseus-240w-usb-type-c-gan-dlya-noutbuka-macbook-i-telefona-chernyy-1753825575/), 10 000 ₽ за штуку |
| Каркас | алюминиевый профиль 20×20, 600 мм, 2 шт в лоте — 2 лота | 4 000 | [Ozon](https://www.ozon.ru/product/profil-konstruktsionnyy-v20h20-an-chernyy-600-mm-2-sht-soberizavod-1787575427/), 2 000 ₽ за лот |
| **Итого — действующая конфигурация** | 5 узлов + GPU + док + сеть + консоль + каркас | **607 198** | |

Историческая карта в сумму не входит: RTX 5060 Ti DUAL OC 16 GB — **91 999 ₽** (DNS, в наличии);
если считать её тоже, выходит 699 197 ₽.

Диски и память отдельными строками не считаются — они входят в конфигурации мини-ПК; апгрейд
`k8s-05` до 32 GB уже учтён в розничной конфигурации K12.

Оговорки: `k8s-01` — **б/у** K6 за 50 000 ₽ (как цена M6); новый K6 в рознице — 123 990 ₽ за
32 GB + 1 TB. Наши узлы `k8s-02/03` — **M6 Ultra** (Ryzen 5 7640HS), в рознице их нет, поэтому в
расчёте M6 (Ryzen 5 6600H) в той же конфигурации 16 GB + 500 GB — процессор слабее, цена ниже;
Tenda в DNS снята с продажи — взята цена Ozon, KNS держит 9 473 ₽; RTX 5070 Ti в DNS под заказ, дешевле — Palit
GamingPro-S за 169 999 ₽. Суммы без доставки, сборки и мелочей (кабели, крепёж).

## Что здесь не публикуется

Серийные номера, MAC-адреса, логины и ключи, public IP площадки — этого в документе нет и не
будет: они живут в приватном `inventory.local.md` вне репозитория. Версии BIOS, прошивок и
политика их обновления — тоже там: слушателю демо это не нужно.

## Где детали

- `architecture/hardware-inventory.md` — журнал железа: диски, износ, SMART, датированные снимки;
- `references/storage-model.md` — разметка дисков и решения по ней;
- `architecture/ARCHITECTURE.md` §2.3 и §5 — роли узлов и размещение сервисов;
- `network/map.md` — сеть: сегменты, VIP, внешний путь;
- `host-beellama/gpu-choice-16gb.md` — выбор карты 16 GB: спеки, цены на дату, прогноз.
