# Спецификация внешнего доступа стенда demo-ai-lab

> **Версия 1** (2026-10-19), статус: черновик. Цель — `demo-ai-lab.ru` живёт снаружи
> **только через Cloudflare** (ADR-0004, Accepted) и изнутри LAN — через split-horizon
> MikroTik; public IP площадки наружу не светится вообще. Владелец контура — эта спека;
> решение — `adr/adr-0004-external-access-cloudflare-tunnel.md`, рецепт роутера для
> слушателей — `mikrotik-setup.md`.
> Секреты (токен туннеля, API-токен Cloudflare, sudo) — вне документов (`inventory.local.md`).

## 1. Границы и инвентарь контура

| Сущность | Значение | Статус |
|---|---|---|
| Домен | `demo-ai-lab.ru` (публичный бренд, публикуется) | reg.ru, NS перенесены в Cloudflare |
| Зона Cloudflare | Free, DNS-only зона + proxy CNAME | активирована 2026-10-18 |
| Туннель | `demo-lab-ingress`, id `9826db91-1ef2-41a6-89e1-eb6a95512020` (публичный — виден в CNAME), remotely-managed | healthy |
| Коннекторы | `cloudflared` (systemd) на k8s-02 и k8s-03, active-active | работают |
| Origin | `192.168.10.230` — ingress-VIP пары 02/03 (ADR-0001; отдельный от API-VIP `.240`, **не склеивать**) | слушатель есть с 2026-10-19 (F7/F8): Higress отвечает 200 из LAN; tunnel-ingress пока `http://` — переезд на `https://` в E5 |
| Split-horizon | MikroTik `dns static` + regexp → `.230` для LAN-клиентов | работает 2026-10-18 |
| legacy NAT | dstnat WAN tcp 80/443 → `.253` (историческое, 2026-10-12) | отключить на E5 |

Не входит: содержимое ingress (Higress-маршруты, AI-плагины, guard-маршрут) — остаток
§10 инсталл-спеки / план демо; механизм `.230`+Higress — там же (F7/F8);
установка кластера — `k8s-install-spec.md`. Пины: cloudflared `2026.10.1` (deb-репо Cloudflare,
autoupdate выключён флагом), cert-manager `1.21.2` (F5 спеки установки — PKI-провижнер LE),
LE-цепочка ISRG Root X1.

## 2. Целевая схема (два пути, один origin)

```
Внешний зритель ──▶ Cloudflare edge (анycast, IP Cloudflare) ──QUIC──▶ cloudflared(02|03)
                     demo-ai-lab.ru + *.demo-ai-lab.ru                        │
                                                                              ▼
LAN-зритель ──dig @192.168.10.1──▶ .230 ────────────▶ Higress-gateway (02/03)
```

- Наружу из uplink идёт только исходящий QUIC/7844(+TCP-fallback) к Cloudflare; входящие не нужны.
- `.230` обслуживает пара 02/03: второй инстанс kube-vip (LB-режим, pool `.230`) статическим
  подом **только на 02/03**; Higress-gateway nodeSelector на 02/03 + `externalTrafficPolicy: Local`
  — VIP отвечает там, где живой endpoint.
- Клиент LAN, упоршийся в публичный DNS (8.8.8.8), получит edge Cloudflare и попадёт туда же
  через туннель — это ожидаемое поведение, не ошибка split-DNS.

## 3. Фазы и критерии приёмки

### E1 — Зона Cloudflare — ✅ выполнено 2026-10-18
Приёмка (проверено):
```bash
dig +short NS demo-ai-lab.ru @1.1.1.1        # irena.ns.cloudflare.com / newt.ns.cloudflare.com
dig +short demo-ai-lab.ru                    # 104.21.x / 172.67.x — адреса Cloudflare, НЕ площадка
dig +short api.demo-ai-lab.ru                # то же (proxied CNAME на <tunnel-id>.cfargotunnel.com)
```
- DS-записи в реестре .ру нет → DNSSEC на зоне выключен (иначе NXDOMAIN-брайк).
- Записи `@`/`www`/wildcard перенесены с reg.ru 1-в-1, все сервисные — proxied CNAME.

### E2 — Туннель и коннекторы — ✅ выполнено 2026-10-18
Коннекторы: `cloudflared.service`, `TUNNEL_TOKEN` из `EnvironmentFile=/etc/cloudflared/token.env`
(600), `tunnel run` без имени. Ингресс туннеля: `demo-ai-lab.ru` + `*.demo-ai-lab.ru` →
`http://192.168.10.230` (E5 переключит на `https://` + caPool).
Приёмка:
- Dashboard/API туннеля: 2 коннектора (02 и 03), соединения active-active, connIndex 0..3,
  версии cloudflared совпадают на обоих;
- **после любого сетевого ребута на ноде — рестарт `cloudflared` и контроль connIndex**:
  QUIC-шторм после перезапуска сети штатен, без рестарта коннектор может висеть деградированным;
