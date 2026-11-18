# Ansible: подготовка ноды к k8s + NVIDIA GPU на k8s-04 (demo-ai-lab)

Детерминированная подготовка Ubuntu-ноды к kubeadm и установка драйвера NVIDIA + Container Toolkit.
**Одна команда** — `site-gpu.yml` последовательно запускает три плейбука:

```bash
# SSH-логин ноды и sudo-пароль экспортируются из локального приватного хранилища
export K8S04_USER=...
ansible-playbook -i hosts.gpu.yml site-gpu.yml
```

Порядок: **1)** `pb-k8s-prep.yaml` — swap off, containerd (systemd cgroup),
модули/sysctl, hostname; **2)** `pb-nvidia-gpu.yaml` — драйвер (может уйти в ребут);
**3)** `pb-nvidia-container-toolkit.yml` — nvidia runtime (рестарт containerd).
Обе переменные обязательны: SSH-логин ноды и sudo-пароль. **Значения** экспортируются из локального
приватного хранилища (`inventory.local.md`, вне git) и в репозиторий не попадают; **имена** переменных
видны в инвентаре/плейбуках (`ansible_user`, `ansible_become_password`) — это не секрет, а контракт
запуска. Команды забора паролей и путей к хранилищу в доки не выносим (правило `AGENTS.md`).

## Подготовка ВСЕХ нод кластера к kubeadm

`pb-k8s-prep.yaml` идемпотентен и гоняется по всем пяти нодам (k8s-01…05) через
отдельный инвентарь `hosts.cluster.yml` (GPU-инвентарь `hosts.gpu.yml` — только k8s-04):

```bash
# SSH-логин ноды и sudo-пароль экспортируются из локального приватного хранилища
export K8S01_USER=... K8S02_USER=... K8S03_USER=... K8S04_USER=... K8S05_USER=...
ansible-playbook -i hosts.cluster.yml pb-k8s-prep.yaml
```

## Подготовка всего кластера — одной командой

`site-cluster.yml` (аналог `site-gpu.yml`, но по сети/подготовке, инвентарь `hosts.cluster.yml`):
`pb-k8s-prep.yaml` на всех пяти (k8s-01…05) → `pb-net-p2p.yaml` на 02/03 + приёмочный ping.
GPU-плейбуки сюда НЕ входят — только `site-gpu.yml` + `hosts.gpu.yml`.

```bash
ansible-playbook -i hosts.cluster.yml site-cluster.yml
```

⚠️ Повторный прогон может откатить containerd 2.2.1→1.x на ноде с docker.io-репо
(снимай `containerd --version` до/после).

## Backend p2p 10.20.20.0/26 (k8s-02 ↔ k8s-03)

`pb-net-p2p.yaml` — netplan p2p-подсети second-NIC на 02/03 (восстановлена 2026-10-18 после переустановки):
enp2s0, статика `10.20.20.2`/`10.20.20.3` (/26), без DHCP и gateway (изолированный L2).
Отдельный файл `/etc/netplan/60-p2p-backend.yaml`. Идемпотентен; приёмка — взаимный
ping по p2p (падение = проверять кабель).
⚠️ `netplan apply` перезапускает systemd-networkd — **SSH по eno1 рвётся** (инцидент
2026-10-18: ноды перебрали DHCP и уехали с зарезервированных адресов). Плейбук
применяет конфиг через `systemd-run` и ждёт возврата ssh; при разрыве проверять факт
применения и адрес eno1, а не повторять вслепую.

```bash
# SSH-логин ноды и sudo-пароль экспортируются из локального приватного хранилища
export K8S02_USER=... K8S03_USER=...
ansible-playbook -i hosts.cluster.yml pb-net-p2p.yaml
```

## Пакеты kubeadm/kubelet/kubectl 1.35.9 (F1)

`pb-k8s-pkgs.yaml` — apt-репозиторий pkgs.k8s.io (core:v1.35), установка строгой
версии `1.35.9-1.1`, `apt-mark hold` на kube*/containerd, включение kubelet.
**Гнать в один день с `kubeadm init/join`**: установленный kubelet до появления
кластера циклически рестартует (штатно, но шумит). В `site-cluster.yml` НЕ входит —
это уже старт F1, а не подготовка. Hold на containerd заодно страхует от даунгрейда
при повторном прогоне `pb-k8s-prep`.

```bash
ansible-playbook -i hosts.cluster.yml pb-k8s-pkgs.yaml
```

## kube-vip VIP .240 (pre-init, F1)

`pb-k8s-vip.yaml` — статический под kube-vip (`vip_arp`, `cp_enable`, `vip_leaderelection`,
`eno1`, VIP `192.168.10.240`) на мастерах (группа `masters` = 01/02/03), шаблон
`templates/kube-vip.yaml.j2`. Пин образа: `v0.9.2@sha256:c6d4f3a3…` (сверен ghcr API
2026-10-18) — bump = править `kube_vip_image` в vars. **Гнать в день F1 до `kubeadm init`**
(endpoint впекается в init); под физически поднимется только после init (до
`kubeadm init` kubelet не читает манифесты). На время init VIP включают вручную
(`ip addr add .240/32 dev eno1` на первом мастере), после `New leader` в логах — снимают.
Грабли v0.9.x (абсолютный `/kube-vip`, hostPath `admin.conf`, `cp_detect=true`; инцидент 2026-10-18)
и запрет digest-индексов в ctr 2.x — в шапке плейбука. Приёмка только post-init: `New leader`
в логах + VIP ровно на одном узле.

