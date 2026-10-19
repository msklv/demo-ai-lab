# Спецификация установки Kubernetes на стенд demo-ai-lab

> **Версия 2.1** (ревизия 2026-10-19). Цель — кластер «готов под демо-шаг 1»:
> kubeadm → Cilium → Longhorn → NFD → cert-manager → Argo CD + GitOps →
> **ingress-VIP `.230` + Higress (F7/F8, добавлены ревизией 2026-10-19)**.
> GPUStack остаётся вне спецы (шаг 1 демо подключается к готовому Higress, ADR-0001 рев. 3).
> Решения: ADR-0001 (Higress), ADR-0002 (дисковая модель), ADR-0003 (три control-plane).
> Секреты (логины нод, sudo-пароль, public IP, MAC) — вне документа (`inventory.local.md`).
>
> **F1-gate снят 2026-10-17:** ADR-0003 принят, controlPlaneEndpoint = **вариант A —
> kube-vip VIP `192.168.10.240`** (§4). VIP защищены от выдачи DHCP: `.240` и ingress-`.230` выведены
> из пула MikroTik (ranges `.10–.229,.231–.239,.241–.254`, 2026-10-17/18). **F1+F2 выполнены 2026-10-18** (см. §7).
>
> **Состояние 2026-10-19 (день): F0–F9 выполнены полностью** (F3–F8 — см. §7; F9: health-gate,
> оба стресс-сценария, GitOps Synced/Healthy + selfHeal, внешний сквозной 200 через Cloudflare —
> external-access E4/E5 приняты там же; операционный риск R1 — шторм uplink, окна 530).
> Инсталляция кластера спекой закрывается; за её пределами — GPUStack, контент демо, E6 Access.

## 1. Форма кластера и границы

- **3 control-plane: k8s-01, k8s-02, k8s-03** — stacked etcd, кворум 3: потеря одного
  мастера не останавливает ни API, ни нагрузку (ADR-0003).
- **k8s-04 — worker общего назначения**: LLM-инференс (nodeSelector-закрепление) **и**
  сервисы; без taint'а (ADR-0003, правка владельца).
- Размещение сервисов nodeSelector'ом (см. §6); изоляция taint'ом — только снятая
  control-plane-изоляция мастеров.
- Входит (ревизия 2026-10-19): **ingress-VIP `.230` (kube-vip LB-инстанс, F7) и Higress-gateway
  (standalone-поды на 02/03, F8)** — прежний «отдельный ingress-план» отменён владельцем,
  ingress теперь часть bootstrap'а. cert-manager входит (F5) — PKI-провижнер под TLS ingress'а.
- Не входит: **GPUStack** (и его routes/модели), сервисы демо-шагов 2/3, BeeLlama — ставятся
  поверх готового Higress шагом 1 демо. GPUStack подключается к уже стоящему Higress
  (`higress-core.enabled=false`, `gateway.ingressClassname=higress`) — ADR-0001 рев. 3.

## 2. Состояние узлов (живой аудит 2026-10-17)

| Узел | LAN IP | Роль | CPU/RAM | Разметка (физика 476.9G) | Готовность |
|---|---|---|---|---|---|
| k8s-01 | .250 | CP #1 (`kubeadm init` здесь) + компьют-heavy | R7 7840HS 8C/16T · 32Gi | root-LV 100G, VG ~374G (не резать) | F0 выполнен 2026-10-17 |
| k8s-02 | .253 | CP #2 + **ingress-пара с 03 (VIP .230)** + GitOps | R5 7640HS 6C/12T · 14Gi | root-LV 100G, VG ~374G | переустановлен 2026-10-17; F0 выполнен (prep прогнан) |
| k8s-03 | .254 | CP #3 + **ingress-пара с 02 (VIP .230)** + лёгкие сервисы | R5 7640HS 6C/12T · 14Gi | root-LV 100G, VG ~374G | переустановлен 2026-10-17; F0 выполнен (prep прогнан) |
| k8s-04 | .252 | worker: LLM + data-heavy + Longhorn 250G | R7 H255 8C/16T · 28Gi · RTX 5060 Ti 16G | root-LV 100G, VG ~374G | containerd 2.2.1+CRI, swap off — в силе |

Готово:
- DHCP-static-резервации всех четырёх bound (.250/.253/.254/.252); после переустановки
  02/03 в static-записях обновлён client-id (REST, явное разрешение владельца, 2026-10-17).
  Правило при переустановке узла — §9 и `mikrotik-setup.md` §3.5.
- NAT MikroTik WAN tcp 80/443 → .253 — исторический (2026-10-12): внешний путь теперь Cloudflare Tunnel (ADR-0004), точка ingress — VIP `.230` (пара 02/03); снятие/перенос правила — в ingress-плане.
- Разметка 02/03 целевая (переустановка владельца): EFI+boot+root-LV 100G, ~374G в VG —
  все четыре узла однотипны, модель ADR-0002.
- k8s-04: containerd 2.2.1 с CRI (`systemd_cgroup=true`, pause 3.10), swap off (fstab).
- **F0 выполнен 2026-10-17**: pb-k8s-prep на 01/02/03 (в playbook исправлен баг: пакет
  containerd 2.x из noble-updates не создаёт `/etc/containerd` — добавлена задача создания
  каталога); приёмка: containerd **2.2.1** + SystemdCgroup на всех четырёх, swap пустой ×4,
  `/etc/hosts` резолвит все четыре с каждого (на 04 дописана строка k8s-01).
- **Longhorn-LV 250G нарезаны, отформатированы (ext4), смонтированы в `/var/lib/longhorn`,
  в fstab** на 02/03/04; k8s-01 без LV (вне пула, план). open-iscsi на всех четырёх:
  `iscsid.socket` enabled (юнит сокет-активируемый — `is-active` показывает inactive в
  простое, это норма), `iscsiadm` работает.

