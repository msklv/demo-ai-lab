# Модель хранения стенда (ADR-0002)

## Факт-таблица (live-замер lsblk, пост-переустановка 2026-10-17)

| Узел | Физический NVMe | root-LV | Свободно в VG |
|---|---|---|---|
| k8s-01 | 476.9G («ZSPEED SSD 512GB», 11% износа — вне пула) | 100G | ~374G |
| k8s-02 | 476.9G («AirDisk 512GB SSD») | 100G | ~374G |
| k8s-03 | 476.9G («AirDisk 512GB SSD») | 100G | ~374G |
| k8s-04 | 476.9G («AirDisk 512GB SSD») | 100G | ~374G |

Проверка без root: `lsblk -d -o NAME,SIZE,MODEL,SERIAL` → физика; `lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT`
→ root-LV/partitions; `df -h` → real used/free. «266G/98G» в старых аудитах = root-LV, не диск; заявленные
ёмкости (например «1 ТБ») сверять живым замером, не фиксировать в доках до проверки. История (root-LV 270G
на 02/03 до переустановки) — `adr/adr-0002-node-storage-model.md` + `architecture/ARCHITECTURE.md` §2.3.

## Решения

1. Отдельный LV под Longhorn на КАЖДОЙ ноде, целевой объём 250G (≈ половина диска 512GB-класса):
   `lvcreate -L 250G -n longhorn ubuntu-vg` + mkfs.ext4 + mount в `/var/lib/longhorn` (fstab).
   k8s-04: 250G помещается (~374G свободно в VG). **k8s-02/03: переустановка Ubuntu 24.04**
   (решение 2026-10-12): root-LV 270G + 250G не влезали (520G > 474G), офлайн-shrink живого root
   отвергнут (ext4 ужимается только на размонтированной ФС). После переустановки разметка как на 04:
   root ~100G + longhorn LV 250G. root-LV не трогать (LVM-shrink назад почти нереализуем).
2. Longhorn: replica=2 (3 ноды хранения), `defaultSettings.replicaZoneSoftAntiAffinity: true` (zone-меток нет —
   без этого том висит вечно-degraded, «no disk candidates»; проверено на стенде), open-iscsi на всех нодах,
   default StorageClass = longhorn (требование и GPUStack-чарта, и RAGFlow-чарта).
3. Модели GPUStack на 04 — hostPath-каталог, НЕ в Longhorn (тома ×2 реплик съедают ёмкость без пользы).
4. Запас на 04: ~20–25G под 1–2 активные модели (qwen3-8b/14b AWQ 4-bit + bge-m3 + whisper small/base) —
   помещается; ротация моделей обязательна.
