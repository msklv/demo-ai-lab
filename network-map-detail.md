# Карта сети — demo-ai-lab

Аудит локального сегмента от `this Mac`. Шлюз — MikroTik. Ноды — **чистый Ubuntu 24.04**.
2 сегмента: **L2 LAN** (192.168.88.0/24, DHCP) и **backend** (10.20.20.0/26, прямой линк нод, 2.5Гбит/с).

```mermaid
%%{init: {"theme": "dark", "themeVariables": {"fontFamily": "ui-monospace, monospace", "edgeLabelBackground": "#1e293b", "primaryTextColor": "#e2e8f0", "lineColor": "#94a3b8"}}}%%
graph TD

    INT["Internet"]:::ext
    RT["MikroTik<br/>192.168.88.1<br/>gw · DHCP · DNS"]:::net

    subgraph LAN["192.168.88.0/24 — L2 LAN · 2.5 GbE"]
        direction LR
        MAC["This Mac<br/>.66"]:::mac
        K2["k8s-02<br/>.62 · 12C/14Gi<br/>enp2s0 10.20.20.2"]:::linux
        K4["k8s-03<br/>.64 · 12C/14Gi<br/>enp2s0 10.20.20.3"]:::linux
        K3["k8s-04<br/>.63 · 16C/28Gi<br/>один NIC"]:::linux
    end

    NET20["10.20.20.0/26<br/>backend-линк · 2.5 GbE<br/>(простаивает)"]:::net

    INT ==>|"WAN · mgmt/egress"| RT
    RT ==>|"DHCP/DNS/gw · 2.5GbE"| MAC
    RT ==>|"2.5GbE"| K2
    RT ==>|"2.5GbE"| K4
    RT ==>|"2.5GbE"| K3

    K2 <==>|"enp2s0 · 2.5GbE"| NET20
    K4 <==>|"enp2s0 · 2.5GbE"| NET20

    classDef mac fill:#0b2c3f,stroke:#22d3ee,color:#e2e8f0;
    classDef linux fill:#063f2e,stroke:#34d399,color:#e2e8f0;
    classDef net fill:#3f2a0b,stroke:#fbbf24,color:#e2e8f0;
    classDef ext fill:#1e293b,stroke:#94a3b8,color:#e2e8f0;
```

## Узлы

| Хост | IP (eno1) | 2-й интерфейс | CPU | RAM | NVMe (полный) | состояние |
|---|---|---|---|---|---|---|
| `k8s-02` | 192.168.88.62 | enp2s0 10.20.20.2 · 2.5G up | 12C | 14Gi | 476.9G · root 266G | Ubuntu 24.04 |
| `k8s-03` | 192.168.88.64 | enp2s0 10.20.20.3 · 2.5G up | 12C | 14Gi | 476.9G · root 266G | Ubuntu 24.04 |
| `k8s-04` | 192.168.88.63 | — (enp3s0 down) | 16C | 28Gi | 476.9G · root 98G | Ubuntu 24.04 |
| `this Mac` | 192.168.88.66 | en0 | — | — | — | macOS 26.6 |

## Потоки / роли

- **L2 LAN (192.168.88/24, 2.5GbE)** — mgmt+данные: DHCP/DNS/шлюз от MikroTik; SSH-доступ с этого Mac.
- **Backend 10.20.20/26 (2.5GbE)** — прямой линк `k8s-02 ↔ k8s-03`; сейчас **простаивает**.