Не готово:
- kubeadm/kubelet нигде; kube-proxy не ставим (Cilium full KPR); kubeconfig на консоли.
- backend-netplan 10.20.20.0/26 на 02/03 восстановлен 2026-10-18 (`ansible/pb-net-p2p.yaml`,
  взаимный ping); в day-0 не участвует (overlay по LAN).
- kube-vip — только при варианте A endpoint (§4).

> ⚠️ `127.0.1.1 <hostname>` от установщика: первый матч резолва — loopback; kubelet
> берёт node-IP по маршруту, но сервисы, резолвящие соседей по `/etc/hosts`, получают
> не тот адрес. pb-k8s-prep строку удаляет.

## 3. Версии и пины (обновлять при установке)

| Компонент | Версия | Источник | Комментарий |
|---|---|---|---|
| kubeadm / kubelet / kubectl | **1.35.9** | pkgs.k8s.io (core:v1.35) | GPUStack требует ≥1.30; связка containerd 2.2.1 + k8s ≥1.33 обкатана на home-lab |
| containerd | **2.2.1** (уже на 04) | apt noble-updates (candidate = 2.2.1-0ubuntu1~24.04.3, замер 2026-10-17) | не обновлять до кластера; registry.mirrors не задавать (ломает CRI) |
| kube-vip | **v0.9.2** @ `sha256:c6d4f3a3…` (сверен ghcr API 2026-10-18) | ghcr kube-vip | вариант A: статический под, ARP + leaderElection на `eno1` — кладёт `ansible/pb-k8s-vip.yaml` (группа masters) |
| Cilium | **1.20.3** | helm cilium/cilium | kubeProxyReplacement=true |
| Longhorn | **1.13.0** | helm longhorn/longhorn | chart = релиз |
| cert-manager | **v1.21.2** (версия чарта с `v`!) | helm jetstack/cert-manager | installCRDs=true |
| NFD | **0.20.0** | helm kubernetes-sigs/nfd | GPU-лейблы для GPUStack (`pci-10de.present`) |
| Argo CD | **3.5.5**, chart argo-cd **10.10.5** (пинить точно, не `10.x`) | helm argoproj/argo-cd | GitOps внутри кластера |
| Higress | **higress-core 2.1.9** (пин = версии сабчарта GPUStack 2.2.3) | helm higress.io | standalone-поды на 02/03 (F8), ingressClass `higress`; GPUStack потом подключается через `gateway.ingressClassname` |
| Helm (клиент на консоли) | ≥3.18.4 | Mac | требование чарта GPUStack |

Все чарты/образы предзагрузить до установки (egress площадки 4–6 МБ/с, Docker Hub
rate-limit = минуты тишины на сцене).

## 4. Сеть кластера

| Параметр | Значение |
|---|---|
| controlPlaneEndpoint | **Принят вариант A (ADR-0003, 2026-10-17): kube-vip VIP `192.168.10.240:6443`** — потеря .253 переживает API. VIP от DHCP-выдачи защищён: `.240` исключён из пула MikroTik (2026-10-17). Вариант B (`.253`) отклонён. **VIP ровно один — только API**: ingress получает собственный VIP (решение 2026-10-18, §10) |
| podSubnet / serviceSubnet | `10.42.0.0/16` / `10.99.0.0/16` (не пересекаются с LAN/p2p/uplink — сверено) |
| certSANs apiserver | `k8s-01..03` + `.250/.253/.254` + `192.168.10.240` + `127.0.0.1` (оба IP мастеров в списке — страховка миграции B→A, вариант B отклонён) |
| Cilium `k8sServiceHost:Port` | endpoint:6443 — обязательно при full KPR без kube-proxy (иначе init-контейнер Cilium падает до CNI — грабля home-lab) |
| kubelet node-IP | авто по маршруту → LAN (нет 127.0.1.1 после prep) |
| kubectl консоли | `~/.kube/demo-ai-lab.conf` = admin.conf, server → endpoint:6443 |

kube-vip (вариант A): статический под `--arp --controlplane --leaderElection` на
**каждом** мастере, LAN-интерфейс `eno1` (у всех четырёх, проверено 2026-10-18);
заводится **до** init и до join. VIP от DHCP-выдачи защищены (2026-10-17/18): `.240` и `.230`
выведены из пула MikroTik (`ranges=.10–.229,.231–.239,.241–.254`); lease-резерв без MAC RouterOS
не принимает, REST-добавление lease заблокировано — резерв делается только пулом.

p2p 10.20.20.0/26 (02↔03) в day-0 не участвует: восток-запад идёт по LAN; с переездом
данных на k8s-04 исходный смысл линка («данные ↔ ingress») утрачен. Netplan восстановлен
2026-10-18 вне рамок спецы (`ansible/pb-net-p2p.yaml`) — линк есть, но day-0 его не использует.

## 5. Дисковая модель (ADR-0002 + ADR-0003)

Все узлы однотипны: физика 476.9G, root-LV 100G, ~374G свободно в VG.
Longhorn-пул — **три узла, LV 250G каждый**: 750G сырых, ≈375G полезных при replica=2.
**k8s-01 в пул не входит** — самый изношенный диск стенда (ZSPEED, 11%, резерв TBW
≈100 TB, `hardware-inventory.md`): LV ему не режется, дефолтный диск Longhorn запрещается
 (§6). Остатки VG — резерв (02/03/04 по ~124G, 01 — 374G).

