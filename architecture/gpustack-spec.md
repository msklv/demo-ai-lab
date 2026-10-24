# Спецификация установки GPUStack (инференс-слой стенда demo-ai-lab)

> **Версия:** v1.3 (живой замер 2026-10-24) · **Статус:** спека, **не установлено** — G0–G8 не выполнены
> **Цель:** шаг 1 демо — GPUStack 2.2.3 helm-чартом в существующий кластер, GPU-воркер на k8s-04
> (RTX 5060 Ti 16G), бэкенд — только раннер каталога `cuda13.0-vllm0.25.1`, модели в AWQ;
> UI + OpenAI-совместимый API — `api.demo-ai-lab.ru`
> **Механизм развёртывания:** `helm install` с консоли (values — `ansible/values-gpustack.yaml` в git),
> манифесты (Ingress, Certificate, RuntimeClass) — Argo CD; секретов в git нет

Стиль-образцы: `architecture/k8s-install-spec.md` (F\*), `architecture/external-access-spec.md` (E\*),
`architecture/keycloak-spec.md` (K\*). Фазы F/E/K не пересматриваются, у GPUStack своя буква — **G1–G8**.

## 1. Что ставим и где (решения)

| Параметр | Решение | Обоснование |
|---|---|---|
| Чарт | `oci://registry-1.docker.io/gpustack/gpustack-chart` **2.2.3**, digest `sha256:b660ab0ba7224def2aa12559803c776272dd854c7af264dee2529772f9299641`; `appVersion 2.2.3`; `kubeVersion >=1.30.0-0` | `helm show chart` (2026-10-24); кластер 1.35.9 — требование выполнено |
| Helm | консоль `v4.1.3` (GoVersion go1.26.1) | доки требуют ≥ v3.18.4; `helm pull` / `show chart` / `template` на 4.1.3 проходят (§2) — открытый вопрос demo-plan закрыт: рендер совместим, `install` проверяется в G3 |
| Namespace | `gpustack` (новый) | изоляция; ApplicationSet `infra-apps` создаёт ns по имени каталога |
| Server | StatefulSet, **1 реплика** (HA не поддерживается чартом), порт API `30080`, metrics `10161` | доки GPUStack 2.2 — «does not support more than one replica» |
| БД | встроенный PostgreSQL в томе сервера (`externalDatabaseURL: null`) | демо, внешней БД нет; бэкап — снапшот PVC |
| Данные сервера | PVC **20Gi**, `storageClass` не задаём → default `longhorn` (r=2, т.е. 40Gi физически) | 244Gi свободно на каждом узле Longhorn (§2); 100Gi дефолта чарта для демо избыточны |
| Размещение server | `preferred` nodeAffinity на `demo-ai-lab/role=ingress` (пара k8s-02/03) | k8s-04 занят Argo CD, Higress-контроллером, Longhorn и самим инференсом (ADR-0003: 02/03 — лёгкие сервисы) |
| Worker GPU | DaemonSet `<rel>-worker-nvidia`, nodeSelector `feature.node.kubernetes.io/pci-10de.present: "true"` (метка уже есть на k8s-04), `runtimeClassName: nvidia`, `hostNetwork: true`, порты `10150/10151` | рендер чарта (§2); NFD-правило F4 метку выставило |
| Worker CPU | DaemonSet `<rel>-worker`, nodeSelector `feature.gpustack.ai/acceleratable: "false"` — **метку ставим только на k8s-01** | узел 01 — компьют-heavy и вне пути показа (ADR-0003); 02/03 не трогаем — они несут ingress-VIP |
| RuntimeClass | `nvidia` → handler `nvidia`, **объект создаём сами** (чарт его не создаёт) | рендер чарта: `runtimeClassName: nvidia`, объекта нет (§2) |
| containerd | drop-in для handler `nvidia` в **схеме version 3** (`io.containerd.cri.v1.runtime`) | **измерено: сейчас handler отсутствует** — старый `99-nvidia.toml` (version 2) containerd 2.2.1 не применяет (§2, R-G1) |
| Бэкенд | только раннер каталога `gpustack/runner:cuda13.0-vllm0.25.1` (8.82 GiB сжатым, ~20.5 ГБ на диске, digest `sha256:f60f9b62e661801f84ffe1b78201574feeb7e5b9b9fc62299c1d070bc2aa0fe2`) | драйвер 595.99.02 → CUDA 13.x; llama-box/GGUF/кастомный llama.cpp исключены решением владельца |
| Модели | `Qwen/Qwen3-14B-AWQ` (9.31 GiB, sha `31c69efc2946`) — основная; `BAAI/bge-m3` (4.27 GiB, sha `5617a9f61b02`) — эмбеддинги; `Qwen3-8B-AWQ` (5.69 GiB) — **опция**, только при запасе диска (R-G5) | 16 GiB VRAM: 14B AWQ 9.3 GiB + KV при `max-model-len 8192` ≈ 1.3 GiB |
| Хранилище моделей | hostPath `/var/lib/gpustack` на k8s-04 (`worker.dataDir`), каталоги `<repo-slug>/` (каталог целиком: шарды + конфиги) | склада предзагрузки нет (снят 2026-10-24) — веса скачиваются с HF на консоли и кладутся на ноду по LAN на подготовке |
| Публикация | свой Ingress + `Certificate` в ns `gpustack` → `api.demo-ai-lab.ru`; ингресс чарта **выключен** (`server.ingress.hostname: null`) | сертификат в values = серт в git (запрещено, §8 AGENTS); правило E-серии — TLS в namespace Ingress'а |
| SSO | клиент Keycloak `gps`, redirect строго `<server-url>/auth/oidc/callback`; API-путь `/v1/*` — по ключу GPUStack, не по SSO | `architecture/endpoints.md`; фаза G7 блокирована K1–K7 |
| Приоритет | **нет** ручки `resources`/`priorityClassName` для server и worker в чарте → поды BestEffort, priority 0 | шаблоны чарта: `resources: {}` захардкожено (§2) → компенсируем размещением и мониторингом (R-G6) |
| Discovery/API | `GPUSTACK_SERVER_URL` воркера = `http://gpustack-server.gpustack.svc:30080` | рендер чарта (headless Service) |
| Ключи API / админ | bootstrap-пароль админа — из лога пода, кладём в `gpustack-admin.local.md` (не в git); ключи моделей создаются в UI | у владельца нет admin-ключа: все действия с GPUStack — через UI, не curl-скриптами |

