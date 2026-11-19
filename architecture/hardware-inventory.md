# Железо: накопители, износ, журнал замен

Состояние железа «на дату»: накопители, износ по SMART, замены и их причины. Новая дата замера —
новая запись в «Хронологии», верхняя таблица держит текущее.

Состав стенда и суммарные характеристики — `HARDWARE.md`; роли узлов — `ARCHITECTURE.md` §2.3 и §5;
разметка дисков — `references/storage-model.md`; серийные номера, MAC и логины — приватный
`inventory.local.md` (вне git).

## Накопители по узлам

| Узел | Накопитель (FW) | Ёмкость | Износ | Записано | Запас | Unsafe shut. | Темп. | Замер |
|---|---|---|---:|---:|---:|---:|---:|---|
| `k8s-01` | ZSPEED SSD 512GB (`09082AA9`) | 476.9 GiB | **11 %** | 13.1 TB | 100 % | 69 | 47 °C | 2026-10-17 |
| `k8s-02` | AirDisk 512GB (`SN27911`) | 476.9 GiB | 0 % | 332 GB | 100 % | 14 | 39 °C | 2026-10-17 |
| `k8s-03` | AirDisk 512GB (`SN27911`) | 476.9 GiB | 0 % | 204 GB | 100 % | 10 | 40 °C | 2026-10-17 |
| `k8s-04` | Netac NV2000 1TB (`GTb57903`) | 931.5 GiB | 0 % | 891 GB | 100 % | 6 | 33 °C | 2026-11-17 |
| `k8s-05` | Netac NV2000 1TB (`GTb57903`) | 931.5 GiB | 0 % | 5.2 GB | 100 % | 2 | 40 °C | 2026-11-08 |

Критических предупреждений SMART нет ни на одной ноде. `FW` — поле `REV` (`lsblk -dno REV`), не серийник.
У `k8s-04` до 2026-11-17 стоял AirDisk 512GB (0 %, 233 GB) — вынут, см. хронологию.

**`k8s-01` — самый изношенный диск стенда:** ресурс ≈119 TB, остаток ≈106 TB против ≈250+ TB у AirDisk.
Поэтому узел вне пула реплик Longhorn (`allowScheduling: false`, 2026-10-24) и контролируется по
`Percentage Used`; он несёт вычисления, не данные (ADR-0003).

## Спецификации накопителей

**AirDisk 512GB** (`k8s-02/03`): OEM Longsys, контроллер Maxio MAP1202, NVMe 1.4, PCIe Gen3 x4, HMB.
TBW по даташиту **256 TB** (P1144 rev. A2), MTBF 1.5 млн ч; для no-name это типично завышено —
Kingston NV2 500GB заявляет 160 TB. Вендорского сайта нет.

**ZSPEED 512GB** (`k8s-01`): публичной документации нет — ни сайта, ни даташита, только бенчмарк-агрегаторы.
Ресурс оценён по контроллеру: 11 % при 13.1 TB ⇒ ≈**119 TB**. Эти 13.1 TB — пробег диска-донора до
ввода в стенд; 69 unsafe shutdowns — его же история питания, не дефект.