```bash
# на k8s-02, k8s-03, k8s-04 (sudo) — НЕ на k8s-01
sudo vgs                                          # контроль: ~374G свободно
sudo lvcreate -L 250G -n longhorn ubuntu-vg
sudo mkfs.ext4 -L longhorn /dev/ubuntu-vg/longhorn
sudo mkdir -p /var/lib/longhorn
echo "UUID=$(sudo blkid -s UUID -o value /dev/ubuntu-vg/longhorn) /var/lib/longhorn ext4 defaults 0 2" | sudo tee -a /etc/fstab
sudo mount -a && df -h /var/lib/longhorn          # приёмка: смонтирован, 250G
# open-iscsi — на ВСЕХ четырёх (instance-manager нужен и k8s-01)
sudo apt-get update && sudo apt-get install -y open-iscsi
```

Тайминг: LV/open-iscsi — блокер **до F3**, не до init (F1/F2 идут без них).
Модели LLM — hostPath на k8s-04, в Longhorn не кладутся.

## 6. Размещение и taint/affinity-политика

| Узел | Правило | Реализация |
|---|---|---|
| k8s-01/02/03 | taint control-plane **снять** (иначе нагружать негде: 04 занят LLM-закреплением, сервисам нужно место) | после F1: `kubectl taint nodes k8s-01 k8s-02 k8s-03 node-role.kubernetes.io/control-plane-` |
| k8s-04 | **без taint'а**: LLM и сервисы сосуществуют (ADR-0003) | инференс (BeeLlama/GPUStack): nodeSelector k8s-04 + priorityClass выше сервисного (preemption при нехватке RAM); сервисы — строго requests/limits |
| k8s-01 × Longhorn | **вне пула реплик**: безLV-узел не должен получить дефолтный диск на root-ZSPEED | до F3: `kubectl annotate node k8s-01 node.longhorn.io/create-default-disk="false"`; контроль в UI Longhorn (нет диска / Allow Scheduling off) |

Планируемое размещение (детали — `ARCHITECTURE.md` §5): компьют-heavy (RAGFlow,
OCR·Docling, рантаймы, BI, Langfuse) → k8s-01; ingress/GitOps/каталоги → k8s-02
(Higress-gateway — парой на 02/03, ingress-VIP `.230`); лёгкие stateless → k8s-03; LLM + data-heavy (PostgreSQL, ClickHouse, Qdrant, MinIO,
Keycloak) → k8s-04.

## 7. Порядок установки (фазы)

### F0 — Подготовка нод — **выполнено 2026-10-17** ✅
1. pb-k8s-prep на 01/02/03 (04 — контроль) — прогнан; баг playbook (каталог
   `/etc/containerd` в пакете 2.x) исправлен на месте.
2. §5: LV 250G на 02/03/04 (ext4, fstab, `df` подтверждает 246G) + open-iscsi на всех.
3. Приёмка пройдена: `swapon --show` пусто (×4); containerd 2.2.1 + systemd_cgroup (×4);
   `getent hosts k8s-0{1..4}` с каждого узла; `iscsiadm -m session` рабочий (×4).

### F1 — kubeadm: init на k8s-01 → join CP на 02/03 → join worker 04 — ✅ выполнено 2026-10-18
> Факт: init прошёл (4 узла Registered, etcd ×3 Running). Порядок дня оказался
> важнее плана: VIP статически стартует только после init (kubelet без config.yaml
> поды не поднимает), поэтому на init VIP включали вручную (`ip addr add .240/32 dev eno1`
> на k8s-01), после "New leader" в логах kube-vip (лидер стал k8s-03) костыль снят.
> Init прогнан без `--skip-phases=addon/kube-proxy` — лишний DS/CM удалены вручную,
> nft-цепочки `KUBE-*` откачаны на всех четырёх (`iptables-save | grep -v KUBE |
> iptables-restore`); при переустановке держать `--skip-phases` как ниже.
> Грабли kube-vip v0.9.x — в заголовке `ansible/pb-k8s-vip.yaml`.
```bash
# [вариант A] ansible/pb-k8s-vip.yaml — статический под kube-vip (ARP, eno1, VIP .240)
# на мастерах, до init; приёмка (только post-init): "New leader" в логах, VIP ровно
# на одном узле.
# kubeadm/kubelet/kubectl 1.35.9 с pkgs.k8s.io (core:v1.35) — ставит
# ansible/pb-k8s-pkgs.yaml (пин 1.35.9-1.1, apt-mark hold kube*/containerd).

cat > kubeadm-config.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
nodeRegistration:
  criSocket: unix:///var/run/containerd/containerd.sock
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: v1.35.9
controlPlaneEndpoint: "192.168.10.240:6443"   # вариант B: "192.168.10.253:6443"
apiServer:
  certSANs: ["k8s-01", "k8s-02", "k8s-03", "192.168.10.240",
             "192.168.10.250", "192.168.10.253", "192.168.10.254", "127.0.0.1"]
networking:
  podSubnet: "10.42.0.0/16"
  serviceSubnet: "10.99.0.0/16"
EOF
sudo kubeadm init --config kubeadm-config.yaml --skip-phases=addon/kube-proxy   # k8s-01

CERT_KEY="$(sudo kubeadm init phase upload-certs --upload-certs | tail -1)"
JOIN="$(sudo kubeadm token create --print-join-command)"
#   на k8s-02 и k8s-03:  $JOIN --control-plane --certificate-key "$CERT_KEY"
#   на k8s-04:           $JOIN
sudo kubectl taint nodes k8s-01 k8s-02 k8s-03 node-role.kubernetes.io/control-plane-  # §6
```
- kubeconfig консоли: `sudo cat /etc/kubernetes/admin.conf` → `~/.kube/demo-ai-lab.conf`
  (server → endpoint:6443).
