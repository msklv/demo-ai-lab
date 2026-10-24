# GPU-планировщики на стенде: что рассмотрено и почему отложено

Вердикты для вопроса «а не прикрутить ли планировщик GPU (KAI/Volcano/Kueue/HAMi)?». Опираются на
факты стенда, а не на фичи продукта; решение-кандидат записано в `IDEAS.md` (реестр идей, формат —
1–2 предложения на идею; глубина блокеров держится здесь, в реестр не выгружается).

## Факты стенда, на которых стоит любой вердикт

- **Одна GPU** — RTX 5060 Ti 16 GB на k8s-04, PCIe Gen4 x4; MIG на GeForce нет, делить карту можно
  только time-slicing/MPS-слоем.
- **GPU занимает только GPUStack** (llama-box/CUDA-worker, nodeSelector на k8s-04) — политика §10 спеки;
  BeeLlama в k8s не исполняется.
- **Драйвер/toolkit — Ansible на хост** (open-модули 595.x, CDI `/var/run/cdi/nvidia.yaml`);
  **NVIDIA GPU Operator не ставится** и в схему не входит.
- **`nvidia.com/gpu` в кластере не публикуется**: device-plugin нет, GPUStack-worker берёт `/dev/nvidia*`
  напрямую ⇒ любой планировщик, работающий на extended resource, видит нулевую ёмкость.
- **RAM мастеров 02/03 — 14 Gi** (~11 Gi после control-plane, уже расписаны; RAGFlow ~10–12 G на 03).
- Приоритет работ: сначала GPUStack (шаг 1 демо), потом любые «улучшайзеры».

## KAI Scheduler — кандидат, отложено

<https://github.com/kai-scheduler/KAI-Scheduler> — Apache-2.0, CNCF sandbox (экс-Run:ai scheduler), релизы
почти еженедельно; чарт `oci://ghcr.io/kai-scheduler/kai-scheduler/kai-scheduler` (ghcr с площадки тянется).

- **Модель работы:** второй планировщик; поды включаются явно — `schedulerName: kai-scheduler` + label
  `kai.scheduler/queue` (default-queue создаётся сразу). Рядом с kube-scheduler живёт штатно, остальные поды
  не трогает.
- **Фичи:** gang/batch (all-or-nothing), иерархические очереди с квотами/DRF-fairshare/reclaim,
  preemption с разделением «приоритет ⟂ вытесняемость», GPU sharing (`NonMemoryEnforced` | `HamiCore` |
  `NvFractions`, HAMi-изолятор ставится отдельно), topology-aware (TAS), DRA, background-pods, elastic.
- **Хард-предпосылка: NVIDIA GPU Operator** — без него GPU-поды не планируются. Это прямой конфликт с
  принятой схемой (драйвер+CDI) плюс образы с `nvcr.io`, которых с площадки нет.
- **Footprint:** operator + scheduler + binder + podgrouper + podgroupcontroller + queuecontroller +
  admission + hook-поды (crdupgrader/kaiConfig/topologyMigration/postCleanup); requests 50–100 m CPU /
  64–128 Mi ⇒ ~0.5–1 Gi суммарно + CRD (Queue, PodGroup, Reservation) + второй планировщик в health-gate.
- **GPUStack через KAI не пойдёт** (воркеры не выставляют `schedulerName`) ⇒ на реальной нагрузке шага 1
  «KAI в работе» не показать; демо свелось бы к примерам `examples/`, которым некуда встать.
- **Матрицы совместимости с k8s 1.35.9 в доках нет** — проверять живьём, не ставить в демо-путь.

### Условия возврата

- ≥2 конкурирующих GPU-ворклоада на карту (несколько моделей на 5060 Ti, time-slicing/MPS) и нужен fairshare;
- появилась вторая GPU/GPU-нода — осмысленны gang + квоты (Ray+KAI интегрированы нативно);
- роль стенда меняется на платформенную с арендаторами (квоты по очередям как история для заказчика).

### Вариант экспоната (НЕ проверен на стенде)

KAI живёт рядом с kube-scheduler, поэтому очереди/квоты/gang/preemption можно показать на **синтетической
ёмкости**: фейковый device-plugin публикует `nvidia.com/gpu` на 02/03, реальную карту не трогаем,
GPU Operator не ставим, контур снимается `helm uninstall`-ом. Вне спеки; перед показом проверить, что
admission KAI не валидирует происхождение ресурса.

## Альтернативы

| Вариант | Когда он и есть ответ |
|---|---|
| kube-scheduler + `nodeSelector`/priorityClass | размещение и вытеснение по RAM — **уже принято** (ADR-0003), для одного претендента достаточно |
| Kueue (CNCF) | job-level квоты на CPU/RAM, без GPU-специфики; брать, если задача про квоты, а не про GPU |
| HAMi | делить одну карту между подами (требование «две модели на 5060 Ti») — самостоятельный слой, KAI для этого не нужен |
| Volcano | тот же класс, что KAI (gang+очереди), но GPU-sharing слабее; отдельно не рассматривать, пока не выполнились условия возврата по KAI |

## Правило ответа

Вердикт первым: «в спеку/демо-путь — нет, в реестр идей — да, при условиях X». Хард-предпосылки продукта
сверять с принятой схемой и с тем, публикуется ли ресурс вообще — не с README продукта.
