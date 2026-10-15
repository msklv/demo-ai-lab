# Ansible: NVIDIA GPU на k8s-04 (demo-ai-lab)

Детерминированная установка последнего production-драйвера NVIDIA и Container Toolkit
на GPU-ноду стенда. **Одна команда** — `site.yml` последовательно запускает оба плейбука:

```bash
export SUDO_PASSWORD_demo_ai_lab=...   # приватный, из ~/.hermes/.env
export K8S04_USER=...                  # логин ноды (приватный, в git не публикуем)
ansible-playbook -i hosts.gpu.yml site.yml
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

## Что делает site.yml

1. **Драйвер 595.91.07** (`pb-nvidia-gpu.yaml`): качает .deb (~780 МБ) один раз в `ansible/driver/`,
   ставит, блэклистит nouveau, hold + blacklist unattended-upgrades; ребут — только если
   `nvidia-smi` ещё не работает. Drift-check предупреждает о новинке в `latest.txt` (не автокатит).
2. **Container Toolkit 1.20.1-1** (`pb-nvidia-container-toolkit.yml`): рантайм containerd,
   docker-часть — только если docker установлен.

Пины версий: `nvidia_driver_version` и `nvidia_ctk_version` — в шапках плейбуков.
Bump = сдвинуть пин и перезапустить (unhold → install → hold сам).

**Почему до k8s:** драйвер требует ребута, toolkit — рестарта containerd; на ноде в кластере
оба действия выносят её поды. k8s-04 ещё не в кластере — идеальный момент.

## Верификация

```bash
ssh ...@192.168.10.252 'nvidia-smi'      # имя карты, драйвер, VRAM
# после bootstrap k8s:
kubectl get nodes -L nvidia.com/gpu
```

Отдельные плейбуки (`pb-nvidia-gpu.yaml`, `pb-nvidia-container-toolkit.yml`) можно запускать
по отдельности, но `site.yml` — штатный путь.