## 2. Предпосылки — проверено 2026-10-24 (живой замер)

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get nodes -o custom-columns='NODE:.metadata.name,V:.status.nodeInfo.kubeletVersion,RAM:.status.allocatable.memory,GPU:.status.allocatable.nvidia\.com/gpu,TAINTS:.spec.taints[*].key'
kubectl top nodes; kubectl get sc; kubectl get ingressclass; kubectl get runtimeclass
helm version; helm list -A; kubectl get applications -n argocd
```

| Что | Факт | Значение для спеки |
|---|---|---|
| Ноды | все `Ready`, v1.35.9, taints нет: 01 — `32 029 372Ki` CPU-allocatable, 02/03 — `15 548 856Ki`, 04 — `29 455 896Ki` | RAM-бюджет: 04 ≈28.1 GiB allocatable |
| `nvidia.com/gpu` | **не публикуется** ни на одной ноде (`<none>`) | GPUStack не полагается на device plugin; GPU отдаёт воркеру через `runtimeClassName` + CDI (проверка — G4) |
| Загрузка | 01 — 2.8 GiB, 02 — 3.3 GiB, 03 — 3.4 GiB, **04 — 3.0 GiB** (из 28.1) | на 04 уже живут Argo CD, cert-manager, Higress-контроллер, Longhorn (Metrics API работает — F10) |
| StorageClass | `longhorn` (**default**, r=2), `longhorn-static` | PVC сервера без `storageClassName` |
| IngressClass | `higress` (higress-core 2.1.9) | `gateway.ingressClassname=higress`, `higress-core.enabled=false` |
| RuntimeClass | **`No resources found`** | объект `nvidia` создаём сами (G1) |
| NFD-метка GPU | `feature.node.kubernetes.io/pci-10de.present=true` на k8s-04 | nodeSelector GPU-воркера чарта удовлетворён |
| Метка `feature.gpustack.ai/acceleratable` | отсутствует на всех нодах | CPU-воркер не сядет никуда, пока не поставим метку (G2) |
| Аппаратный путь | RTX 5060 Ti 16 311 MiB, драйвер `595.99.02`, compute cap `12.0` (sm_120); `nvidia-smi`: 2 MiB занято, 0 % | GPU свободен; **AWQ-ядра под sm_120 — риск R-G4** |
| NVIDIA Toolkit | `1.20.1`, бинарь `/usr/bin/nvidia-container-runtime` есть, CDI `/var/run/cdi/nvidia.yaml` (23.10 09:01), юнит `nvidia-cdi-refresh.path` enabled | CDI генерируется автоматически |
| **CRI runtimes (журнал containerd)** | `starting cri plugin … "runtimes":{"runc":…}` — **handler `nvidia` отсутствует**; `/etc/containerd/conf.d/99-nvidia.toml` — `version = 2` и плагин `io.containerd.grpc.v1.cri` (legacy), основной конфиг — `version = 3` | **блокер**: `runtimeClassName: nvidia` упадёт; фаза G1 |
| Диск k8s-04 | root LV 98G / занято 38G / **свободно 56G**; `/var/lib/longhorn` 246G (46M занято), Longhorn: 244Gi free на 02/03/04, на 01 — 78Gi | математика диска в R-G5 |
| Helm/чарт | `helm v4.1.3`; `helm show chart … --version 2.2.3` → `Pulled`, `kubeVersion '>=1.30.0-0'`, зависимость `higress-core 2.1.9`; `helm template` с плановыми values → **exit 0, 1333 строки** | рендер проверен до установки |
| Рендер: что создаёт чарт | ServiceAccount ×3, Secret ×3 (`gpustack-image-pull-secret`, `registration-token`, `gpustack-jwt-key`), ConfigMap ×3, ClusterRole ×4 + bindings, Service ×4, DaemonSet ×2 (CPU + nvidia), Deployment ×1 (`gpustack-higress-plugins`), StatefulSet ×1, Ingress ×1, Job ×2 (helm-hooks `post-install/post-upgrade`) | ингресс рендерится только при `server.ingress.hostname`; `tls`-секции нет |
| Рендер: сервер | `StatefulSet gpustack-server`, `serviceName: gpustack-server`, PVC-шаблон `gpustack-data-dir` (`ReadWriteOnce`, size из values), Service `gpustack-server-cluster-ip:30080` (его и берёт ингресс) | свой Ingress бэкендим на `*-cluster-ip`, не на headless |
| Рендер: воркеры | nvidia-DS: `runtimeClassName: nvidia`, `hostNetwork: true`, `hostIPC: true`, `privileged: true`, монтирует `/var/lib/gpustack`, `/var/run/cdi`, `/var/lib/kubelet/device-plugins`; CPU-DS: как выше без runtimeClass; **required** podAntiAffinity по hostname между воркерами | два воркера на одной ноде невозможны |
| TLS/внешний путь | `ClusterIssuer letsencrypt-wildcard` → **Ready**; `certificate demo-wildcard` в `demo-test` Ready; `dig @1.1.1.1 api.demo-ai-lab.ru` → две A-записи Cloudflare anycast (зона proxied), `dig @192.168.10.1` → `192.168.10.230` | новый хост заводить не нужно (E5/E7), нужен только Ingress + свой `Certificate` |
| Argo CD | приложения `infra`, `root-app` — `Synced/Healthy`; `argocd-repo-server` = `quay.io/argoproj/argocd:v3.5.5` | манифесты G6 идут через существующий ApplicationSet |
| Пространство `gpustack` | отсутствует | конфликтов имён нет |
| Сеть до интернета с 04 | `huggingface.co` и `registry-1.docker.io` отвечают (307/401), канал площадки 4–6 МБ/с | первой загрузке 14B (9.3 GiB) ≈ 30–45 мин, раннера (20.5 ГБ) — часы: прогревать заранее (R-G7) |

## 3. Секреты и приватные файлы

| Объект | Что внутри | Кто/что читает | Где живёт |
|---|---|---|---|
| `gpustack-admin.local.md` | логин `admin` + bootstrap-пароль, ключи API моделей | человек, консоль | корень репо, `*.local.md` → `.gitignore` (в git **не** попадает) |
| Secret `registration-token` (ns `gpustack`) | токен регистрации воркеров | DaemonSet воркеров (`envFrom`) | генерируется чартом, в git нет |
| Secret `gpustack-jwt-key` (ns `gpustack`) | подпись сессий сервера | сервер | генерируется чартом |
| `gpustack-tls` (ns `gpustack`) | LE-серт `api.demo-ai-lab.ru` | Higress | создаёт cert-manager из `Certificate`; **в git только `Certificate`, не серт** |
| клиент Keycloak `gps` | client secret | OIDC сервера GPUStack | `keycloak-clients.local.md` (не в git) |

Правила:

- `server.ingress.tls.cert` / `.key` в values **не заполняем никогда** — это PEM в git.
- Bootstrap-пароль: чарт при 1 реплике генерирует пароль на узел и печатает инструкцию получения в логе
  (`kubectl -n gpustack logs statefulset/gpustack-server`); сразу после первого входа — сменить,
  новый записать в `gpustack-admin.local.md`. `bootstrapPasswordSecret.enabled` оставляем `false`
  (статический пароль в values = пароль в git).
- Приёмка гигиены перед коммитом: `git check-ignore -v gpustack-admin.local.md` + grep-фильтр из `AGENTS.md`.

## 4. Развёртывание

### 4.1. Почему helm напрямую, а не Argo-приложением

Чарт публикуется как OCI-артефакт на `registry-1.docker.io`, а `AppProject infra` в
`gitops/root/applicationsets.yaml` разрешает только `sourceRepos: https://github.com/msklv/demo-ai-lab.git`.
Argo-приложение с Helm-источником потребовало бы правки AppProject и вложенного app-of-apps
(ApplicationSet создаёт приложения только типа «каталог»). Прецедент стенда — релизы F2–F5, F8, F10
поставлены helm'ом напрямую, перевод под Argo — отдельный план adoption (`gitops/README.md`).
Поэтому: **релиз — helm, манифесты — Argo**.