- до появления слушателя на `.230` edge отдаёт **530/502 — это штатно**, не считать инцидентом.
Грабли установки (зафиксированы): deb маскирует свой unit (unmask); `--no-autoupdate` — только
глобальный флаг (у `tunnel run` его нет); `--token-file` не существует — только `TUNNEL_TOKEN`.

### E3 — MikroTik: адреса и split-horizon DNS — ✅ выполнено 2026-10-18
Требуемое состояние (публичный рецепт — `mikrotik-setup.md` §3.5/§3.6):
```routers
/ip pool set dhcp ranges=10-229,231-239,241-254     # .230 (ingress) и .240 (API) не выдаются
/ip dns static add name=demo-ai-lab.ru address=192.168.10.230
/ip dns static add name="^(.*)\\.demo-ai-lab\\.ru$" address=192.168.10.230 regexp=true
```
Приёмка (проверено):
```bash
dig +short @192.168.10.1 demo-ai-lab.ru api.demo-ai-lab.ru   # оба → 192.168.10.230
```
- DHCP-пул не отдаёт `.230/.240` (lease-резерв без MAC RouterOS отвергает, REST-создание
  lease заблокировано — резерв **только пулом**);
- wildcard в `dns static` — только `regexp` (имя `*.домен` RouterOS читает как литерал);
- ⚠️ правка lease через REST `PUT` = полная замена (неполученные поля стираются) —
  только `PATCH` полным набором и проверка `address == active-address` (`mikrotik-setup.md` §3.5).

### E4 — Ingress на `.230` — ⏳ частично 2026-10-19 (LAN-сторона принята, сквозной путь — за E5)
F7/F8 в инсталл-спеке выполнены 2026-10-19: слушатель на `.230` есть.
**Принято (периметр/LAN, 2026-10-19):**
- `.230` ровно на одном узле пары (ip addr), ARP отвечает (ip neigh с соседа), split-DNS
  из LAN резолвит на `.230` (E3);
- `curl http://192.168.10.230/` (Host `echo.demo-ai-lab.ru`, тестовый ingress) — **200 от
  Higress** (`server: istio-envoy`), не connection refused;
- отказоустойчивость: увод LB-инстанса с держателя → `.230` переехал на второй узел пары,
  трафик без потерь; drill «мастер down» — ingress 200 всё время.
**Не принято:** сквозной внешний путь (edge→туннель→`.230`→ingress→200) и `tcpdump`-проверка
«не на .253». Причина — **uplink площадки, а не контур**: соединения коннекторов к edge
рвутся волнами в обоих протоколах — QUIC (`datagram manager timeout`) и TCP/http2
(`connection with edge closed` ~каждые 2–3 мин, при этом connIndex не поднимается выше 0);
edge то отдаёт 502 (сессию видит, origin http живой — ответ штатный), то 1033
(tunnel: no active connections — все сессии в данном PoP мертвы). На 02/03 оставлен
drop-in `--protocol http2` (соединения чаще переживают шторм, чем QUIC); полноценная
приёмка сквозного пути — при стабильном uplink (утром/другое время окна) и после E5.
Публичные проверки с консоли искажаются системным DNS (ZTN `10.69.99.1` отдаёт залежалую
запись старой площадки — «200 openresty без cf-ray» это НЕ наш край;
см. skill `demo-ai-lab-stand`); проверять только `dig @1.1.1.1` + `curl --resolve`.
Бывший «отдельный ingress-план» отменён владельцем: механизм (kube-vip LB-инстанс pool
`.230` + Higress-gateway standalone на 02/03) теперь ставится в `k8s-install-spec.md`
**F7/F8** (конфликт ADR-0001 закрыт рев. 3 — standalone). Здесь E4 остаётся **периметровой
приёмкой** того, что F7/F8 дали слушателя и внешний путь сквозной.

### E5 — TLS Full strict + переезд tunnel-ingress — ⏳ ждёт Cloudflare API-токена
> **Блокер 2026-10-19:** prerequisites F5 (cert-manager) и E4-LAN сделаны, но нет
> **Cloudflare API-токена с правом `DNS:Edit`** — его нет ни в `inventory.local.md`, ни
> в ключейке/macOS vault. Без токена невозможны: Secret `cert-manager/cloudflare-api-token`
> → Ready ClusterIssuer → выпуск LE wildcard → Higress :443 → переезд tunnel-ingress на
> `https://.230` + `--origin-ca-pool` → режим зоны Full (strict) → снятие legacy-NAT.
> Нужен одноразовый токен (Zero Trust → API Tokens, шаблон «Edit zone DNS», зона demo-ai-lab.ru);
> положить в `inventory.local.md`, в git не коммитить.
cert-manager (F5 спеки установки) выпускает LE wildcard `*.demo-ai-lab.ru` DNS-01
(solver cloudflare, API-токен с правом `DNS:Edit` — в Secret, не в git; ClusterIssuer
`letsencrypt-wildcard` — плейсхолдер F5 заполняется здесь). Далее: Higress :443 с этим
сертом, режим зоны **Full (strict)**, у коннекторов `TUNNEL_ARGS --origin-ca-pool /etc/cloudflared/isrg-root-x1.pem`,
tunnel-ingress → `https://192.168.10.230`.
Приёмка:
```bash
curl -sSI --resolve demo-ai-lab.ru:443:192.168.10.230 https://demo-ai-lab.ru/   # из LAN: цепочка Let's Encrypt/ISRG, не Cloudflare-origin
curl -sSI https://demo-ai-lab.ru                                               # через edge: HTTP/2 200, не 525/526
```
- legacy-NAT dstnat WAN tcp 80/443→`.253` — **отключить** (единственный вход — Cloudflare);
- 525/526 от edge (ORIGIN_NOT_ALLOWED / SSL_ERROR) — strict не настроен, не годится.

