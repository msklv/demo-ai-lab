# network — сеть стенда

Топология, адресация, шлюз и внешний доступ. Здесь только сетевые факты; железо нод —
`../architecture/hardware-inventory.md`, роли и размещение сервисов — `../architecture/ARCHITECTURE.md`.

| Файл | Что внутри |
|---|---|
| `map.md` | карта сети: сегменты, узлы и их сетевые роли, VIP `.230`/`.240`, split-DNS, изоляция LAN→uplink, Wi-Fi, JetKVM |
| `mikrotik.md` | рецепт шлюза RouterOS: bridge и LAG, DHCP/DNS, NAT и проброс, фактический порядок правил firewall, Wi-Fi, службы, квирки REST |

Рядом, но не переносятся — это архитектурные артефакты, на них ссылаются ADR:

- `map.jpg` — рендер mermaid-карты из `map.md` (`python3 scripts/render_diagrams.py network`);
- `../architecture/endpoints.md` — адреса сервисов и SSO;
- `../architecture/specs/external-access-spec.md` — внешний путь (фазы E, приёмки), решение — ADR-0004;
- `../adr/adr-0001-higress-as-sole-ingress.md` — почему ingress один и на паре 02/03.

Как снять состояние заново: REST MikroTik `http://192.168.10.1:8080/rest/...` (основное чтение),
DHCP-лизы там же, SSH на ноды — разово; порядок правил firewall — только по SSH
`/ip firewall filter print without-paging`. Общая приёмка стенда — `../scripts/k8s_health.py`
(кластер) и `../scripts/env_health.py` (внешний путь).

MAC-адреса, логины и пароли в этой папке не публикуются — только `../inventory.local.md` (gitignored).