### 4.2. Файлы в git

| Файл | Что |
|---|---|
| `ansible/values-gpustack.yaml` | values релиза (единственный источник правды; вне каталогов, которые сканирует ApplicationSet — иначе Argo попытается применить values как манифест) |
| `gitops/infra-apps/gpustack/ingress.yaml` | Ingress `api.demo-ai-lab.ru` → `gpustack-server-cluster-ip:30080` |
| `gitops/infra-apps/gpustack/certificate.yaml` | `Certificate` `gpustack-tls` (ClusterIssuer `letsencrypt-wildcard`) |
| `gitops/infra-apps/infra/runtimeclass-nvidia.yaml` | `RuntimeClass nvidia` (кластерный объект — рядом с NodeFeatureRule F4) |
| `ansible/pb-nvidia-container-toolkit.yml` | правка: drop-in в схеме version 3 вместо `nvidia-ctk … configure` (G1) |

### 4.3. `ansible/values-gpustack.yaml`

```yaml
global:
  nodeSelector: {}
image:
  tag: v2.2.3                 # пин чарта 2.2.3; образы — по digest из §1 (сверять в G2)
higress-core:
  enabled: false              # у стенда свой Higress 2.1.9 (ADR-0001)
gateway:
  ingressClassname: higress   # вкл. in-cluster gateway mode на существующем шлюзе
server:
  ingress:
    hostname: null            # Ingress и TLS — свои манифесты (серт в git нельзя)
  dataVolume:
    size: 20Gi                # longhorn default r=2 → 40Gi физически
  affinity:
    nodeAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          preference:
            matchExpressions:
              - key: demo-ai-lab/role     # метка есть на k8s-02 и k8s-03 (§2)
                operator: In
                values: ["ingress"]
worker:
  enabled: true
  gpuVendors: [nvidia]
  dataDir: /var/lib/gpustack
operator:
  resources:                  # дефолт чарта 4 CPU / 8Gi — для 28-GiB ноды избыточен
    requests: {cpu: 200m, memory: 256Mi}
    limits:   {cpu: "2",  memory: 2Gi}
```

