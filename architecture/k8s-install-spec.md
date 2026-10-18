# Спецификация установки Kubernetes на стенд demo-ai-lab

> **Версия 2** (2026-10-17), статус: черновик. Цель — кластер «готов под демо-шаг 1»:
> kubeadm → Cilium → Longhorn → NFD → cert-manager → Argo CD + GitOps.
> Higress и GPUStack вне этой спецы (отдельный ingress-план, шаг 1 демо).
> Решения: ADR-0001 (Higress), ADR-0002 (дисковая модель), ADR-0003 (три control-plane).
> Секреты (логины нод, sudo-пароль, public IP, MAC) — вне документа (`inventory.local.md`).
>
> **F1-gate снят 2026-10-17:** ADR-0003 принят, controlPlaneEndpoint = **вариант A —
> kube-vip VIP `192.168.10.240`** (§4). VIP защищены от выдачи DHCP: `.240` и ingress-`.230` выведены
> из пула MikroTik (ranges `.10–.229,.231–.239,.241–.254`, 2026-10-17/18). F1 отложен по решению владельца.

## 1. Форма кластера и границы

- **3 control-plane: k8s-01, k8s-02, k8s-03** — stacked etcd, кворум 3: потеря одного
  мастера не останавливает ни API, ни нагрузку (ADR-0003).
- **k8s-04 — worker общего назначения**: LLM-инференс (nodeSelector-закрепление) **и**
  сервисы; без taint'а (ADR-0003, правка владельца).
- Размещение сервисов nodeSelector'ом (см. §6); изоляция taint'ом — только снятая
  control-plane-изоляция мастеров.
- Не входит: Higress, GPUStack, модели, сервисы демо-шагов 2/3, BeeLlama (ставятся
  после кластера). cert-manager входит (F5) — PKI-провижнер готов к ingress-плану.

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
- backend-netplan 10.20.20.0/26 на 02/03 стёрт переустановкой (`enp2s0` down) — day-0 не
  нужен (overlay по LAN), восстановление отложено (§10).
- kube-vip — только при варианте A endpoint (§4).

> ⚠️ `127.0.1.1 <hostname>` от установщика: первый матч резолва — loopback; kubelet
> берёт node-IP по маршруту, но сервисы, резолвящие соседей по `/etc/hosts`, получают
> не тот адрес. pb-k8s-prep строку удаляет.

## 3. Версии и пины (обновлять при установке)

| Компонент | Версия | Источник | Комментарий |
|---|---|---|---|
| kubeadm / kubelet / kubectl | **1.35.9** | pkgs.k8s.io (core:v1.35) | GPUStack требует ≥1.30; связка containerd 2.2.1 + k8s ≥1.33 обкатана на home-lab |
| containerd | **2.2.1** (уже на 04) | apt noble-updates (candidate = 2.2.1-0ubuntu1~24.04.3, замер 2026-10-17) | не обновлять до кластера; registry.mirrors не задавать (ломает CRI) |
| kube-vip | пин сверить при F1 | github kube-vip | только вариант A: статический под, ARP + leaderElection на LAN-интерфейсе |
| Cilium | **1.20.3** | helm cilium/cilium | kubeProxyReplacement=true |
| Longhorn | **1.13.0** | helm longhorn/longhorn | chart = релиз |
| cert-manager | **1.21.2** | helm jetstack/cert-manager | installCRDs=true |
| NFD | **0.20.0** | helm kubernetes-sigs/nfd | GPU-лейблы для GPUStack (`pci-10de.present`) |
| Argo CD | **3.5.5**, chart argo-cd **10.10.5** (пинить точно, не `10.x`) | helm argoproj/argo-cd | GitOps внутри кластера |
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
**каждом** мастере, LAN-интерфейс `eno1` (02/03; имена на 01/04 сверить до F1);
заводится **до** init и до join. VIP от DHCP-выдачи защищены (2026-10-17/18): `.240` и `.230`
выведены из пула MikroTik (`ranges=.10–.229,.231–.239,.241–.254`); lease-резерв без MAC RouterOS
не принимает, REST-добавление lease заблокировано — резерв делается только пулом.

p2p 10.20.20.0/26 (02↔03) в day-0 не участвует: восток-запад идёт по LAN; с переездом
данных на k8s-04 исходный смысл линка («данные ↔ ingress») утрачен — восстановление
netplan отложено вне рамок спецы.

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

