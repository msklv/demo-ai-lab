# Спецификация установки Kubernetes на стенд demo-ai-lab

> Статус: **черновик** (2026-10-16). Установка k8s (kubeadm 1.35) + Cilium + Longhorn + cert-manager + Argo CD.
> Higress и GPUStack в эту спецификацию **не входят** — отдельный план
> (инфраструктура «во главе с GPUStack», шаг 1 демо).
> Секреты (логины нод, sudo-пароль, public IP, MAC) — вне документа, см. §12.

## 1. Назначение и границы

- Цель: воспроизводимый runbook установки кластера на 4× GMKtec (k8s-01/02/03/04)
  до состояния «готов под демо-шаг 1»: kubeadm init/join → Cilium → Longhorn
  (данные на **всех** нодах) → NFD → cert-manager → Argo CD + GitOps.
- Не входит: Higress (ingress), GPUStack, модели, сервисы демо-шагов 2/3, BeeLlama —
  ставятся отдельно после готовности кластера. **cert-manager входит в спецификацию (F5)**:
  PKI-провижнер на уровне кластера, готовый к приходу ingress-плана.
- Форма кластера: **single control-plane** (etcd из 1 члена), демо-стенд, не prod.
  HA/двойной etcd — явный out-of-scope; при желании позже — отдельный план.

## 2. Предусловия (текущее состояние, проверено живым аудитом)

| Узел | LAN IP | Роль | CPU/RAM | Диск (физика 476.9G) |
|---|---|---|---|---|
| k8s-01 | 192.168.10.250 | **добавлена 2026-10-17, роль не назначена; НЕ готова** — containerd нет, swap ON, нужен pb-k8s-prep перед join | R7 7840HS 8C/16T · 32Gi | root-LV 100G, свободно в VG ~374G |
| k8s-02 | 192.168.10.253 | control-plane + Longhorn (данные) + Argo CD | R5 7640HS 6C/12T · 14Gi | root-LV 270G, свободно в VG ~204G |
| k8s-03 | 192.168.10.254 | worker: данные + Longhorn | R5 7640HS 6C/12T · 14Gi | root-LV 270G, свободно в VG ~204G |
| k8s-04 | 192.168.10.252 | worker LLM (taint `dedicated=llm:NoSchedule`) + Longhorn | R7 H255 8C/16T · 28Gi | root-LV 100G, свободно в VG ~374G |

Уже готово (pb-k8s-prep.yaml, 2026-10-12):
- containerd 2.2.1 с CRI (`systemd_cgroup=true`, pause 3.10) на всех нодах;
- swap off (в т.ч. fstab), `/etc/hosts` именами соседних нод, строка установщика
  `127.0.1.1 <hostname>` **удалена** (иначе резолв соседних сервисов уходит на loopback);
- DHCP-резервирования IP нод на MikroTik (make-static);
- NAT 80/443 → 192.168.10.253 (для будущего ingress, не используется этим планом).
  > ⚠️ `127.0.1.1` — критично: два адреса на одно имя дают первым матчем loopback;
  > kubelet node-IP берёт автоопределением по маршруту → должен получиться LAN-IP.
- Не готово: kubeadm/kubelet, kube-proxy нет (ставим Cilium full KPR), longhorn-LV,
  open-iscsi, kubeconfig на консоли.

## 3. Версии и пины (VERSIONS — обновлять при установке)

| Компонент | Версия | Источник | Комментарий |
|---|---|---|---|
| kubeadm / kubelet / kubectl | **1.35.9** | pkgs.k8s.io (core:v1.35) | требование GPUStack ≥1.30 выполнено с запасом; связка containerd 2.2.1 + k8s ≥1.33 обкатана на home-lab |
| containerd | 2.2.1 (уже стоит) | apt | НЕ обновлять до установки кластера; registry.mirrors НЕ задавать (ломает CRI) |
| Cilium | **1.20.3** | helm cilium/cilium | kubeProxyReplacement=true, kube-proxy не ставим |
| Longhorn | **1.13.0** | helm longhorn/longhorn | chart-версия = версия релиза |
| cert-manager | **1.21.2** | helm jetstack/cert-manager | `installCRDs=true`; ClusterIssuer создаётся в F5, внешний DNS-solver — плейсхолдер (секрет заполняется в ingress-плане) |
| Node Feature Discovery | **0.20.0** | helm kubernetes-sigs/nfd | обязателен: даёт GPU-лейблы для GPUStack-воркера (`pci-10de.present`) |
| Argo CD | **3.5.5** (chart argo-cd 10.x) | helm argoproj/argo-cd | GitOps внутри кластера |
| Helm (клиент) | ≥3.18.4 | Mac-консоль | требование чарта GPUStack (из внешнего плана) |