**Netac NV2000 1TB** (`k8s-04/05`): [`NT01NV2000-1T0-E4X`](https://www.coxo.ru/catalog/zhestkie_diski_m_2_ssd/zhestkiy_disk_ssd_m_2_1_tb_netac_nv2000_pcie_3_x4_r2500_w2100mb_s_nt01nv2000_1t0_e4x_600_tbw/),
PCIe **3.0 x4**, 2500/2100 МБ/с, **TBW 600 TB** — в 2,3 раза больше AirDisk (256 TB) и в 5 раз больше
оценки ZSPEED (≈119 TB). Оба диска ставились новыми (Power On Hours 0), износ 0 %; 931.5 GiB — вдвое
больше остальных нод.

## Прошивки и версии

Снимок 2026-10-17 (`dmidecode`/`lspci`/`ethtool`); `k8s-05` — замер 2026-11-08.

| Узел | Плата | BIOS | Ядро |
|---|---|---|---|
| `k8s-01` | NucBox K6 | AMI `NucBox K6 102` (2023-11-29) | 6.8.0-147 |
| `k8s-02` | NucBox M6 Ultra | AMI `NucBox M6 Ultra 1.02` (2025-08-06) | 6.8.0-139 |
| `k8s-03` | NucBox M6 Ultra | AMI `NucBox M6 Ultra 1.02` (2025-08-06) | 6.8.0-139 |
| `k8s-04` | NucBox K12 | AMI `NucBox_K12 1.07` (2025-07-24) | 6.8.0-147 |
| `k8s-05` | NucBox K12 | AMI `K12 2.07` (2026-10-07, заводская) | 6.8.0-149 |

BIOS не обновляем: официальных версий для этих плат GMKtec не публикует (раздел Downloads пуст),
а единственная свежая сборка для K12 — неофициальная (2.03/EC 2.02 с 4PDA) и без гарантии возврата.
Следить за `gmktec.com/pages/drivers-and-software`; на K12 скрытые пункты BIOS доступны по `Alt+F5`
на вкладке Advanced — без перепрошивки.

**Сеть:** Realtek RTL8125 2.5GbE (rev 05) ×2 на узел, драйвер `r8169`, firmware NIC `rtl8125b-2_0.0.2`.
**GPU `k8s-04`:** `nvidia-driver-595-open` 595.99.02 (open-модули обязательны для Blackwell), в `hold`;
локальный apt-репо 595.91.07; VBIOS — 5070 Ti `98.03.58.40.34`, 5060 Ti `98.06.39.40.B1`.
**Шлюз:** MikroTik L009UiGS-2HaxD, RouterOS 7.24.5 (`routeros` + `wifi-qcom`), RouterBOARD firmware 7.24.5 —
актуальная stable на дату замера.
**Память:** `k8s-02/03` — 16 GB; `k8s-05` — 2 × 16 GB (оба слота заняты, платформа до 64 GB; второй модуль
добавлен 2026-11-16).

## Хронология

### 2026-11-17 — k8s-04: системный диск 512 GB → 1 TB (клон, без переустановки)

AirDisk выведен, в узле остался Netac 1TB (раньше нёс только `/data`). Клон `dd` в initramfs (477 ГБ,
~30 мин), затем `sgdisk -e` + `growpart` + `pvresize`; LV `data` сохранён с прежним UUID — fstab не правился.
Приёмка: 17/17 подов Running, Longhorn 15/15, `k8s_health.py` — 16 PASS / 1 WARN / 0 FAIL.
Попутно: JetKVM питается от USB ноды (при выключенной ноде KVM недоступен), live через `kexec`
поднимается без HDMI — рабочим путём стал initramfs.

### 2026-11-14 — k8s-05: диск в пуле Longhorn

LV `longhorn` 500G на Netac 1TB, `allowScheduling=true`, резерв 30 %; тестовая реплика легла на `k8s-05`.
Пул: 250G × 3 + 500G = 1.25 TB сырых, ≈625 GB полезных при replica=2. Адреса, UUID и fstab — `references/storage-model.md`.

### 2026-11-10 / 11-09 — k8s-04: карта оказалась RTX 5070 Ti, не 5060 Ti

Спецификация: 16 303 MiB, GB203 (`sm_120`), VBIOS `98.03.58.40.34`, power limit 300 W, PCIe Gen4 x4
(в простое линк уходит в Gen1). Плата — MAXSUN `MS-RTX5070Ti iCraft OC16G`, модель внесена владельцем 11-10.
До 09.11 в узле стояла ASUS `DUAL-RTX5060TI-O16G` (16 311 MiB, VBIOS `98.06.39.40.B1`) — на ней снят эталон 16.10.
Расхождение видно по цифрам: тот же бенчмарк и GGUF — decode 80.8 / 65.4 / 42.5 против 44.7 / 38.6 / 21.7 tok/s
(4K / 32K / 128K), то есть ×1.7–1.9. Свод по докам сделан 09.11, замеры до этой даты оставлены историей.
Спецификации обеих карт — `HARDWARE.md`.

### 2026-11-08 — добавлена k8s-05 (NucBox K12)

R7 H255, iGPU 780M, 16 GB (1×16 из 2 слотов; 2026-11-16 апгрейд до 32 GB), Netac 1TB с нуля, BIOS `K12 2.07`.
F0 и `kubeadm join` через VIP `.240` в тот же день, worker без taint'а; планирование Longhorn на ноде
выключено до 14.11.

### 2026-11-04 — k8s-01: UMA 8G, iGPU отдана RAG-паре

BIOS K6: `UMA Frame Buffer Size` 512 MiB → 8G — иначе GPUStack видел 0.5 GiB и отвергал модель с claim 1.77 GiB.
После ребута `mem_info_vram_total` = 8.00 GiB, ОС видит 23.26 GiB RAM (было 31.4). Пара `bge-m3` + реранк
поднялась на 780M: `/v1/embeddings` 0.10–0.13 с, `/v1/rerank` 0.13–0.21 с.

### 2026-11-03 — k8s-04: UMA 8G, root-LV до 224 GiB, разбор диска

BIOS K12: UMA 3 → 8G (тот же сценарий GPUStack). root-LV расширен до 223.89 GiB, VG исчерпан.
Занято 130 GB из 211: containerd 68 GB (из них 51 GB — снапшоты), gpustack 44 GB, `/home` 15 GB.
При том замере ОС видела 23.26 GiB RAM; в текущем снимке `k8s-04` видит 30.6 GiB — UMA уменьшена позже,
отдельного замера нет. Инцидент: первый старт `bge` с дефолтным `util 0.9` → GPU Hang, нода `NotReady`
~15 мин, восстановилась сама; вывод — флаги писать в модель до первого `Start` (`gpustack-spec` §4.6).

### 2026-10-17 — переустановка 02/03, первый SMART и инвентарь прошивок

Переустановка Ubuntu под дисковую модель: root-LV 100G, ~374G в VG. Побочные эффекты — DHCP-резервации
MikroTik не сработали, containerd/swap/`/etc/hosts` сброшены, p2p-netplan стёрт, swap ON 4G.
В тот же день поставлен `smartmontools` и снят первый SMART (таблица выше), сняты DMI/BIOS, `lspci`/`ethtool`,
`nvidia-smi`, RouterOS по REST — версии прошивок перенесены в приватный `inventory.local.md`.

### 2026-10-12 — аудит ёмкостей

Все ноды (тогда 02/03/04) — NVMe 476.9G. «266G/98G» в старых аудитах — это root-LV, а не диск.

## Как переснять замер

```bash
# на ноде
smartctl -a /dev/nvme0 | grep -iE 'Model Number|Firmware|Percentage Used|Available Spare| \
Data Units Written|Power On Time|Unsafe Shutdowns|Temperature:|Critical Warning'
# на все ноды сразу (пароль sudo — из окружения, см. ansible/README.md)
ansible k8s_nodes -i ansible/hosts.cluster.yml -m shell \
  -a 'smartctl -A /dev/nvme0 | grep -iE "Percentage Used|Data Units Written"' --become
```

Считать по `Percentage Used`: это оценка контроллера, она переживает перезагрузки, в отличие от `diskstats`.