```bash
helm install gpustack oci://registry-1.docker.io/gpustack/gpustack-chart \
  --version 2.2.3 -n gpustack --create-namespace \
  -f ansible/values-gpustack.yaml --set worker.enabled=false    # G3; воркеры — G4
```

Почему именно так:

- `higress-core.enabled=false` + `gateway.ingressClassname=higress` — прямое требование доки GPUStack
  при существующем контроллере; иначе второй шлюз подерётся за `IngressClass` (ADR-0001).
- `server.ingress.hostname: null` — чартовый ингресс не умеет ссылаться на готовый Secret, только
  принимать PEM в values; свой Ingress ещё и переживает `helm upgrade`.
- `worker.enabled=false` на первом шаге: воркер без рабочего handler `nvidia` уходит в
  `CreateContainerConfigError` и маскирует результат установки сервера.
- `preferred` (не `required`) affinity: hard-пин на 02/03 = `Pending` при потере обоих узлов
  (грабля из `references/service-spec-authoring.md`).

### 4.4. RuntimeClass и drop-in containerd (G1)

```yaml
# gitops/infra-apps/infra/runtimeclass-nvidia.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: nvidia
handler: nvidia
```

```toml
# /etc/containerd/conf.d/99-nvidia.toml — схема version 3 (containerd 2.2.1)
version = 3
[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia]
  runtime_type = 'io.containerd.runc.v2'
  [plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.nvidia.options]
    BinaryName = '/usr/bin/nvidia-container-runtime'
```

Старый файл (`version = 2`, плагин `io.containerd.grpc.v1.cri`) — заменяется, не дополняется:
в 2.2.1 он не применяется (R-G1). Если после рестарта handler в журнале не появился — писать секцию
в основной `/etc/containerd/config.toml` (тот же путь ключа) и проверять снова, а не «надеяться».

### 4.5. Модели и каталог

- Веса кладутся на k8s-04 в `/var/lib/gpustack/models/<repo-slug>/` (каталог целиком: шарды + конфиги;
  один файл не годится — vLLM собирает модель из каталога).
- Регистрация в UI: `Catalog` → GPUStack-модель, либо источник `local_path` в кастомном каталоге
  (`source: local_path`, `local_path: /var/lib/gpustack/models/Qwen3-14B-AWQ` — схема каталога 2.2).
  Не угадывать путь: имя страницы/поля зафиксировать фактом при первом входе.
- Параметры деплоя 14B (16 GiB VRAM): `--max-model-len 8192`, `--gpu-memory-utilization 0.90`,
  `--served-model-name qwen3-14b`; 32k контекст в 16 GiB не влезает (KV ≈ 5.2 GiB) — не выставлять.

## 5. Конфигурация домена: что должно быть настроено после установки

| Пункт | Значение/действие | Проверка |
|---|---|---|
| Админ | `admin` + bootstrap-пароль из лога; пароль сменён, лежит в `gpustack-admin.local.md` | вход в UI |
| Кластер | `kubernetes` (default) — GPUStack сам создаёт кластер при установке чартом | UI → `Clusters`: кластер `Default` |
| Воркеры | `k8s-04` — GPU (16 311 MiB), `k8s-01` — CPU | UI → `Workers`: две записи `Online` |
| Модель LLM | `Qwen3-14B-AWQ`, vLLM, `max-model-len 8192` | UI → статус `Running`; Playground отвечает |
| Эмбеддинги | `bge-m3` (не запускать одновременно с 14B, если VRAM не хватает — очередь) | `/v1/embeddings` |
| Ключи API | один ключ на демо-потребителя (`owu`, `rag`, `qm`, `her`) с квотой | UI → `API Keys` |
| SSO | клиент `gps`, redirect `<server-url>/auth/oidc/callback` (после K1–K7) | вход через `auth.demo-ai-lab.ru` |
| Роут наружу | Ingress + `Certificate` (G6) | `curl` из LAN и снаружи |

## 6. Фазы и критерии приёмки

### G0. Предпосылки — перепроверить фактом перед работой

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get nodes; kubectl get sc; kubectl get ingressclass
kubectl get node k8s-04 -o jsonpath='{.metadata.labels.feature\.node\.kubernetes\.io/pci-10de\.present}{"\n"}'
kubectl get clusterissuer letsencrypt-wildcard -o jsonpath='{.status.conditions[0].type}{"\n"}'
helm version
```

**Приёмка:** 4 ноды `Ready`; `longhorn` default; `higress` IngressClass; метка `true`; issuer `Ready`;
`helm` ≥ 3.18.4. Расхождение — стоп: цифры §2 устарели, обновить спеку.

### G1. Handler `nvidia` в containerd + RuntimeClass — **блокер**

```bash
# 0) ssh-цель ноды с GPU: логин берётся из локального приватного хранилища, в доку не пишется
NODE04="<node-user>@192.168.10.252"
# 1) заменить drop-in на схему version 3 (содержимое — §4.4). Через ansible, не руками:
#    правится ansible/pb-nvidia-container-toolkit.yml, затем:
ansible-playbook -i ansible/hosts.gpu.yml ansible/pb-nvidia-container-toolkit.yml \
  -e nvidia_ctk_version="1.20.1-1"