- Приёмка: 4 узла Registered (3 master + 1 worker); etcd-подов ×3; kube-proxy нет.
- **DNS-отказоустойчивость: обе реплики coredns на РАЗНЫХ узлах**
  (`kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide`). У kubeadm-Deployment
  анти-аффинность только `preferred`, а CoreDNS заводится на init, когда остальных узлов
  ещё нет, — обе реплики могут сесть на один узел (факт 2026-10-18: обе на k8s-03).
  Лечение — `kubectl -n kube-system rollout restart deploy/coredns` (2026-10-18 разъехались
  на 01+04), критерий проверять после F2 и после каждого recovery-сценария.

### F2 — Cilium (CNI, full KPR) — ✅ выполнено 2026-10-18
```bash
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium -n kube-system --version 1.20.3 \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=192.168.10.240 --set k8sServicePort=6443   # вариант B: .253
```
Приёмка: 4 Ready; `cilium status --brief` → OK (проверено). Дополнительно по §6:
taints control-plane сняты на 01/02/03, longhorn-аннотация k8s-01 проставлена.

### F3 — Longhorn — ✅ выполнено 2026-10-19
```bash
kubectl annotate node k8s-01 node.longhorn.io/create-default-disk="false"   # ДО install (§6)
helm repo add longhorn https://charts.longhorn.io
helm install longhorn longhorn/longhorn -n longhorn-system --create-namespace --version 1.13.0 \
  --set persistence.defaultClass=true \
  --set persistence.defaultClassReplicaCount=2 \
  --set 'defaultSettings.defaultReplicaCount=2' \
  --set 'defaultSettings.replicaZoneSoftAntiAffinity=true'
```
Приёмка: в `nodes.longhorn.io` 4 узла, диск ≈250G **только на 02/03/04**; SC longhorn —
default; тестовый PVC replica=2 → Bound, реплики не на k8s-01 → удалить.
> **Грабли (2026-10-19):**
> 1. `defaultSettings.defaultReplicaCount` плавает только setting Longhorn; реальный
>   .numberOfReplicas берётся из **параметра StorageClass** (`persistence.defaultClassReplicaCount`,
>    дефолт чарта = 3). Без него первый PVC приехал replica=3. SC неизменяем → `kubectl delete sc longhorn`
>    + `helm upgrade --set persistence.defaultClassReplicaCount=2` (уже сделано; проверено PVC r=2).
> 2. Аннотация `create-default-disk="false"` **не помешала** агенту создать дефолтный диск на k8s-01
>    (директория `/var/lib/longhorn` уже была). Удаление диска CR'ом заблокировано Longhorn
>    («disable the disk first»). Исполненная форма изоляции k8s-01: **`allowScheduling: false` на ноде**
>    (`kubectl -n longhorn-system patch nodes.longhorn.io k8s-01 --type merge -p '{"spec":{"allowScheduling":false}}'`)
>    — это ветка приёмки «Allow Scheduling off». Контроль после ребута longhorn-manager: SCHED=false
>    в `nodes.longhorn.io` (агент может пересоздать диск — но узел остаётся off).
> 3. Под с томом на fs-squash образе (nginx-unprivileged, uid 101) требует `fsGroup: 101`,
>    иначе запись в /data молча не делается (приёмка «пишем-читаем» это ловит).

### F4 — NFD — ✅ выполнено 2026-10-19
```bash
helm repo add nfd https://kubernetes-sigs.github.io/node-feature-discovery/charts
helm install nfd node-feature-discovery/node-feature-discovery \
  -n node-feature-discovery --create-namespace --version 0.20.0
```
Приёмка: на k8s-04 метка `feature.node.kubernetes.io/pci-10de.present=true` (проверено).
> **Грабли (2026-10-19):** в NFD ≥0.18 файловые custom-правила **удалены** — worker.conf
> `featureRules` молча игнорируется (в 0.20 конфиг парсится, правил не видно). Метка
> GPU задаётся CR **`NodeFeatureRule`** (`matchFeatures: pci.device vendor In [10de]` →
> `labels: feature.node.kubernetes.io/pci-10de.present: "true"`); манифест —
> `gitops/infra-apps/infra/nfd-rule-nvidia.yaml`. Дефолтные встроенные лейблы PCI —
> формата `pci-<class>_<vendor>` (`pci-0300_10de`), GPUStack-совместимого `pci-10de` они не дают.

### F5 — cert-manager + ClusterIssuer — ✅ установлено 2026-10-19
```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.21.2 --set installCRDs=true
```
Приёмка: 3/3 Running (проверено); CRD на месте.
> **Грабля (2026-10-19):** версия чарта публикуется с **префиксом `v`** —
> `--version 1.21.2` не найдётся, нужен `--version v1.21.2`.
ClusterIssuer `letsencrypt-wildcard` (DNS-01, solver cloudflare — ADR-0004 ревизия)
создаётся сейчас, solvers/секрет — плейсхолдер (API-токен `DNS:Edit` зоны), заполняется
ingress-планом, не коммитится. Манифест issuer лежит в
`gitops/infra-apps/infra/clusterissuer-letsencrypt-wildcard.yaml` (секрет в git не входит).
**Не Ready** до появления Secret `cert-manager/cloudflare-api-token` — внешний шаг (E4 ingress-плана).

