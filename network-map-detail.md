# Карта сети — demo-ai-lab

Актуализировано **2026-02-12 04:38 MSK** по живому аудиту: REST-API MikroTik (`192.168.10.1`),
DHCP-leases с роутера, SSH на ноды. **2026-09-24** MAC/логины — в `inventory.local.md`
(не публикуется).

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, monospace", "edgeLabelBackground": "#1e293b", "primaryTextColor": "#e2e8f0", "lineColor": "#94a3b8"}}}%%
graph TD

    UP["Uplink 192.168.3.0/24<br/>gw 192.168.3.1 · public IP [confidential]"]:::ext

    RT["MikroTik L009UiGS-2HaxD<br/><b>MikroTikHome</b> · 192.168.10.1<br/>RouterOS 7.21.1 · DHCP · FW · NAT"]:::net

    subgraph LAN["LAN 192.168.10.0/24 · DHCP pool .10–.254 · lease 1h"]
        direction LR
        MAC["This Mac en0/Wi-Fi<br/>.20"]:::mac
        K2["k8s-02<br/>.13 · 12T/14Gi<br/>enp2s0 10.20.20.2"]:::linux
        K3["k8s-03<br/>.12 · 12T/14Gi<br/>enp2s0 10.20.20.3"]:::linux
        K4["k8s-04<br/>.14 · 16T/28Gi<br/>2-й NIC down"]:::linux
    end

    K2 <==>|"enp2s0 2.5G"| BE["backend 10.20.20.0/26"]
    K3 <==>|"enp2s0 2.5G"| BE

    UP ==>|"ether1 · DHCP · 192.168.3.98"| RT
    UP -.->|"192.168.3.0/24"| MINI
    RT ==>|"Wi-Fi 5G · DHCP"| MAC
    RT ==>|"bridge · DHCP"| K2
    RT ==>|"bridge · DHCP"| K3
    RT ==>|"bridge · DHCP"| K4

    classDef mac fill:#0b2c3f,stroke:#22d3ee,color:#e2e8f0;
    classDef linux fill:#063f2e,stroke:#34d399,color:#e2e8f0;
    classDef net fill:#3f2a0b,stroke:#fbbf24,color:#e2e8f0;
    classDef ext fill:#1e293b,stroke:#94a3b8,color:#e2e8f0;
```

## Сегменты

| Сегмент | Назначение | Адресация | Статус |
|---|---|---|---|
| `192.168.10.0/24` | LAN: кластер + консоль, DHCP, NAT в интернет | DHCP pool `.10–.254` (lease 1h10m) | живой |
| `192.168.3.0/24` | uplink за MikroTik (gw `.1`, dns `.1`); DHCP на ether1 (MikroTik = `.98`) | живой |
| `10.20.20.0/26` | backend p2p k8s-02↔k8s-03, 2.5G MTU 1500 | статика в netplan | живой, L2 проверен |

## Узлы кластера

| Хост | IP (LAN, DHCP) | 2-й интерфейс | CPU | RAM | Роль / состояние |
|---|---|---|---|---|---|
| `k8s-02` | 192.168.10.13 | `enp2s0` 10.20.20.2/26 · 2.5G up | 12T (6C, R5 7640HS) | 14Gi | будущий CP · Ubuntu 24.04.4 |
| `k8s-03` | 192.168.10.12 | `enp2s0` 10.20.20.3/26 · 2.5G up | 12T (6C, R5 7640HS) | 14Gi | worker · Ubuntu 24.04.4 |
| `k8s-04` | 192.168.10.14 | `enp3s0` — **down** | 16T (8C, R7 H 255) | 28Gi | новый, БЕЗ containerd · Ubuntu 24.04.4 |
| `This Mac` | 192.168.10.20 (Wi-Fi) | — | — | — | консоль (ssh/kubectl) |

## Ключевые точки

- Шлюз — физический MikroTik `L009UiGS-2HaxD` (`192.168.10.1`, identity `MikroTikHome`),
  RouterOS 7.21.1. WAN = `192.168.3.98/24` за шлюзом `192.168.3.1`; public IP [confidential].


## Проверено / не проверено

**Проверено (живые команды):**
- SSH по ключу на `k8s-02/03/04` → `hostname` соответствует, backend-интерфейсы те же.
- Аутентификация на MikroTik: REST API (Basic) подтверждён, SSH на роутере отклонён.
- DHCP: pool `.10–.254`, lease 1h10m; DNS-статик `router.lan`.

**Не проверено (не выдумываю):**
- НЕ резервируются ли DHCP-лизы нод по MAC (иначе адреса поедут со следующим lease).
- Внешняя доступность демо-сервисов из интернета (public IP [confidential] — проверял только в облаке роутера).

## Управление

Подключение к нодам (SSH) и к MikroTik (Winbox/REST) — см. `inventory.local.md` (доступ
только у владельца; логины/пароль там, файл не публикуется).