# 2) рестарт containerd на k8s-04 — поды ноды перезапускаются (Argo CD, Higress, Longhorn живут там же):
ssh "$NODE04" 'sudo systemctl restart containerd && systemctl is-active containerd'
# 3) RuntimeClass — через Argo (файл §4.4) или kubectl apply -f
kubectl apply -f gitops/infra-apps/infra/runtimeclass-nvidia.yaml
kubectl get runtimeclass nvidia
```

**Приёмка (обе строки обязательны):**

```bash
# а) handler виден в эффективном конфиге CRI
ssh "$NODE04" 'journalctl -u containerd -o cat | grep "starting cri plugin" | tail -1 | tr "," "\n" | grep -c nvidia'
#   ожидание: число > 0 (сейчас 0 — это и есть блокер)

# б) GPU виден внутри контейнера с runtimeClassName (единственное настоящее доказательство)
kubectl -n gpustack run gpu-smoke --restart=Never \
  --image=nvidia/cuda:12.8.0-base-ubuntu24.04 \
  --overrides='{"spec":{"runtimeClassName":"nvidia","nodeSelector":{"kubernetes.io/hostname":"k8s-04"}}}' \
  -- nvidia-smi
kubectl -n gpustack logs gpu-smoke        # ожидание: строка «NVIDIA GeForce RTX 5060 Ti … 16311MiB»
kubectl -n gpustack delete pod gpu-smoke
```

Образ smoke-пода (≈400 МБ) в локальном сторе 04 может отсутствовать: предтянуть разово
(`skopeo inspect --override-arch amd64` → digest, без digest образ не брать). На сцене этот шаг не повторяется.

### G2. Метки узлов и прогрев ноды (образы и веса)

Склада предзагрузки нет (снято 2026-10-24): всё тянется **прямым pull с самой ноды** на подготовке.
Порядок принципиален — прогрев до `helm install`, иначе первый старт сервера висит в `ImagePullBackOff`,
а приезд раннера при деплое модели занимает часы.

```bash
# CPU-воркер — только k8s-01 (02/03 — ingress-пара)
kubectl label node k8s-01 feature.gpustack.ai/acceleratable=false --overwrite
kubectl get node k8s-01 -o jsonpath='{.metadata.labels.feature\.gpustack\.ai/acceleratable}{"\n"}'

# образы: тянем на 04 заранее (≈24.4 ГБ суммарно, раннер — 20.5 ГБ из них).
# crictl на нодах НЕ установлен (замер 2026-10-24) — только ctr с namespace k8s.io
ssh "$NODE04" 'sudo ctr -n k8s.io images pull docker.io/gpustack/gpustack:v2.2.3 && \
  sudo ctr -n k8s.io images pull docker.io/gpustack/gpustack-operator:v0.5.4 && \
  sudo ctr -n k8s.io images pull docker.io/gpustack/higress-plugins:0.3.0 && \
  sudo ctr -n k8s.io images pull docker.io/gpustack/runner:cuda13.0-vllm0.25.1'
ssh "$NODE04" 'sudo ctr -n k8s.io images ls -q | grep -E "gpustack|runner"'

# веса — каталогами, не файлами (10.0 ГБ + 4.6 ГБ): качаем НА КОНСОЛИ, кладём по LAN.
# На ноде нет python-пакета huggingface_hub (замер 2026-10-24) — путь «скачать на 04 python-ом» не работает.
ssh "$NODE04" 'sudo install -d -o "$USER" -g "$USER" /var/lib/gpustack/models'
hf download Qwen/Qwen3-14B-AWQ --local-dir /tmp/weights/Qwen3-14B-AWQ
hf download BAAI/bge-m3 --local-dir /tmp/weights/bge-m3
rsync -a --info=progress2 /tmp/weights/Qwen3-14B-AWQ /tmp/weights/bge-m3 "$NODE04":/var/lib/gpustack/models/
ssh "$NODE04" 'ls -la /var/lib/gpustack/models/Qwen3-14B-AWQ /var/lib/gpustack/models/bge-m3'
```

`hf` есть на консоли (`huggingface-cli download …` — синоним). Если качать всё же на ноде — поднять venv
(`python3 -m venv ~/hf && ~/hf/bin/pip install -U huggingface_hub`, затем `snapshot_download` из него).
Кэш LM Studio и «модели на консоли» не считаются: каталог обязан лежать на k8s-04 целиком, с шардами и конфигами.

**Приёмка:** метка `false` на 01 и отсутствует на 02/03; в CRI на 04 есть
`docker.io/gpustack/gpustack:v2.2.3`, `gpustack-operator:v0.5.4`, `higress-plugins:0.3.0`,
`runner:cuda13.0-vllm0.25.1` и `nvidia/cuda:12.8.0-base-ubuntu24.04` (smoke из G1);
в `/var/lib/gpustack/models/` — полные каталоги (≥2 шарда `.safetensors` + конфиги);
`df -h /` на 04 — свободно ≥ 10 ГБ (R-G5).

### G3. Установка сервера (без воркеров)

```bash
helm install gpustack oci://registry-1.docker.io/gpustack/gpustack-chart \
  --version 2.2.3 -n gpustack --create-namespace \
  -f ansible/values-gpustack.yaml --set worker.enabled=false