### E6 — Cloudflare Access (опция, не блок приёмки)
Access-политика на демо-хостнеймы (email-otp), чтобы сырое демо не индексировалось.
Приёмка: без сессии Access — 403 от Cloudflare до origin; с сессией — сквозной 200.

## 4. Общий health-gate контура (E-приёмка)

```bash
dig +short NS demo-ai-lab.ru @1.1.1.1                     # NS Cloudflare
dig +short demo-ai-lab.ru                                  # anycast Cloudflare, не IP площадки
dig +short @192.168.10.1 demo-ai-lab.ru                    # LAN → .230
curl -sSI https://demo-ai-lab.ru                           # edge → 200 (после E4/E5)
# Cloudflare API: туннель healthy, 2 коннектора active-active
# grep -R по ответам/заголовкам публичных страниц: IP площадки не встречается
```
Сценарии деградации (прогонять после изменений):
1. `systemctl stop cloudflared` на 02 → внешний путь жив через 03 (edge переключает без DNS);
2. обрыв WAN → LAN-путь через `.230` жив (split-horizon не зависит от Cloudflare);
3. `systemctl stop higress`/ребут узла пары → `.230` переезжает на второй узел пары, DNS не трогается.

## 5. Риски и грабли

- **Public IP площадки — [confidential]**: в наружу идёт только anycast Cloudflare; в доках/логах
  наружные IP не печатать (фильтр AGENTS.md). Публичное имя `demo-ai-lab.ru` — публиковать можно.
- 530/502 на edge до E4 — норма (origin не слушает); не «чинить туннель».
- QUIC-шторм коннекторов после сетевых ребундов — рестарт сервиса + контроль connIndex (E2).
- RouterOS: `PUT` стирает поля lease; wildcard-DNS только regexp; `lease add` без MAC/GET-создание
  заблокированы — резерв адресов только пулом; DUID-грабля при переустановке узла — `k8s-install-spec.md` §9.
- Free-план Cloudflare: лимиты по запросам достаточны для демо; Access на 50 пользователей free;
  DNSSEC на зоне не включать (нет DS у регистратора).
- Смена NS обратно/миграция регистратора — вне планов; при смене NS помнить TTL-окно.

## 6. Связанные документы

- `adr/adr-0004-external-access-cloudflare-tunnel.md` — решение и ревизия TLS (Full strict).
- `architecture/k8s-install-spec.md` §10 — кластерные соседи (VIP `.230`/.240, cert-manager F5, guard-план).
- `mikrotik-setup.md` §3.5/§3.6 — публичный рецепт роутера (плейсхолдеры секретов).
- `network-map-detail.md`, `architecture/ARCHITECTURE.md` §6.2 — карта и периметр.
- Скилл-памятка процесса (для агентов): `cloudflare-dns-tunnel`.

История версий:
- **v1.2** (2026-10-19, ночь): F7/F8 сделаны — слушатель `.230` жив (LAN-приёмка E4
  пройдена: Higress 200 через VIP, ARP, переезд VIP без потерь, drill мастера — ingress 200).
  Сквозной внешний путь не принят: edge 502 (tunnel-ingress ещё `http://`, коннекторы
  штормили QUIC — на 02/03 поставлен drop-in `--protocol http2`). E5 уточнён: блокеры —
  Cloudflare API-токен (`DNS:Edit`, в инвентаре его нет) и связанные шаги (сертификат,
  Full strict, caPool, снятие legacy-NAT). Проверка края с консоли — только
  `dig @1.1.1.1`/`--resolve` на CF-anycast (ZTN-DNS врёт).
- **v1** (2026-10-19): выделено из `k8s-install-spec.md` §10; E1–E3 выполнены 2026-10-18,
  E4/E5 заблокированы ingress-планом/F5.
- **v1.1** (2026-10-19): ingress-план отменён владельцем — механизм E4 переехал в
  `k8s-install-spec.md` F7/F8 (Higress standalone, ADR-0001 рев. 3); E4 = периметровая
  приёмка; E5 ждёт F5 (cert-manager) + F8 (Higress).