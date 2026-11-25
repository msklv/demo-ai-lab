# MikroTik — эталонная конфигурация сетевой части стенда

> Рецепт для повторения: шлюз LAN `192.168.10.0/24`, LAG до коммутатора, NAT, ingress-VIP `.230`,
> изоляция от сети площадки, Wi-Fi. Сверено на живом стенде (`gw-demo-ai-lab`, RouterOS **7.25.1**,
> 2026-11-19): REST + SSH `print` для порядка правил (`.id` в REST — порядок **создания**, не
> исполнения). Секретов (admin, PSK, MAC, адреса uplink) здесь нет — свои значения в разделе 5.
> Карта сети — `network/map.md`.

## 1. Железо

| Компонент | Модель / версия |
|---|---|
| Роутер | MikroTik L009UiGS-2HaxD (RouterBOARD ipq5000) |
| RouterOS | **7.25.1** (обновлён 2026-11-19) + RouterBOARD firmware **7.24.5** — upgrade до 7.25.1 доступен: `/system routerboard upgrade` + перезагрузка |
| Коммутатор | Tenda TEM2010X (8 × 2.5 Гбит/с + 2 × SFP+), статическая агрегация портов 7–8 (без LACP) |
| Узлы | 5× GMKtec mini-PC (`k8s-01…05`) за коммутатором, порты 1–6 |

## 2. Схема

- `ether1` — **WAN** (uplink площадки, адрес по DHCP; свои адреса не публикуем);
- `bridge` — LAN `192.168.10.1/24`; порты: `ether2–ether6`, `sfp1`, `wifi1`, `bond1`;
- `bond1` = `ether7`+`ether8` (`balance-xor`) → коммутатор, порты 7–8; ноды и консоль — за
  коммутатором/по Wi-Fi; backend `10.20.20.0/26` — на вторых интерфейсах нод, роутер вне её.

## 3. Пошаговая настройка (Terminal/Winbox, стиль `/export`)

### 3.1 Базовое

```
/system identity set name=gw-demo-ai-lab
# Сразу сменить пароль admin:  /user set admin password=<STRONG_PASSWORD>
```

### 3.2 Мост и адрес

```
/interface bridge add name=bridge comment=defconf
/ip address add address=192.168.10.1/24 interface=bridge comment=HomeLan
```

### 3.3 LAG до коммутатора

```
/interface bonding add name=bond1 slaves=ether7,ether8 mode=balance-xor \
    transmit-hash-policy=layer-2 comment="LAG -> switch ports 7-8"
```

Параллельно на L2-коммутаторе создайте **статическую** агрегацию портов 7–8
(без LACP — режим на обеих сторонах должен совпадать). Порты 1–6 — ноды.

### 3.4 Порты бриджа (`ether7/ether8` НЕ добавлять — они слейвы `bond1`)

```
/interface bridge port add bridge=bridge interface=ether2 comment=defconf
/interface bridge port add bridge=bridge interface=ether3 comment=defconf
/interface bridge port add bridge=bridge interface=ether4 comment=defconf
/interface bridge port add bridge=bridge interface=ether5 comment=defconf
/interface bridge port add bridge=bridge interface=ether6 comment=defconf
/interface bridge port add bridge=bridge interface=sfp1 comment=defconf
/interface bridge port add bridge=bridge interface=wifi1 comment=defconf
/interface bridge port add bridge=bridge interface=bond1 comment=defconf
```

### 3.5 DHCP и DNS