### F1 — kubeadm: init на k8s-01 → join CP на 02/03 → join worker 04
```bash
# [вариант A] на каждом мастере — статический под kube-vip (ARP, eno1, VIP .240),
# до init; приёмка: VIP отвечает ARP с k8s-01.
# kubeadm/kubelet/kubectl 1.35.9 с pkgs.k8s.io (core:v1.35), пакеты предзагружены.

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

### F2 — Cilium (CNI, full KPR)
```bash
helm install cilium cilium/cilium -n kube-system --version 1.20.3 \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=192.168.10.240 --set k8sServicePort=6443   # вариант B: .253
```
Приёмка: 4 Ready; `cilium status --summary` ok.

### F3 — Longhorn
```bash
kubectl annotate node k8s-01 node.longhorn.io/create-default-disk="false"   # ДО install (§6)
helm repo add longhorn https://charts.longhorn.io
helm install longhorn longhorn/longhorn -n longhorn-system --create-namespace --version 1.13.0 \
  --set persistence.defaultClass=true \
  --set 'defaultSettings.defaultReplicaCount=2' \
  --set 'defaultSettings.replicaZoneSoftAntiAffinity=true'
```
Приёмка: в `nodes.longhorn.io` 4 узла, диск ≈250G **только на 02/03/04**; SC longhorn —
default; тестовый PVC replica=2 → Bound, реплики не на k8s-01 → удалить.

### F4 — NFD
```bash
helm repo add nfd https://kubernetes-sigs.github.io/node-feature-discovery/charts
helm install nfd node-feature-discovery/node-feature-discovery \
  -n node-feature-discovery --create-namespace --version 0.20.0
```
Приёмка: на k8s-04 метка `feature.node.kubernetes.io/pci-10de.present=true`.

### F5 — cert-manager + ClusterIssuer (плейсхолдер)
```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version 1.21.2 --set installCRDs=true
```
ClusterIssuer `letsencrypt-wildcard` (DNS-01, solver cloudflare — ADR-0004 ревизия)
создаётся сейчас, solvers/секрет — плейсхолдер (API-токен `DNS:Edit` зоны), заполняется
ingress-планом, не коммитится.
Приёмка: 3/3 Ready; CRD на месте; issuer Ready — после заполнения секрета (ingress-план).

### F6 — Argo CD + GitOps (папка `gitops/`)
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace --version 10.10.5
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d    # до ingress — UI через port-forward
```
`gitops/` в этом репо: `root-app.yaml` + ApplicationSet-watchers (`infra-apps/*`,
`apps/*`), AppProjects, destination in-cluster, вендоринг чартов + оверлеи values
(паттерн home-lab). Деплой = `git push`. Приёмка: Synced/Healthy, selfHeal на drift.

### F7 — Приёмка (health-gate)
```bash
kubectl get nodes -o wide            # 4 Ready, 3 master, kubelet 1.35.9
kubectl get --raw /readyz            # ok
kubectl -n kube-system get pods -l component=etcd          # 3 Running
cilium status --summary
kubectl -n longhorn-system get nodes.longhorn.io ; kubectl get sc
kubectl -n cert-manager get pods ; kubectl -n node-feature-discovery get pods
kubectl -n argocd get applications   # Synced/Healthy
```
Плюс: под с PVC (rw) живёт, namespace create/delete не виснет. Отказоустойчивость:
выключить один мастер → API (endpoint) и нагрузка живы, etcd 2/3.

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
- GPUStack k8s-режим — experimental, вне спецы; версия зафиксирована: **v2.2.3**
  (чарт `gpustack-chart:2.2.3`, ADR-0001); стык: NFD-лейблы + nodeSelector
  воркера на 04 (tolerations больше не нужны).

## 10. Вне спецификации (отдельные планы)

