# Ansible: подготовка ноды к k8s + NVIDIA GPU на k8s-04 (demo-ai-lab)

Детерминированная подготовка Ubuntu-ноды к kubeadm и установка драйвера NVIDIA + Container Toolkit.
**Одна команда** — `site-gpu.yml` последовательно запускает три плейбука:

```bash
export SUDO_PASSWORD_demo_ai_lab="$(grep -E '^SUDO_PASSWORD_k8s_home_lab=' ~/.hermes/.env | head -1 | cut -d= -f2- | tr -d '\r')"   # приватный
export K8S04_USER=...
ansible-playbook -i hosts.gpu.yml site-gpu.yml
```

Порядок: **1)** `pb-k8s-prep.yaml` — swap off, containerd (systemd cgroup),
модули/sysctl, hostname; **2)** `pb-nvidia-gpu.yaml` — драйвер (может уйти в ребут);
**3)** `pb-nvidia-container-toolkit.yml` — nvidia runtime (рестарт containerd).
Обе переменные обязательны: `K8S04_USER` — SSH-логин ноды, `SUDO_PASSWORD_demo_ai_lab` —
пароль для sudo. Отдельной переменной `SUDO_PASSWORD_demo_ai_lab` в `~/.hermes/.env` нет:
пароль стенда лежит под `SUDO_PASSWORD_k8s_home_lab` — выше он экспортируется из неё.

## Подготовка ВСЕХ нод кластера к kubeadm

`pb-k8s-prep.yaml` идемпотентен и гоняется по всем трём нодам (k8s-02/03/04) через
отдельный инвентарь `hosts.cluster.yml` (GPU-инвентарь `hosts.gpu.yml` — только k8s-04):

```bash
export SUDO_PASSWORD_demo_ai_lab="$(grep -E '^SUDO_PASSWORD_k8s_home_lab=' ~/.hermes/.env | head -1 | cut -d= -f2- | tr -d '\r')"
export K8S02_USER=... K8S03_USER=... K8S04_USER=...
ansible-playbook -i hosts.cluster.yml pb-k8s-prep.yaml
```

## Подготовка всего кластера — одной командой

`site-cluster.yml` (аналог `site-gpu.yml`, но по сети/подготовке, инвентарь `hosts.cluster.yml`):
`pb-k8s-prep.yaml` на всех четырёх → `pb-net-p2p.yaml` на 02/03 + приёмочный ping.
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
export SUDO_PASSWORD_demo_ai_lab=...   # экспортируется из локального приватного хранилища
export K8S02_USER=... K8S03_USER=...
ansible-playbook -i hosts.cluster.yml pb-net-p2p.yaml
```

## Факты ноды (снято 2026-10-15)

| Параметр | Значение |
|---|---|
| Узел / IP | k8s-04 / 192.168.10.252 |
| ОС / ядро | Ubuntu 24.04.4 / 6.8.0-147-generic |
| GPU | 10de:2d04 (RTX 5060 Ti); точное имя — `nvidia-smi` после установки |
| Secure Boot | выключен |
| containerd | 2.2.1; docker НЕ установлен |
| k8s | НЕ установлен — ставить GPU ДО kubeadm join |

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

Bump версии = сдвинуть пин и перезапустить (unhold → install → hold сам).

**Почему до k8s:** драйвер требует ребута, toolkit — рестарта containerd; на ноде в кластере
оба действия выносят её поды. k8s-04 ещё не в кластере — идеальный момент.

## Верификация

```bash
ssh ...@192.168.10.252 'nvidia-smi'      # имя карты, драйвер, VRAM
# после bootstrap k8s:
kubectl get nodes -L nvidia.com/gpu