kubectl -n gpustack get sts,pod,svc,pvc
kubectl -n gpustack logs statefulset/gpustack-server | grep -i -m3 password
```

**Приёмка:**

1. `statefulset.apps/gpustack-server` — `1/1`, под `Running`; PVC `gpustack-data-dir-gpustack-server-0` — `Bound` (20Gi).
2. Сервер на узле 02 или 03 (`kubectl -n gpustack get pod -o wide`), не на 04.
3. `kubectl -n gpustack exec sts/gpustack-server -- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:30080/healthz` → `200`.
4. Helm-hook Job'ы `gpustack-operator-worker-deployment` / `-cleanup` — `Completed` (при Argo-подходе в будущем
   они станут PostSync; сейчас — забота helm).
5. **Стенд не пострадал:** `kubectl -n demo-test get ingress` без изменений; `curl -sk https://echo.demo-ai-lab.ru/` → 200;
   `kubectl -n higress-system get pods` — `Running`; `python3 scripts/k8s_health.py --brief` — без новых FAIL.
6. Bootstrap-пароль перенесён в `gpustack-admin.local.md`, вход в UI выполнен, пароль сменён.

### G4. GPU-воркер на k8s-04 (+ CPU-воркер на k8s-01)

```bash
helm upgrade gpustack oci://registry-1.docker.io/gpustack/gpustack-chart \
  --version 2.2.3 -n gpustack -f ansible/values-gpustack.yaml
kubectl -n gpustack get ds,pod -o wide
kubectl -n gpustack logs ds/gpustack-worker-nvidia --tail=50
```

**Приёмка:**

1. `gpustack-worker-nvidia` — `DESIRED 1 / READY 1` на `k8s-04`; `gpustack-worker` (CPU) — `1/1` на `k8s-01`.
2. В UI `Workers`: `k8s-04` `Online` с GPU «NVIDIA GeForce RTX 5060 Ti · 16 GiB», `k8s-01` — CPU.
3. В логе воркера нет `failed to ... runtime` / `no runtime for nvidia`; CDI-устройства видны.
4. `nvidia.com/gpu` (если воркер публикует device plugin через `/var/lib/kubelet/device-plugins`) —
   зафиксировать факт: `kubectl get node k8s-04 -o jsonpath='{.status.allocatable}'`. Отсутствие — не FAIL:
   планирование моделей делает GPUStack, а не kube-scheduler.
5. **Дрилл «шлюз не заложник GPUStack»** (R-G3): `kubectl -n gpustack scale sts/gpustack-server --replicas=0`,
   затем рестарт пода Higress-шлюза на 02/03 → `curl -sk https://echo.demo-ai-lab.ru/` обязан остаться 200
   (шлюз не должен ждать плагины из ns `gpustack`). Возврат: `--replicas=1`.

### G5. Модель 14B AWQ через UI

Действия в UI (скриптового деплоя не даём — admin-ключа нет):

1. `Catalog` → `Qwen3-14B-AWQ`, либо источник `local_path` = `/var/lib/gpustack/models/Qwen3-14B-AWQ`.
2. Backend — `vLLM` (раннер `cuda13.0-vllm0.25.1`), `--max-model-len 8192`, `--gpu-memory-utilization 0.90`,
   `--served-model-name qwen3-14b`; реплика 1, воркер `k8s-04`.
3. Дождаться `Running` (первый старт тянет раннер, если он не прогрет — часы, а не минуты; это G2).

**Приёмка:**

```bash
kubectl -n gpustack get deploy,pod | grep -i qwen            # под модели Running
ssh "$NODE04" 'nvidia-smi --query-gpu=memory.used --format=csv,noheader'
#   ожидание: ~11–14 GiB занято, 0 MiB — модель не поднялась
```
Playground в UI отвечает осмысленно; в логе модели нет `CUDA out of memory` / `no kernel image` (R-G4).
Рестарт пода модели → снова `Running` (модель не перекачивается — веса локальные).

### G6. Публикация `api.demo-ai-lab.ru`

```bash
kubectl apply -f gitops/infra-apps/gpustack/certificate.yaml -f gitops/infra-apps/gpustack/ingress.yaml
kubectl -n gpustack get certificate gpustack-tls    # READY=True, SECRET=gpustack-tls
dig @192.168.10.1 api.demo-ai-lab.ru +short         # 192.168.10.230
curl -sI https://api.demo-ai-lab.ru/ | head -1      # из LAN: 200/302, не 404
```

**Приёмка:** из LAN `200/302`; снаружи `curl -sI https://api.demo-ai-lab.ru/` — не `530`/`1033`
(путь туннеля E5/E7); серт — LE wildcard, цепочка валидна (`openssl s_client`); `/v1/models` без ключа → `401`
(значит, API закрыт). Служебные пути (`/admin`) наружу не выносим отдельным правилом — по `E6`
админка доступна там же, где UI, SSO включается в G7.

### G7. SSO (заблокирована Keycloak K1–K7)

1. В `keycloak-clients.local.md` + realm `dev`: клиент `gps`, confidential, redirect
   `<server-url>/auth/oidc/callback` — точный redirect брать из лога/доки GPUStack при первом включении, не угадывать.
2. `server.environmentConfig` — OIDC-переменные (`GPUSTACK_OIDC_*`: issuer/realm, client id, secret ref);
   секрет — из Secret в кластере, **не** литералом в values.
3. **Приёмка:** вход в UI редиректит на `auth.demo-ai-lab.ru`, возврат даёт сессию; API-ключевой путь `/v1/*`
   продолжает работать по ключу GPUStack (браузерный SSO на него не распространяется).

### G8. Приёмка шага 1 демо

```bash
python3 scripts/k8s_health.py --brief          # код 0
python3 scripts/env_health.py --brief          # код 0
kubectl -n gpustack get pods -o wide
```