```bash
ansible-playbook -i hosts.cluster.yml pb-k8s-vip.yaml
```

## kube-vip LB VIP `.230` — ingress-пара (F7)

`pb-k8s-vip-lb.yaml` — **второй, независимый** инстанс kube-vip в режиме LoadBalancer: следит
за `Service type=LoadBalancer` (не за control-plane), группа `ingress` = k8s-02/03, шаблон
`templates/kube-vip-lb.yaml.j2`. Отличия от API-`.240`: `manager --services --leaderElection`,
`cp_enable=false`, `svc_enable=true`, `vip_arp=true`, `vip_leaderelection=true`,
`vip_leasename=plndr-svc`, интерфейс `eno1`, VIP `192.168.10.230/32`, тот же пин образа
`v0.9.2@sha256:c6d4f3a3…`. Два VIP не склеивать (ADR-0001): `.240` — только API, `.230` — только ingress.

Приёмка: VIP ровно на одном из 02/03 (`ip -4 addr show eno1 | grep 192.168.10.230`), тестовый
Service получает `EXTERNAL-IP .230`, при уводе инстанса с держателя VIP переезжает на второй узел
без потери трафика.

```bash
ansible-playbook -i hosts.cluster.yml pb-k8s-vip-lb.yaml
```

## Пороги kubelet — image GC и eviction (после join)

`pb-kubelet-imagegc.yaml`: GC 90/85 %, `imageMinimumGCAge 10m`, eviction 8 % — дефолты сносят по LRU
образы и раннеры остановленных моделей (инцидент 2026-11-06). Нужен готовый
`/var/lib/kubelet/config.yaml` → шаг **после** `kubeadm join`, в `site-cluster.yml` его нет:

```bash
ansible-playbook -i hosts.cluster.yml pb-kubelet-imagegc.yaml   # --limit k8s-05 для новой ноды
```

Приёмка: `grep -E 'imageGC|imagefs.available' /var/lib/kubelet/config.yaml`.

## values-*.yaml — обязательные values helm-релизов (релизы ставились helm'ом, не Argo)

Лежат рядом с плейбуками как исполняемый артефакт; те же ключи продублированы в спеке §7.

- **`values-f8.yaml`** — Higress-gateway (F8): `gateway.replicas=2`, nodeSelector
  `demo-ai-lab/role=ingress`, required-antiaffinity по `kubernetes.io/hostname`, Service
  `LoadBalancer` с `loadBalancerIP 192.168.10.230` + аннотацией `kube-vip.io/loadbalancerIPs`,
  `externalTrafficPolicy: Local`. Ключи сверены с `helm show values higress.io/higress-core 2.1.9`:
  namespace **`gateway.*`**, а не `higress-core.gateway.*` (это префикс umbrella-чарта).
- **`values-f10.yaml`** — metrics-server (F10, установлен 2026-10-24): `replicas=2`, antiaffinity по
  `app.kubernetes.io/name` (лейбла `k8s-app` в чарте 3.14.0 нет), `--kubelet-insecure-tls` (чарт
  **дополняет** `defaultArgs`). Установка: `helm install metrics-server metrics-server/metrics-server
  -n kube-system --version 3.14.0 -f ansible/values-f10.yaml`; предтяжка образа с `registry.k8s.io`
  и грабли — спека §7 F10, §9.

## Порядок работ и факты ноды

Драйвер ставится **до** `kubeadm join` (нужен ребут), `hosts.gpu.yml` держит только k8s-04.
Факты узла и текущее состояние — `architecture/ARCHITECTURE.md` §7 и
`architecture/hardware-inventory.md`; здесь не дублируются.

## Что делает каждый плейбук

1. **`pb-k8s-prep.yaml`** — общая подготовка любой ноды к kubeadm: hostname = имени в inventory,
   swap off (runtime + fstab), containerd с `SystemdCgroup = true`, модули `overlay`/`br_netfilter`
   (persist в `/etc/modules-load.d/k8s.conf`), sysctl (`bridge-nf-call-iptables/ip6tables`, `ip_forward`;
   persist в `/etc/sysctl.d/k8s.conf`). Идемпотентен — можно гонять на любой ноде.
2. **`pb-nvidia-gpu.yaml`** — драйвер: **Blackwell (RTX 50xx) ставится в варианте `-open`
   (open kernel modules), закрытый модуль отказывает** (`RmInitAdapter 0x22:0x56:1017`).
   Пин `nvidia_driver_version` в шапке; drift-check против `latest.txt` предупреждает о новинке
   (не автокатит). .deb (~780 МБ) качается один раз в `ansible/driver/` (в `.gitignore`),
   nouveau блэклистится, после установки — hold + blacklist unattended-upgrades.
   Ребут — только если `nvidia-smi` ещё не работает.
3. **`pb-nvidia-container-toolkit.yml`** — пин `nvidia_ctk_version` в шапке; рантайм containerd,
   docker-часть — только если docker установлен.

Bump версии = сдвинуть пин **и** `driver_deb_sha256` → перезапустить (unhold → install → hold сам);
при несовпадении хеша плейбук падает до установки, а не ставит битый `.deb` из кэша.

**Почему до k8s:** драйвер требует ребута, toolkit — рестарта containerd; в кластере оба действия выносят поды ноды.

## Верификация

```bash
ssh ...@192.168.10.252 'nvidia-smi'      # имя карты, драйвер, VRAM
# после bootstrap k8s: проверять NFD-метку GPU (ресурса nvidia.com/gpu в кластере нет):
kubectl get nodes -L feature.node.kubernetes.io/pci-10de.present
```