Все чарты/образы — предзагрузить до фазы установки (egress площадки 4–6 МБ/с;
Docker Hub rate-limit = минуты тишины на сцене).

## 4. Сеть кластера (план)

| Параметр | Значение | Обоснование |
|---|---|---|
| controlPlaneEndpoint | `192.168.10.253:6443` | статичный LAN-IP CP. Без VIP/L2: NAT 80/443 уже смотрит на .253, hairpin решается позже в ingress-плане; VIP — только если придёт HA |
| podSubnet | `10.42.0.0/16` | не пересекается с LAN 192.168.10.0/24, p2p 10.20.20.0/26, uplink |
| serviceSubnet | `10.99.0.0/16` | не пересекается (проверено по существующим сегментам) |
| certSANs apiserver | `192.168.10.253`, `k8s-02`, `127.0.0.1` | до join CP; невалидный SAN ломает kubectl с консоли |
| kubelet node-IP | авто (default route) → 192.168.10.x | уже корректно благодаря §2 (нет 127.0.1.1) |
| Cilium `k8sServiceHost/Port` | `192.168.10.253:6443` | **обязательно** при `kubeProxyReplacement=true` без kube-proxy: иначе init-контейнер Cilium падает (ClusterIP .1 недоступен до CNI) — грабля home-lab |
| p2p 10.20.20.0/26 (02↔03) | не используется для overlay | east-west идёт через LAN-интерфейсы. Использовать 2.5G p2p для Cilium — отдельная оптимизация, не day-0 |
| kubectl консоли | `~/.kube/demo-ai-lab.conf` | admin.conf с ноды, server → `https://192.168.10.253:6443`; не воевать с root на нодах |

## 5. Дисковая модель day-0 — БЕЗ переустановки нод (решение 2026-10-16)

> Отменяет план ADR-0002 «переустановка Ubuntu 02/03 под LV 250G».
> LV режутся из **свободного места существующего VG**: 02/03 — весь остаток (~204G),
> 04 — 250G. Требует правки ADR-0002 (см. §12).

```bash
# на КАЖДОЙ ноде (sudo)
sudo vgs                                          # контроль свободного места
# 02 и 03: весь свободный остаток VG (~204G)
sudo lvcreate -l 100%FREE -n longhorn ubuntu-vg
# 04: фиксированный объём (свободно ~374G)
sudo lvcreate -L 250G -n longhorn ubuntu-vg
sudo mkfs.ext4 -L longhorn /dev/ubuntu-vg/longhorn
sudo mkdir -p /var/lib/longhorn
echo "UUID=$(sudo blkid -s UUID -o value /dev/ubuntu-vg/longhorn) /var/lib/longhorn ext4 defaults 0 2" | sudo tee -a /etc/fstab
sudo mount -a && df -h /var/lib/longhorn          # приёмка: смонтирован, размер ~LV
sudo apt-get update && sudo apt-get install -y open-iscsi   # требование Longhorn (все ноды)
```

Итог пула: ~204 + ~204 + 250 = **~658G**, полезных при replica=2 ≈ **329G**.
root-LV 02/03 (270G) не трогаем: LVM-shrink назад почти нереализуем.
**Блокер до kubeadm init**: LV и open-iscsi должны быть на нодах ДО Longhorn-фазы.

## 6. Taint / affinity-политика

| Узел | Правило | Реализация |
|---|---|---|
| k8s-02 | **taint control-plane снять** — Longhorn обязан жить на CP-ноде (требование) | `kubectl taint nodes k8s-02 node-role.kubernetes.io/control-plane-` (после init); CP несёт данные Longhorn, как home-lab |
| k8s-04 | taint `dedicated=llm:NoSchedule` **оставить** (LLM-нода) | Longhorn терпит его: `defaultSettings.taintToleration: "dedicated=llm:NoSchedule"` — иначе longhorn-manager/instance-manager не встанут на 04 ∈ пуле |
| Higress/GPUStack | входят во внешний план | GPUStack-woker потребует tolerations на 04 + NFD-лейблы (§4 NFD) |