1. Все поды `gpustack` `Running`, рестартов за час — 0.
2. `api.` отвечает из LAN и снаружи; UI открывается; модель `Running`.
3. `nvidia-smi` на 04 показывает занятую VRAM модели; GPU не шарится с другими подами.
4. Снапшот Longhorn тома сервера снят (перед демо) — `kubectl -n longhorn-system get snapshots.longhorn.io`.
5. Диск k8s-04: `ssh "$NODE04" 'df -h / /var/lib/longhorn'` — свободно на `/` ≥ 10 ГБ (R-G5).
6. Репетиция с таймером: шаг 1 ≤ 10 мин (`references/demo-plan.md` §«Репетиция»); последовательность
   показа зафиксирована в `references/demo-plan.md`.

## 7. Операции

| Задача | Как |
|---|---|
| Health | `kubectl -n gpustack get pods`; `curl -s http://gpustack-server.gpustack.svc:30080/healthz` из кластера; `scripts/k8s_health.py --brief` |
| Бэкап перед демо/апгрейдом | снапшот тома `gpustack-data-dir-gpustack-server-0` (Longhorn); веса моделей не бэкапить — их источник HF |
| Апгрейд | прогреть новые образы и раннер на ноде → `helm upgrade … --version <новая>` → дождаться миграции БД (`/healthz` 200) → `helm rollback` при провале; порядок обязателен: без предтяжки апгрейд встанет на pull |
| Переустановка | `helm uninstall gpustack -n gpustack` **оставляет PVC** `gpustack-data-dir-gpustack-server-0`; удаление тома = потеря админа, моделей, ключей |
| Ротация registration token | удалить Secret `registration-token` + `helm upgrade` (чарт перегенерирует) → перезапустить DS воркеров |
| Ротация ключей API | UI → `API Keys`; старый ключ удалить, конфиги потребителей (`owu`/`rag`/`qm`/`her`) обновить синхронно |
| Остановка GPU-нагрузки | UI → модель `Stop` (не `kubectl scale` — состояние разъедется) |

## 8. Риски

| ID | Риск | Что делаем |
|---|---|---|
| **R-G1** | Handler `nvidia` в containerd отсутствует (измерено): `runtimeClassName: nvidia` падает → GPU-воркер не стартует | G1 до установки; приёмка — запись в журнале CRI + GPU-смок в контейнере |
| **R-G2** | Доки GPUStack 2.2: развёртывание на k8s с Higress — **experimental**; интеграция с внешним шлюзом не гарантирована | Держим `higress-core.enabled=false`; при провале gateway mode — фолбэк: модели через сервисный порт + собственный Ingress, без gateway-функций (маршруты на ключи/лимиты теряются) |
| **R-G3** | Шлюз при рестарте тянет Wasm-плагины с Deployment `gpustack-higress-plugins`: недоступность ns `gpustack` блокирует старт шлюза → падает всё демо | Дрилл в G4 п.5; если подтвердится — не давать GPUStack управлять плагинами шлюза, плагины ставить штатным путём Higress (спека guardrail — отдельно) |
| **R-G4** | AWQ-ядра под sm_120 (compute cap 12.0, Blackwell): возможен `no kernel image` или медленный скалярный путь | G5 фиксирует факт на репетиции; фолбэк — `Qwen3-8B-AWQ`, затем FP8/bf16-вариант меньшей модели |
| **R-G5** | Диск k8s-04: **56 ГБ свободно** на root-LV; образы ≈24.4 ГБ (раннер 20.5 + сервер 3.1 + operator 0.6 + plugins 0.2) + веса 14.6 ГБ (14B-AWQ 10.0 + bge-m3 4.6) ≈ **39 ГБ → запас ≈17 ГБ**; 8B (+6.1) влезает, но оставляет ≈11 ГБ, фолбэк-раннер `cuda12.9` (+26 ГБ) — **не влезает** | Только 14B + bge-m3; чистить старые образы перед апгрейдом (`ctr images rm`); модели не дублировать в других каталогах; `df -h /` на 04 — в чек-лист G8 |
| **R-G6** | В чарте нет `resources`/`priorityClassName` для server и worker (захардкожено `resources: {}`) → BestEffort/QoS, первые кандидаты на вытеснение при RAM-pressure; на 04 уже 3 GiB занято Argo/Longhorn/Higress | Сервер на 02/03; следить `kubectl top pod -n gpustack`; при вытеснении — `post-renderer` не спасает (Argo его не использует) → ручной патч StatefulSet/DS с фиксацией в спеке |
| **R-G7** | Первая загрузка без прогрева: раннер 20.5 ГБ + веса 14.6 ГБ при 4–6 МБ/с = часы; на сцене это тишина и `ImagePullBackOff` | G2 прогревает ноду заранее прямым pull (склада нет); на сцене качать нечего |
| **R-G8** | Воркер работает `privileged` + `hostNetwork` + `hostIPC`, слушает 10150/10151 на хосте; CPU-воркер на 01 не должен появиться на 02/03 (там ingress-VIP) | Метку `acceleratable=false` ставим только на 01; порты на 04 свободны (проверено в G4) |
| **R-G9** | Admin-ключа GPUStack нет (решение владельца) → деплой моделей и ключи — только UI; скриптовая приёмка ограничена | Все шаги G5/G7 — UI-процедурой; приёмка — фактом в UI + `nvidia-smi`/HTTP-проверка |
| **R-G10** | Helm 4.1.3: `pull`/`show`/`template` проверены, `install` с hook-Job'ами — нет | G3 на пустом ns; при провале hooks — `--no-hooks` и ручной Job, факт в спеку |
| **R-G11** | Встроенный PostgreSQL без внешних бэкапов; потеря PVC = потеря админа, ключей, истории | Снапшот Longhorn перед демо и перед каждым апгрейдом |
| **R-G12** | Плагины/гардрейлы (`ai-security-guard`, WAF) в этой спеке не настраиваются; маршруты моделей через шлюз без правил фильтрации | Отдельная спека guardrail (решение 2026-10-24: плагины Higress); до неё шлюз не фильтрует промпты |