### F6 — Argo CD + GitOps — ✅ выполнено 2026-10-19 (push + root-app + selfHeal-drift)
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace --version 10.10.5 \
  --set redis.image.registry=docker.io --set redis.image.repository=library/redis
  # redis по дефолту чарта тянется с ecr-public.aws.com — недоступен с площадки
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d    # до ingress — UI через port-forward
```
Приёмка релиза: STATUS deployed, секрет админа выдан (проверено).
`gitops/` в этом репо подготовлен: `gitops/root/root-app.yaml` (app-of-apps) +
`gitops/root/applicationsets.yaml` (AppProjects `infra`/`apps` + два
ApplicationSet-наблюдателя `gitops/infra-apps/*` и `gitops/apps/*`, destination
in-cluster, automated prune+selfHeal); первые объекты инфраструктуры —
ClusterIssuer (F5) и NodeFeatureRule (F4). Паттерн home-lab.
> **Принято 2026-10-19 (ночь):** git push по команде владельца → `kubectl apply -f
> gitops/root/root-app.yaml` → root-app **Synced/Healthy**; ApplicationSet породили
> приложение `infra` (ClusterIssuer + NodeFeatureRule adoption — Synced), `apps` пустое.
> selfHeal-drift пройден: live-annotation на NodeFeatureRule → само вернулась за ~3 мин
> (дефолтный reconcile-интервал). **Грабель:** chart 10.10.5 тащит redis с
> `ecr-public.aws.com` (недоступен с площадки) → ImagePullBackOff → appset-git-generator
> падал `no route to host :6379`; лечение: `helm upgrade --reuse-values --set
> redis.image.registry=docker.io --set redis.image.repository=library/redis`
> (chart нормализует docker.io в префиксе). ClusterIssuer остаётся Degraded — ждёт
> Secret `cert-manager/cloudflare-api-token` (E5), это ожидаемо.
> Существующие helm-релизы (F2–F5, F8) под Argo **не** переводились — это отдельный
> план adoption (иначе Argo удалит «чужие» объекты при prune).

### F7 — ingress-VIP `.230` (kube-vip LB-инстанс на 02/03) — ✅ выполнено 2026-10-19
Приёмка пройдена: `.230` ровно на одном из 02/03 (ip addr), ARP отвечает (ip neigh с соседа),
тестовый Service type=LoadBalancer получил EXTERNAL-IP `.230` через аннотацию; при уводе
инстанса с держателя VIP переехал на второй узел пары, трафик (`curl` каждые 0,3 с) не потерял
ни одного ответа. Локация инстансов — `kube-vip-lb` static pod на 02/03 (`/etc/kubernetes/manifests/kube-vip-lb.yaml`).
> **Заметки (2026-10-19):** `vip_leasename=plndr-svc` (реальный lease в кластере — `plndr-svcs-lock`,
> v0.9.2 добавляет суффикс; локи API и LB не конфликтуют); graceful-уход держателя даёт переезд
> быстрее лиза, жёсткое убийство пода (`delete pod`) держатель может вернуть до истечения лиза —
> для приёмки переезда надо выводить инстанс из игры надолго (mv манифеста / стоп ноды).
> Проверка держателя: `ip -4 addr show eno1 | grep 192.168.10.230` (у `arping` на нодах нет —
> ставить `iputils-arping` или брать `ip neigh`).
Второй инстанс kube-vip, **отличный от API-`.240`** (ADR-0001, решение «два VIP не
склеивать»): пул `.230`, узлы **только k8s-02/03** (не все мастера), режим LoadBalancer +
`externalTrafficPolicy: Local` (VIP отвечает там, где живой endpoint gateway). Статические
поды на 02/03, отдельный манифест/плейбук, **не** пересекается с `pb-k8s-vip.yaml` (`.240`).
```bash
# ansible/pb-k8s-vip-lb.yaml — группа ingress (k8s-02,k8s-03), шаблон kube-vip-lb.yaml.j2:
#   args: manager --services --leaderElection   ( следит за Services type=LoadBalancer, не за CP )
#   env:  vip_interface=eno1, address=192.168.10.230/32, vip_arp=true,
#         cp_enable=false, svc_enable=true, vip_leaderelection=true,
#         vip_leasename=plndr-svc ; image = тот же пин v0.9.2@sha256:c6d4f3a3…
# Грабли — те же, что у API-VIP (см. шапку pb-k8s-vip.yaml): абсолютный /kube-vip,
# hostPath admin.conf, cp_detect не нужен (svc-режим).
# .230 зарезервирован от DHCP (MikroTik pool, external-access-спека E3) — проверить до F7.
ansible-playbook -i hosts.cluster.yml pb-k8s-vip-lb.yaml   # группа ingress = 02/03
```
Приёмка:
- `.230` ровно на одном из 02/03, ARP отвечает (`arping -c1 -I eno1 192.168.10.230` с соседа);
- тестовый `Service type=LoadBalancer` получает `EXTERNAL-IP .230` (аннотация
  `kube-vip.io/loadbalancerIPs: 192.168.10.230` для статичной галочки), endpoint-под на 03 →
  трафик через `.230` проходит; убить под на активном узле пары → VIP переезжает на другой ≤2 c.

### F8 — Higress-gateway на 02/03 (ingress-контроллер) — ✅ выполнено 2026-10-19
Приёмка: ingressClass `higress` есть; `higress-gateway` 2/2 Running, поды на 02 **и** 03
(antiaffinity сработала); Service `EXTERNAL-IP 192.168.10.230`; смоук-тест — тестовый
Ingress `echo.demo-ai-lab.ru` (ns `demo-test`, образ `ghcr.io/nginxinc/nginx-unprivileged:1.27-alpine`)
отвечает **200 через `.230`** (`server: istio-envoy`); связка higress-core 2.1.9 × k8s 1.35.9
работоспособна. Тестовые echo/ns `demo-test` — временные, удалить после E4.
> **Грабли (2026-10-19):**
> 1. `helm install` без `--create-namespace` (при `-n higress-system`) падает
>    `namespaces "higress-system" not found`.
> 2. **Cilium full-KPR не отдаёт nodePort до рестарта агента**: после установки Higress баль
>    `NodePort 31656` и ClusterIP gateway отсутствовали в `cilium bpf lb list` на всех нодах
>    (watch сервисов залип с момента установки CNI в F2 — все сервисы, созданные позже,
>    в maps не попадали). Лечение: `kubectl -n kube-system rollout restart ds/cilium`
>    (бесшовно, eBPF-maps переписываются) — после этого `192.168.10.253:31656` появился,
>    трафик через `.230` пошёл. **Проверять `cilium bpf lb list | grep <nodePort>` после
>    установки КАЖДОГО нового LoadBalancer-сервиса; симптом — connection refused на VIP
>    при живом gateway.** Вероятная причина — обрыв watch на шторме API-VIP дня F1;
>    за наблюдением (если повторится — чинить не рестартом).
> 3. Реестры: с площадки `public.ecr.aws` и `registry.k8s.io/e2e-test-images` тянутся
>    минутами/таймаутятся; `ghcr.io` — секунды. Тестовые образы брать с ghcr, предтягивать
>    `ctr -n k8s.io images pull` на узлы.
> 4. `externalTrafficPolicy: Local` + VIP на узле **без** локального endpoint → connection
>    refused (так и должно быть; VIP держится там, где живой gateway — проверка приёмки).
Standalone-установка (не через GPUStack-chart) — ADR-0001 рев. 3. ingressClass `higress`;
GPUStack на шаге 1 демо поставят позже с `higress-core.enabled=false` +
`gateway.ingressClassname=higress`, подключившись к этому же контроллеру.
```bash
kubectl label nodes k8s-02 k8s-03 demo-ai-lab/role=ingress
helm repo add higress.io https://higress.io/helm-charts
# higress-core = контроллер + gateway, без консоли/o11y (лёгкий стенд); пин = сабчарт GPUStack 2.2.3.
# Ключи values проверены по `helm show values higress-core 2.1.9` (2026-10-19): namespace
# gateway.* (НЕ higress-core.gateway.* — это префикс umbrella-чарта), service по умолчанию
# LoadBalancer, есть loadBalancerIP/annotations/externalTrafficPolicy/nodeSelector/affinity.
helm install higress higress.io/higress-core -n higress-system --create-namespace \
  --version 2.1.9 -f values-f8.yaml
```
`values-f8.yaml` (вендорится в `ansible/` рядом с релизом; ключи сверены с чартом):
```yaml
gateway:
  replicas: 2
  nodeSelector:
    demo-ai-lab/role: ingress
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels: { app: higress-gateway }
  service:
    type: LoadBalancer
    loadBalancerIP: 192.168.10.230        # = пул F7; статичная галочка
    externalTrafficPolicy: Local          # source-IP клиента, VIP где живой endpoint
    annotations:
      kube-vip.io/loadbalancerIPs: "192.168.10.230"
```
Приёмка:
- `kubectl get ingressclass higress` есть; gateway 2/2 Running, поды на 02 **и** 03 (antiaffinity);
- `higress-gateway` Service `EXTERNAL-IP .230`; тестовый Ingress (`echo.demo-ai-lab.ru`)
  отвечает через `.230`, внешний путь через Cloudflare → 200 (external-access E4);
- `externalTrafficPolicy: Local` — source-IP клиента сохраняется (не кластерный SNAT).
Риск: higress-core 2.1.9 на k8s 1.35.9 связками не тестировался (вендоры от 1.30) — смоук
обязателен; после GPUStack gateway скачивает Wasm-плагины с `gpustack/higress-plugins` →
рестарт gateway блокируется, пока тот Deployment недоступен (связка в §9).

### F9 — Приёмка (health-gate) — ✅ выполнено 2026-10-19
Пройдено 2026-10-19: 4 узла Ready ×1.35.9; `/readyz` ok; etcd 3/3; CoreDNS на разных узлах
(01+04); `cilium status --brief` OK; longhorn-узла 4 (k8s-01 SCHED=false), SC default r=2;
cert-manager 3/3; nfd Ready + метка GPU; higress pods/svc + ingressClass; под с PVC rw
живёт (write/read подтверждён), namespace create/delete не виснет.
Отказоустойчивость проверена двумя drilled:
1. **мастер--down (k8s-03, донор `.240`):** стоп kubelet + kill apiserver/etcd → VIP `.240`
   переехал на k8s-02 за ~6 c, API (`/readyz`) восстановлен (ok через VIP), ingress `.230`
   всё это время 200; старт kubelet → узел Ready, etcd 3/3, `/readyz` ok.
2. **ingress-пара:** увод LB-инстанса с держателя `.230` → VIP переехал на второй узел пары,
   трафик (`curl` 0,3 с) без потерь.
**Критерий приёмки (добавлен 2026-10-19, команда владельца): все затронутые поды — в
состоянии Running/Ready** во всех затронутых инсталляцией ns (kube-system, longhorn-system,
node-feature-discovery, cert-manager, argocd, higress-system); недопустимы ImagePullBackOff,
CrashLoopBackOff, зависшие Pending/Terminating. Пройден 2026-10-19 после зачистки старого
argocd-redis (ImagePullBackOff на ecr-public, см. F6) — призрачный Terminating-под снят
`--force`. Проверка — последней строкой health-gate.
**Внешний путь — закрыт 2026-10-19 (external-access E4/E5 приняты):** origin-`https` на
`.230` поднят (LE wildcard + Full strict + caPool, legacy-NAT снята),
`curl --resolve …:443:<CF-anycast> https://echo.demo-ai-lab.ru` → **200 через edge**
зафиксирован. Шторм uplink (сессии cloudflared рвутся волнами, 530-окна) — операционный
риск R1 спеки `external-access-spec.md`, не дефект кластера. **GitOps-пункт закрыт
2026-10-19:** push по команде владельца → root-app Synced/Healthy, selfHeal-drift
пройден (см. F6).
> Проверка public-края с консоли: системный DNS (ZTN) может отдавать старую площадку-парковку
> (`server: openresty`, без `cf-ray`) — только `dig @1.1.1.1` + `curl --resolve
> хост:443:<CF-anycast>`; при капризном egress — check-host.net. Это не инцидент стенда.
```bash
kubectl get nodes -o wide            # 4 Ready, 3 master, kubelet 1.35.9
kubectl get --raw /readyz            # ok
kubectl -n kube-system get pods -l component=etcd          # 3 Running
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide # реплики DNS на РАЗНЫХ узлах (§7 F1)
cilium status --summary
kubectl -n longhorn-system get nodes.longhorn.io ; kubectl get sc
kubectl -n cert-manager get pods ; kubectl -n node-feature-discovery get pods
kubectl -n argocd get applications   # Synced/Healthy
kubectl -n higress-system get pods,svc ; kubectl get ingressclass higress  # F8
kubectl get pods -A --no-headers | grep -vE ' ([0-9]+)/\1 +(Running|Completed)'  # пусто = все затронутые поды Running (критерий F9)
```
Плюс: под с PVC (rw) живёт, namespace create/delete не виснет. Отказоустойчивость:
выключить один мастер → API (endpoint) и нагрузка живы, etcd 2/3; выключить один узел
ingress-пары → `.230` переезжает, внешний путь через Cloudflare жив (external-access §4).

## 8. GitOps-памятка (паттерн home-lab)

- Argo CD внутри кластера (ns `argocd`), единственная точка входа — git.
- `git pull --ff-only` перед push; статус проверять по живому образу пода, не по «Synced».
- Секреты в git не кладём: приватное — в `inventory.local.md`, в манифестах — плейсхолдеры.

## 9. Риски и открытые вопросы

- ~~резерв `.240`~~ закрыто 2026-10-17, расширено 2026-10-18: пул MikroTik `.10–.229,.231–.239,.241–.254`
  (`.240` API и `.230` ingress не выдаются). В SAN уже оба адреса.
- **k8s-04 общий (LLM + data-heavy на 28Gi)**: без requests/limits у сервисов RAM
  кончается посреди демо; priorityClass инференса — страховка через preemption.
  Осознанная цена отказа от taint-изоляции (ADR-0003).
- **RAM 14Gi на мастерах 02/03**: control-плоскость + longhorn-manager ≈ 2,5–3 Gi →
  ~11 Gi на узел; data-heavy туда не селить.
- ~~containerd-пин~~ закрыт замером 2026-10-17: apt-candidate noble-updates = 2.2.1 —
  pb-k8s-prep даёт ту же версию, что на 04; рассинхрон возможен только на зеркале без
  noble-updates — приёмка `containerd --version` в F0 это ловит.
- **kube-vip — L2 ARP в общем LAN с Wi-Fi аудитории**: VIP зарезервировать в UI MikroTik.
- **DHCP-резервации и переустановки**: RouterOS матчит lease по client-id (DUID от
  machine-id) — после переустановки узла обновить client-id в его static-записи.
- Cilium full KPR: диагностика Service/`kubectl proxy` отличается; фиксы —
  `references/argo-cilium-notes.md` home-lab.
- **Cilium service-watch может залипнуть (зафиксировано 2026-10-19):** новые Service не попадают
  в `cilium bpf lb list` → VIP/nodePort refuses при живых подах. Диагностика:
  `cilium bpf lb list | grep <ClusterIP|nodePort>`; лечение: `rollout restart ds/cilium`.
  Проверять после каждого нового LB-сервиса.
- **Реестры с площадки:** ghcr.io и docker.io/longhornio тянутся нормально; `public.ecr.aws`
  и `registry.k8s.io/e2e-test-images` — таймауты. Тестовые/демо-образы пинать на ghcr
  (предтяжка `ctr -n k8s.io images pull`).
- **cloudflared QUIC-шторм (2026-10-19):** соединения к edge рвутся `datagram manager timeout`
  волнами; рестарт сервиса помогает ненадолго. На 02/03 поставлен systemd drop-in
  `/etc/systemd/system/cloudflared.service.d/protocol.conf` → `tunnel run --protocol http2`
  (TCP 443 вместо QUIC). Откат — удалить drop-in + daemon-reload + restart.
- GPUStack k8s-режим — experimental, вне спецы; версия зафиксирована: **v2.2.3**
  (чарт `gpustack-chart:2.2.3`, ADR-0001); стык: NFD-лейблы + nodeSelector
  воркера на 04 (tolerations больше не нужны) + `higress-core.enabled=false`,
  `gateway.ingressClassname=higress` (наш Higress из F8).
- **Higress 2.1.9 × k8s 1.35.9 — связка вендорами не тестировалась** (матрица совместимости от 1.30);
  смоук F8 обязателен до демо. После установки GPUStack higress-gateway скачивает Wasm-плагины
  с Deployment'а `gpustack/higress-plugins` — рестарт gateway блокируется, пока тот недоступен
  (новое скрытое ребро зависимости ingress от GPUStack-релиза, в сценарии E4-деградации учитывать).

## 10. Вне спецификации (отдельные планы)

- ~~Ingress-план как отдельный план~~ — **запрет отменён владельцем 2026-10-19**: механизм
  ingress (VIP `.230` + Higress-gateway) перенесён внутрь этой спеки как **F7/F8** (см. §7);
  способ установки решён — **Higress standalone** (ADR-0001 рев. 3), GPUStack позже
  подключается через `gateway.ingressClassname=higress`. Остаток «ingress-плана» вне спецы —
  только маршруты/модели GPUStack (шаг 1 демо) и guard-маршрут (ниже).
- **Два VIP, не объединять (решение 2026-10-18, в силе): `.240` — только
  API control-plane (F1, `pb-k8s-vip.yaml`); ingress — отдельный VIP `192.168.10.230`,
  обслуживают k8s-02+k8s-03** (LB-инстанс kube-vip, F7). Gateway закрепляется на 02/03
  (nodeSelector + antiaffinity, `externalTrafficPolicy: Local`) — VIP отвечает где живой endpoint (F8).
- **Внешний доступ, Cloudflare Tunnel, split-horizon DNS, TLS Full strict, MikroTik-часть —
  вынесены в `architecture/external-access-spec.md`** (v1, 2026-10-19; ADR-0004). Там же
  приёмка E1–E6 и сценарии деградации; состояние на 2026-10-18: зона активна, туннель
  healthy (2 коннектора 02/03), split-DNS работает; ждёт E4 (слушатель `.230`) и E5 (Full strict).
  Стык с этой спекой: cert-manager F5 — PKI-провижнер для E5; VIP-пара `.230` — см. выше.
- **guard-маршрут (guardrail — план 2026-10-18):** отдельный AI-маршрут Higress с Wasm-плагином
  `ai-security-guard`; бэкенд модерации — модель **Prompt Guard 2** (86M GGUF, **CPU-worker**
  GPUStack на k8s-01 — VRAM k8s-04 не занимает) через OpenAI-совместимый API. Защищаемые
  сервисы/агенты используют `base_url` guard-маршрута; прямые маршруты к GPUStack не guard'ятся
  (шаги 1–2 демо без лишней латентности). Рубильник — снятие аннотации Ingress. **Верифицировать
  при ingress-плане:** поддержка плагином кастомного OpenAI-бэкенда модерации (`openaiCustomUrl`);
  фолбэк — проверка хуками на стороне Лайт-ЛЛМ прокси. `ai-data-masking` не задействовать:
  маскирование PII — роль Лайт-ЛЛМ прокси (эгресс), не гейтвея.
- **Политика GPU — решено 2026-10-18:** в k8s-инсталляции инференс ТОЛЬКО GPUStack
  (llama-box, CUDA-worker на k8s-04); **BeeLlama в кластере не исполняется** — остаётся
  хостовым эталонным прогоном вне k8s. Перед демо проверять, что хостовый инференс не
  держит GPU (`stop_beellama_5060.sh` от standalone-ранбука).
- Метрики/логи/трейсы (Langfuse и пр.) — day-2, по RAM-бюджету.
- ~~Восстановление backend-netplan 10.20.20.0/26 на 02/03~~ — сделано 2026-10-18
  (`ansible/pb-net-p2p.yaml`, приёмочный ping).

## 11. Связанные документы и история

- `architecture/ARCHITECTURE.md` — целевая архитектура C2, размещение сервисов (§5).
- `adr/adr-0001-higress-as-sole-ingress.md` · `adr/adr-0002-node-storage-model.md` ·
  `adr/adr-0003-three-control-planes.md` (Accepted 2026-10-17).
- `network-map-detail.md` — живая карта сети; `architecture/hardware-inventory.md` —
  железо/SMART-журнал.
- Эталонный runbook: `~/git/home-lab/home-k8s/SPEC.md` + `references/bootstrap-pitfalls.md`.

История версии:
- **v2.3** (2026-10-19, день): **F9 закрыт — спека выполнена целиком (F0–F9)**. GitOps:
  push по команде владельца → root-app Synced/Healthy (грабельный redis
  ecr-public → docker.io/library/redis, F6), selfHeal-drift пройден. Внешний путь: принят
  external-access-спекой v1.3 (LE wildcard, Full strict, caPool, legacy-NAT off; сквозной
  200 через Cloudflare edge зафиксирован; 530-окна = R1 uplink). Критерий владельца
  «все затронутые поды Running» в health-gate (F9/E4). Вне спеки остались: GPUStack,
  контент демо, E6 Access.
- **v2.2** (2026-10-19, ночь): **F3–F8 выполнены** (Longhorn 1.13.0 SC default r=2 + изоляция
  k8s-01 нодовым `allowScheduling:false`; NFD + метка GPU через `NodeFeatureRule`;
  cert-manager v1.21.2 + ClusterIssuer-плейсхолдер; Argo CD 10.10.5 + каталог `gitops/`
  (app-of-apps + два ApplicationSet, живьём не применялся — ждёт git push владельца);
  kube-vip LB `.230` на 02/03 (`pb-k8s-vip-lb.yaml`, переезд VIP без потери трафика);
  Higress 2.1.9 standalone + `values-f8.yaml`, смоук-200 через `.230`). **F9 частично**:
  health-gate зелёный, стресс-дрill мастера и ingress-пары пройдены; не принято: GitOps
  Synced (git push) и внешний сквозной 200 (E4/E5, Cloudflare-токен). Грабли записаны
  в §7 (SC-replicas, NFD CR, cilium service-watch, Longhorn disk k8s-01, `fsGroup`), §9.
- **v1** (2026-10-16): single CP на k8s-02, LV «без переустановки» (204/204/250).
- **v2.1** (2026-10-19): ingress вошёл в спеку по решению владельца — **F7** (kube-vip LB
  `.230` на 02/03) + **F8** (Higress standalone, higress-core 2.1.9), приёмка перенумерована
  F7→F9; конфликт ADR-0001 закрыт рев. 3 (standalone + `higress-core.enabled=false` у GPUStack,
  путь официально документирован GPUStack); пин Higress в §3, риски связки в §9.
- **v2** (2026-10-17): три CP (ADR-0003); k8s-04 без taint'а, LLM+data-heavy;
  переустановка 02/03 выполнена (однотипная разметка 100G root), пул 250×3; роли
  сервисов по ADR-0003; DHCP-резервации восстановлены (DUID-грабля описана в §2/§9);
  Argo chart запинен 10.10.5; endpoint принят (вариант A); **F0 выполнен** (prep ×3, LV ×3, iscsi ×4; playbook-фикс `/etc/containerd`).
</content>
</invoke>