```
# .240 и .230 намеренно вне пула — VIP'ы kube-vip (держатся через ARP): .240 = API
# control-plane (ADR-0003), .230 = ingress-VIP пары 02/03 (ADR-0004, спека §10); DHCP не
# должен выдавать ни один. Резерв делается ИМЕННО пулом: lease без mac-address/client-id
# RouterOS отвергает, а REST-добавление lease заблокировано.
/ip pool add name=dhcp ranges=192.168.10.10-192.168.10.229,192.168.10.231-192.168.10.239,192.168.10.241-192.168.10.254
/ip dhcp-server add name=defconf interface=bridge address-pool=dhcp lease-time=1h10m
/ip dhcp-server network add address=192.168.10.0/24 gateway=192.168.10.1 dns-server=192.168.10.1 comment=defconf
/ip dns set servers=8.8.8.8,1.1.1.1 allow-remote-requests=yes
# ⚠️ В /ip dns рядом со статическими видно `dynamic-servers` — адрес uplink-роутера, который
#    приходит от DHCP-клиента на ether1 (проверено 2026-11-18). Если резолвить нужно ТОЛЬКО
#    через свои серверы: /ip dns set use-dynamic-servers=no
/ip dns static add name=router.lan address=192.168.10.1 comment=defconf
# split-DNS стенда (LAN/Wi-Fi резолвят сервисы напрямую на ingress-VIP, минуя WAN):
# ⚠️ имя "*.domain" в dns static — НЕ wildcard (литеральное имя); wildcard делается
#    ТОЛЬКО полем regexp (точка экранируется):
/ip dns static add name=demo-ai-lab.ru address=192.168.10.230 comment="split-DNS -> ingress-VIP"
/ip dns static add regexp="(.*)\\.demo-ai-lab\\.ru" address=192.168.10.230 comment="split-DNS wildcard -> ingress-VIP"
# ⚠️ AAAA закрывается отдельно: A-записи перекрывают только A, а AAAA уходит в публичный резолвер
#    (адрес внешней VM) — клиент с IPv6-предпочтением идёт наружу мимо .230. IPv6 на стенде нет:
/ip dns static add name=demo-ai-lab.ru type=AAAA address=::1 comment="no IPv6 on stand (AAAA -> loopback)"
/ip dns static add regexp="(.*)[.]demo-ai-lab[.]ru" type=AAAA address=::1 comment="no IPv6 on stand (AAAA -> loopback; wildcard)"
#    `address=::` и полная форма `0:0:0:0:0:0:0:0` отвергаются (7.24.5, `bad AAAA data`); в wildcard
#    точку писать `[.]`, а не `\.`; добавление — только по SSH (`POST /rest/ip/dns/static` → 400).
# Приёмка: dig +short @192.168.10.1 demo-ai-lab.ru A → .230; <host>.demo-ai-lab.ru AAAA → ::1

```

Резервирование адресов нод: дождаться лизинга ноды и `/ip dhcp-server lease make-static`
(значения MAC/client-id — приватные, в репо не публикуются). Консоль — так же: статик-лиз **внутри
пула** (пулом выводят только VIP `.230/.240`, у которых MAC нет). На 18.11.2026 статик-лизов
восемь: пять нод `.250–.254`, два Mac — `.200` (`host-name=Mac`) и `.188` (`Mac console en7`,
preload registry host), и IP-KVM `.10`.
⚠️ RouterOS матчит лиз по **client-id** (Ubuntu шлёт DUID от `machine-id`) — после переустановки
ОС резервация перестаёт работать; лечится обновлением `client-id`, а не удалением записи. macOS
с «Private Wi-Fi Address» меняет client-id сам — для консоли рандомизацию выключить. `PUT` по
lease выжигает `address`/`server`/`mac-address` (поломка видна на следующем ребайнде) — только
`PATCH`, приёмка: `address == active-address`; создание lease по REST заблокировано.

### 3.6 NAT

```
/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade comment="defconf: masquerade"

# Прямой входящий на ingress-VIP (включено 2026-10-28 по команде владельца).
# Правило живёт в конфиге с 2026-10-12 (тогда — to-addresses=192.168.10.253, узел k8s-02),
# с 2026-10-19 по 2026-10-28 было disabled=yes.
/ip firewall nat add chain=dstnat in-interface-list=WAN protocol=tcp dst-port=80,443 \
    action=dst-nat to-addresses=192.168.10.230 \
    comment="port-forward: WAN 80/443 -> ingress-VIP .230 (Higress, 02/03)"

# ОБЯЗАТЕЛЬНЫЙ спутник dstnat: возвратный путь. Ставится ПЕРЕД правилом изоляции
# (isolate: stand LAN -> uplink, см. 3.7), иначе ответы VIP клиентам из uplink режутся:
# SYN доходит, VIP отвечает, клиент видит таймаут (conntrack: syn-recv, orig 1 / repl 7).
/ip firewall filter add chain=forward action=accept in-interface-list=LAN \
    dst-address=<uplink-subnet> connection-nat-state=dstnat \
    comment="port-forward: return path ingress-VIP -> uplink clients"
```