## 9. Что забывают в таких спеках (и что решено здесь) / открытые вопросы

| Пункт | Решение |
|---|---|
| RuntimeClass и drop-in containerd | чарт их **не создаёт** — отдельные объекты, G1 |
| Метка `acceleratable` для CPU-воркера | ставим сами, иначе DS висит `Pending` (грабля demo-plan) |
| Сертификат в values | запрещён; свой Ingress + `Certificate` |
| PVC после `helm uninstall` | остаётся — удаление только осознанно |
| Порты воркера на хосте | 10150/10151 заняты воркером, второй воркер на ноду не сядет (anti-affinity) |
| «Кластер здоров» ≠ «шаг 1 готов» | два разных вердикта: `k8s_health.py` и G8 |
| Модели — каталог, а не файл | веса кладутся каталогом `<repo-slug>/` |

Открытые вопросы (с рекомендацией — чтобы исполнитель не решал заново):

1. **Способ деплоя:** helm напрямую (рекомендация, прецедент F2–F5) vs Argo-приложение с OCI-чартом
   (требует правки `AppProject.sourceRepos` и вложенного app-of-apps). *(Рекомендация: helm; adoption — отдельной задачей.)*
2. **PVC сервера:** 20Gi (рекомендация) vs дефолт 100Gi. *(20Gi: встроенная БД + метаданные.)*
3. **Размещение сервера:** пара 02/03 (рекомендация) vs k8s-01. *(02/03 — лёгкие сервисы по ADR-0003; 04 исключён — там GPU и Argo.)*
4. **Модельный набор:** 14B + bge-m3 (рекомендация) vs +8B. *(8B (+5.7 ГБ) — только если после прогрева на root-LV останется >10 ГБ.)*
5. **Транспорт образов:** только прямой pull с ноды (склада и локального зеркала нет — решение 2026-10-24).
   *(Прогрев: `ctr -n k8s.io images pull` нужных образов + разовая загрузка весов ДО `helm install`, иначе первый старт
   висит в `ImagePullBackOff` и красит health-gate. Поднять локальный реестр — отдельное решение, если
   канал площадки станет узким местом.)*
6. **SSO:** включать в этой спеке (G7, блокируется K1–K7) или отдельной спекой после Keycloak. *(Оставить G7 здесь как фазу, не дублировать клиента в двух спеках.)*

## 10. Связанные документы и история версий

- `references/demo-plan.md` — сценарий (шаг 1), RAM-бюджет, чек-лист «готово ли к демо», репетиция с таймером.
- `references/gpu-scheduling-options.md` — почему GPUStack, а не голый device plugin/KAI.
- `adr/adr-0001-higress-as-sole-ingress.md` — единственный ingress-контроллер (отсюда `higress-core.enabled=false`).
- `adr/adr-0003-three-control-planes.md` — роли узлов (01 — компьют, 02/03 — ingress, 04 — GPU).
- `architecture/ARCHITECTURE.md` §5, §7 — размещение и текущее состояние.
- `architecture/endpoints.md` — `api.demo-ai-lab.ru`, клиент `gps`.
- `architecture/keycloak-spec.md` — K1–K7, от которых зависит G7.
- `references/service-spec-authoring.md` — шаблон этой спеки.

**История версий**

| Версия | Дата | Что |
|---|---|---|
| v1.3 | 2026-10-24 | Сверка с живым стендом после снятия реестра: G2 переведена с `crictl` (не установлен на нодах) на `ctr -n k8s.io images pull`; веса качаются на консоли (`hf download`) и кладутся по LAN — `huggingface_hub` на ноде нет; объёмы пересчитаны в GB (≈39 ГБ для 14B + bge-m3, запас ≈17 ГБ). В `ARCHITECTURE.md` §7 добавлен факт снятия mirror-конфигов containerd |
| v1.2 | 2026-10-24 | Локальный реестр образов убран из всех архитектурных схем и доков (`demo-ai-lab-architecture.html`, `ARCHITECTURE.md` §4, `AGENTS.md`, `status-audit.md`, `external-access-spec.md`): образы — прямой pull из облачных реестров (Docker Hub / ghcr / quay). O5 закрыт — вариант `global.hub` на локальный реестр снят |
| v1.1 | 2026-10-24 | Склад предзагрузки снят по решению владельца: `preload-registry/` и `references/preload-registry.md` удалены из репозитория, `env_health.py` больше не проверяет реестр. G2 переписана на прогрев ноды прямым pull (`crictl pull` образов + веса каталогами в `/var/lib/gpustack/models/`); R-G7 пересчитан (раннер 20.5 ГБ + веса 9.3 GiB) |
| v1.0 | 2026-10-24 | Первая версия: живой замер (ноды, диск, helm 4.1.3 + рендер чарта 2.2.3, журнал containerd), решения §1, фазы G0–G8, риски R-G1…R-G12. Найдено: **handler `nvidia` в containerd не применён** — вынесено в блокер G1. Установка не выполнялась |