## 7. Порядок установки (фазы)

### F0 — Подготовка: диски + open-iscsi (§5) + контроль pb-k8s-prep
- Выполнить §5 на всех нодах. Прогнать `pb-k8s-prep.yaml` (hosts.cluster.yml) — содержит
  /etc/hosts, swap, containerd, модули/sysctl (если ещё не прогнан).
- Приёмка: `df -h /var/lib/longhorn` на 3 нодах; `reboot`-проверка fstab опциональна.

### F1 — kubeadm init (k8s-02) + join (03, 04)

```bash
# kubeadm 1.35.9 ставится с pkgs.k8s.io (core:v1.35) — пакеты предзагрузить заранее
cat > kubeadm-config.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
nodeRegistration:
  criSocket: unix:///var/run/containerd/containerd.sock
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: v1.35.9
controlPlaneEndpoint: "192.168.10.253:6443"
apiServer:
  certSANs: ["192.168.10.253", "k8s-02", "127.0.0.1"]
networking:
  podSubnet: "10.42.0.0/16"
  serviceSubnet: "10.99.0.0/16"
EOF
sudo kubeadm init --config kubeadm-config.yaml --skip-phases=addon/kube-proxy   # на 02
sudo kubeadm token create --print-join-command    # на 02 → выполнить на 03 и 04 (sudo)
```
- kubeconfig консоли: с ноды `sudo cat /etc/kubernetes/admin.conf` → `~/.kube/demo-ai-lab.conf` (server = https://192.168.10.253:6443).
- Приёмка: `kubectl get nodes -o wide` — 3 узла Registered (Ready появится после Cilium);
  `kubectl get po -n kube-system` — нет kube-proxy.

### F2 — Cilium (CNI, full KPR)

```bash
helm install cilium cilium/cilium -n kube-system --version 1.20.3 \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=192.168.10.253 --set k8sServicePort=6443
```
- Приёмка: `kubectl get nodes` — **3 Ready**; `cilium status --summary` — ok.

### F3 — Longhorn

```bash
helm repo add longhorn https://charts.longhorn.io
helm install longhorn longhorn/longhorn -n longhorn-system --create-namespace --version 1.13.0 \
  --set persistence.defaultClass=true \
  --set 'defaultSettings.defaultReplicaCount=2' \
  --set 'defaultSettings.replicaZoneSoftAntiAffinity=true' \
  --set 'defaultSettings.taintToleration=dedicated=llm:NoSchedule'
```
- Приёмка: `kubectl -n longhorn-system get nodes.longhorn.io` — 3 ноды, у каждой диск
  со `storageMaximum` ≈ размеру LV; `kubectl get sc` — longhorn default;
  создать тестовый PVC (replica=2) → Bound → удалить.

### F4 — NFD (для GPU-плана и GPUStack)

```bash
helm repo add nfd https://kubernetes-sigs.github.io/node-feature-discovery/charts
helm install nfd node-feature-discovery/node-feature-discovery \
  -n node-feature-discovery --create-namespace --version <chart-версия 0.20.0>
```
- Приёмка: на k8s-04 метка `feature.node.kubernetes.io/pci-10de.present=true`.

### F5 — cert-manager (PKI-провижнер кластера)

```bash
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version 1.21.2 --set installCRDs=true
```
- ClusterIssuer для внешних доменов создаётся сейчас (wildcard, DNS-01), секрет solver'а —
  **плейсхолдер**: заполняется в ingress-плане, не коммитится:
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-wildcard
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: <placeholder@demo-ai-lab.ru>
    privateKeySecretRef: {name: letsencrypt-wildcard-key}
    solvers:
      - dns01:
          <placeholder: провайдер DNS, креды из секрета>
```
- Приёмка: `kubectl -n cert-manager get pods` — 3/3 Ready; CRD `certificates.cert-manager.io`
  установлен; ClusterIssuer создан (Ready — после заполнения секрета, проверяется в ingress-плане).

### F6 — Argo CD + GitOps (папка `gitops/`)

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace --version 10.x
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d    # до ingress — UI через port-forward
```
- Создать в репозитории **`gitops/`** (публичный demo-ai-lab, секретов нет):
  `root-app.yaml` + ApplicationSet-watchers (списки `infra-apps/*`, `apps/*`) +
  AppProjects; destination `https://kubernetes.default.svc` (in-cluster SA);
  вендоринг чартов в подпапки, оверлей `values.yaml` (паттерн home-lab).
- Применение: `kubectl apply -f gitops/root-app.yaml`; далее `git push` = деплой.
- Статус-баннер: долг — маркировать период установки.
- Приёмка: Application Synced/Healthy; selfHeal на тестовом drift.

### F7 — Приёмка кластера (health-gate)

```bash
kubectl get nodes -o wide                       # 3 Ready, kubelet 1.35.9
cilium status --summary
kubectl -n longhorn-system get nodes.longhorn.io ; kubectl get sc
kubectl -n cert-manager get pods                # 3/3 Ready
kubectl -n node-feature-discovery get pods
kubectl -n argocd get applications              # Synced/Healthy
```
Плюс: тестовый под с PVC из Longhorn (rw), создание/удаление namespace не зависает.

## 8. GitOps-памятка (паттерн home-lab)

- Argo CD живёт внутри кластера (ns `argocd`), единственная точка входа — git-репозиторий.
- Вывод узла из эксплуатации: `git pull --ff-only` перед push; после push проверять
  `argocd application status` не по «Synced», а по живому образу пода.
- Секреты в git НЕ кладём: приватный материал — inventory.local.md (gitignored),
  в манифестах — плейсхолдеры.

## 9. Риски и открытые вопросы

- **Single control-plane / etcd из 1 члена** — нулевая отказоустойчивость API; принято
  для демо-стенда. Про проговорить до начала работ.
- **Longhorn-данные на CP (02)** — конкуренция за CPU/RAM с Argo/CD/CDN: 14Gi на 02;
  следить по RAM-бюджету (Longhorn-manager ~1G). Приемлемо (проверено на home-lab).
- Cilium full KPR без kube-proxy — команды `kubectl proxy`/Service-диагностика отличаются;
  фиксы в `references/argo-cilium-notes.md` home-lab.
- k8s 1.35 + containerd 2.2.1: CRI v1 совместим (обкатано на 1.33); если kubeadm заругается
  на containerd — проверить `crictl info` (criSocket верный).
- GPUStack k8s-режим — experimental и вне этой спецы; стыкуется через NFD-лейблы (§4) и
  tolerations воркера на 04 (внешний план).

## 10. Вне спецификации (отдельные планы)

- Higress (ingress) — отдельная установка на кластер (план «Шаг 1 — Инфраструктура во главе
  с GPUStack»): Higress standalone → GPUStack helm с `higress-core.enabled=false`,
  `gateway.ingressClassname=higress`. Let's Encrypt: ClusterIssuer уже создан в F5,
  фактический выпуск сертификатов и hairpin — в ingress-плане.
- Beam: BeeLlama (хостовый процесс на k8s-04) vs GPUStack CUDA-воркер — политика владения
  GPU RTX 5060 Ti решается в том же плане (демо: `stop_beellama_5060.sh` перед GPUStack).
- Метрики/логи/трейсы (Langfuse и пр.) — day-2, по RAM-бюджету.

## 11. Связанные документы

- `architecture/ARCHITECTURE.md` — целевая архитектура C2 (нужны правки, §12).
- `adr/adr-0001-higress-as-sole-ingress.md`, `adr/adr-0002-node-storage-model.md`.
- `network-map-detail.md` — живая карта сети.
- Home-lab runbook (эталон): `~/git/home-lab/home-k8s/SPEC.md` + `references/bootstrap-pitfalls.md`.

## 12. Правки, которые нужно внести (по этому решению)

| Документ | Правка |
|---|---|
| ADR-0002 | Переустановка 02/03 отменена: LV из свободного места VG (02/03 — 100%FREE ~204G, 04 — 250G), taint CP на 02 снимается; статус/текст поправить |
| README.md | Строка «дискретного GPU на стенде нет» → GPU RTX 5060 Ti 16G на k8s-04 есть (демо-сценарий шага 1 пересматривается: GPU-first, CPU — фолбэк) |
| ARCHITECTURE.md | §2.3/§5: root-LV 02/03 больше «270G-навсегда» — после LV-разметки данные на longhorn-томах; §7 п.4 «GPU не в инвентаре» → устарело |
| demo-plan (skill) | «CPU-first, GPU нет» → GPU есть; NFD из опционала перешёл в обязательную инфраструктуру |