- **Ingress-план (шаг 1 демо)**: способ установки Higress — **открытый конфликт**
  (ADR-0001 Accepted «через GPUStack-chart» vs спека «standalone»; решить до ingress);
  выпуск сертификатов — решение TLS принято ревизией ADR-0004 (LE wildcard через DNS-01
  на Cloudflare DNS, Full strict), реализация (токен, `Certificate`, переезд ingress на
  `https://.230`, режим зоны Full(strict)) — здесь. **Два VIP, не объединять (решение 2026-10-18): `.240` — только
  API control-plane; ingress — отдельный VIP `192.168.10.230`, обслуживают k8s-02+k8s-03**
  (решение владельца): второй инстанс kube-vip в LB-режиме (ARP, pool `.230`) статическим
  подом только на 02/03; Higress-gateway закрепляется на 02/03 (nodeSelector + antiaffinity,
  `externalTrafficPolicy: Local`) — VIP отвечает там, где живой endpoint. NAT 80/443
  переезжает с .253 на `.230` (в ingress-плане). **DNS: split-horizon — работает с 2026-10-18**:
  `dns-static demo-ai-lab.ru` + regexp `(.*)\.demo-ai-lab\.ru` → `.230` (wildcard-имя `*.домен`
  в RouterOS — литерал, нужен именно regexp; приёмка `dig @192.168.10.1 api.demo-ai-lab.ru` → `.230`)
  на MikroTik (LAN-клиенты и Wi-Fi идут напрямую).
- **Внешний путь зоны — Cloudflare Tunnel — ADR-0004 (Accepted, 2026-10-18)**: зона
  reg.ru (NS ns1/ns2.reg.ru, записи `@`/`www` → внешний хостинг [ip в inventory]); зона
  переносится в Cloudflare Free (создана 2026-10-18, записи перенесены 1-в-1), NS меняет
  владелец в reg.ru. Туннель: коннекторы `cloudflared` на k8s-02+k8s-03 (active-active —
  штатный HA: несколько коннекторов на один туннель, переключение на уровне edge без DNS),
  ингресс `demo-ai-lab.ru` + `*.demo-ai-lab.ru` → `http://192.168.10.230`. Публичный DNS
  отвечает адресами Cloudflare — public IP площадки не публикуется; входящие в uplink не
  нужны (только исходящий QUIC/TCP 7844).
  **Исполнено 2026-10-18 02:20 MSK:** туннель `demo-lab-ingress` (id
  `9826db91-1ef2-41a6-89e1-eb6a95512020`, remotely-managed), ингресс `demo-ai-lab.ru` +
  `*.demo-ai-lab.ru` → `http://192.168.10.230` (catch-all 404); DNS-записи CNAME (proxied)
  на `<tunnel-id>.cfargotunnel.com`; коннекторы systemd `cloudflared.service` на k8s-02
  и k8s-03 (токен в `/etc/cloudflared/token.env` 600, `EnvironmentFile` + `cloudflared
  tunnel run` без имени), 8/8 соединений active-active. Осталось: активация зоны (ждём
  propagation NS) и прослушивание на `.230` (до Higress туннель будет отдавать 502/530 —
  это штатно). Опция 2-м шагом: Cloudflare Access на демо-хостнеймы.
  Грабли установки: deb-пакет маскирует свой unit (unmask); `--no-autoupdate` — глобальный
  флаг, у `tunnel run` его нет; `--token-file` не существует (только `TUNNEL_TOKEN` env).
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
- Восстановление backend-netplan 10.20.20.0/26 на 02/03.

## 11. Связанные документы и история

- `architecture/ARCHITECTURE.md` — целевая архитектура C2, размещение сервисов (§5).
- `adr/adr-0001-higress-as-sole-ingress.md` · `adr/adr-0002-node-storage-model.md` ·
  `adr/adr-0003-three-control-planes.md` (Accepted 2026-10-17).
- `network-map-detail.md` — живая карта сети; `architecture/hardware-inventory.md` —
  железо/SMART-журнал.
- Эталонный runbook: `~/git/home-lab/home-k8s/SPEC.md` + `references/bootstrap-pitfalls.md`.

История версии:
- **v1** (2026-10-16): single CP на k8s-02, LV «без переустановки» (204/204/250).
- **v2** (2026-10-17): три CP (ADR-0003); k8s-04 без taint'а, LLM+data-heavy;
  переустановка 02/03 выполнена (однотипная разметка 100G root), пул 250×3; роли
  сервисов по ADR-0003; DHCP-резервации восстановлены (DUID-грабля описана в §2/§9);
  Argo chart запинен 10.10.5; endpoint принят (вариант A); **F0 выполнен** (prep ×3, LV ×3, iscsi ×4; playbook-фикс `/etc/containerd`).
</content>
</invoke>