**Приёмка (2026-10-28):** с хоста в uplink-сети на WAN-адрес роутера `:80`/`:443` отвечают 200
(`auth.` → 302, серт LE `CN=demo-ai-lab.ru`), счётчик `dstnat` растёт по входящим. **Снаружи путь по адресу площадки
не публикуется:** публичный адрес держит аплинк-роутер площадки. Внешний вход — `haproxy` на
внешней VM → SSH-hop 02/03 → `.230` → Higress (ADR-0004, рев. 2026-11-05), входящий NAT 80/443
открыт только с адреса VM.

Доступ к uplink-хосту для пробы — **временным** accept перед изоляцией (`src=<консоль>`,
`dst=<uplink-host>`, `tcp:22`); после теста удалить, иначе остаётся дырка LAN→площадка.

### 3.7 Firewall — порядок правил важен

**Правила исполняются сверху вниз**, первое совпадение завершает цепочку (кроме `passthrough`);
mangle — раньше filter; `fasttrack-connection` выводит соединение из остатка forward
([Firewall](https://help.mikrotik.com/docs/spaces/ROS/pages/250708066/Firewall),
[Packet Flow](https://help.mikrotik.com/docs/spaces/ROS/pages/328227/Packet+Flow+in+RouterOS)).
Фактический порядок снят по SSH `/ip firewall filter print without-paging` (7.25.1, 2026-11-19):
⚠️ `.id` из REST — порядок **создания**. `LAN` = `bridge`, `WAN` = `ether1`.

**input** (6 правил, в порядке исполнения):

| # | Правило | Замечание |
|---|---|---|
| 1 | accept `established,related,untracked` | сначала быстрые состояния |
| 2 | drop `invalid` | |
| 3 | accept `tcp/8728` `in-interface=bridge` («API - local») | ограничено бриджем — поэтому безопасно стоять выше drop; снимите `in-interface=bridge`, и API уедет наружу |
| 4 | accept `dst-address=127.0.0.1` (CAPsMAN) | |
| 5 | accept `protocol=icmp` | **переставлено 2026-11-19**: было последним, после drop — из-за этого ICMP с WAN не отвечал |
| 6 | **drop `in-interface-list=!LAN`** | главная защита WAN; всё, что ниже в этой цепочке, для не-LAN уже не исполняется |

**forward** (10 правил, в порядке исполнения; до 2026-11-19 было 12 — сняты «Web 443» и «Web 80»):

| # | Правило | Замечание |
|---|---|---|
| 1 | `passthrough` «special dummy rule» | косметика: на ней видны счётчики fasttrack. Пропускает пакет дальше |
| 2 | **accept `connection-nat-state=dstnat`** `in-interface-list=LAN` `dst-address=<uplink-subnet>` | **возвратный путь проброса** (§3.6): именно это правило спасает ответы ingress-VIP клиентам uplink |
| 3 | **drop `dst-address=<uplink-subnet>`** `in-interface-list=LAN` `out-interface-list=WAN` | изоляция стенда от сети площадки. Стоит **сразу после** возвратного пути — в этом и весь смысл порядка |
| 4–5 | accept ipsec-политик in/out | |
| 6 | `fasttrack-connection` `established,related` | совпавшее соединение дальше по forward не идёт; поэтому правила 1–5 «видят» трафик, а 7+ для fasttrack'нутых — нет |
| 7 | accept `established,related,untracked` | |
| 8 | accept `udp/5353` `224.0.0.251` in/out `bridge` (mDNS) | |
| 9 | drop `invalid` | после accept №7 — безопасно: invalid не совпадает с established |
| 10 | **drop `new` из WAN при `connection-nat-state=!dstnat`** | пробросы проходят: у них `dstnat`; это единственное WAN-правило, которое нужно |

**Что следует.** Возвратный путь (№2) выше изоляции (№3) — требование §3.6 выполнено порядком.
Изоляция выше `fasttrack`/`established`: LAN→uplink режется и для установленных соединений, кроме
dstnat-ответов (правило №2). `raw`/`mangle` — только заглушки для счётчиков fasttrack.
«Web 443»/«Web 80» сняты 2026-11-19 (проброс от них не зависел); ICMP поднят выше drop; в filter
16 правил вместо 18.

### 3.8 Wi-Fi (встроенный AP)

```
/interface wifi security add name=sec1 authentication-types=wpa2-psk,wpa3-psk passphrase=<YOUR_WIFI_PSK>
/interface wifi set wifi1 configuration.mode=ap configuration.ssid=<YOUR_SSID> \
    configuration.country=<YOUR_COUNTRY_CODE> security=sec1
```

SSID и PSK демо-сети — публичные: SSID — бренд конференции, PSK — в `README.md` («Подключение»),
источник значения — `inventory.local.md`; после мероприятия PSK меняется.
Country code: для РФ — `ru` (в живом стенде стоял `us` — для 2.4GHz это не критично, но
ставится код своей страны).

### 3.9 Службы управления (только LAN)

Включены: `ssh` (22), `www` (8080, REST), `winbox` (8291), `api` (8728), `api-ssl` (8729).
Выключены: `ftp`, `telnet`, `www-ssl` (443 занят пробросом), `reverse-proxy`. Снаружи всё закрыто
правилом «drop не из LAN» (а `api` — ещё и «API - local», см. 3.7); `btest`/`detnet`/`ntp`/`dhcp`/
`resolver`/`discover` — служебные юниты RouterOS, тем же правилом не видны.

### 3.10 Облако — выключить полностью

`/ip/cloud` `ddns-enabled=auto` = DDNS только при включённом Back To Home, а он
`revoked-and-disabled` — фактически выключен (`update-time` пуст, имя резолвится NXDOMAIN).

## 4. Значения, которые не выводятся из §3 (проверено 2026-11-18, REST + SSH)

| Параметр | Значение |
|---|---|
| DNS апстрим | `8.8.8.8,1.1.1.1` + `dynamic-servers` от uplink (192.168.3.x) — гасится `use-dynamic-servers=no` |
| DHCP-резервации | 8 static, все внутри пула: `k8s-01 .250`, `k8s-05 .251`, `k8s-04 .252`, `k8s-02 .253`, `k8s-03 .254`, Mac `.200`, Mac console en7 `.188`, IP-KVM `.10` (проверено 2026-11-18). ⚠️ REST 7.24 отдаёт связанный лизинг через `active-address`, поле `address` у него пустое — аудиторским скриптам читать оба |
| dstnat | WAN tcp `80,443` → **`192.168.10.230`** (ingress-VIP) — включено 2026-10-28 |

Остальные значения (pool, split-DNS, LAG, службы, cloud) — в §3.

## 5. Чек-лист «замени под себя» (обязательно)

- [ ] пароль `admin` — сменить сразу после установки
- [ ] Wi-Fi PSK (`passphrase`)
- [ ] SSID (публичный — можно оставить брендовый)
- [ ] country code Wi-Fi (`ru` для РФ)
- [ ] сеть uplink в правиле изоляции (`<uplink-subnet>`) — свои адреса не публиковать
- [ ] MAC нод при DHCP-резервации — в открытые доки не выносить
- [ ] public IP / публичные DNS-имена — не фиксировать в публичных доках

## 6. Управление и чтение

- Чтение — REST `http://192.168.10.1:8080/rest/...` (основное), SSH (22) — разовые команды;
  Winbox (8291), API (8728) — вспомогательные. Изменения делает владелец через UI.
- ⚠️ REST: `PUT` = полная замена записи (лишние поля сбрасываются — PUT пула переименовал `dhcp`
  в `pool0`), точечно — `PATCH`; `POST` в `ip/dhcp-server/lease` и `ip/dns/static` не работает
  (только SSH). Wildcard в `ip dns static` — только `regexp`; имя `"*.домен"` — литерал.

См. также: `network/map.md` (карта сети), `architecture/ARCHITECTURE.md`,
`adr/adr-0001-higress-as-sole-ingress.md`.