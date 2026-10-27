# MikroTik — эталонная конфигурация сетевой части стенда

> Готовый рецепт для повторения: шлюз демо-ЛВС (`192.168.10.0/24`), LAG до коммутатора,
> NAT в интернет площадки, маршрутизация сервисов через ingress-VIP `.230` и Higress, изоляция
> стенда от сети площадки, Wi-Fi для аудитории.
> Снято живьём с рабочего стенда (identity `gw-demo-ai-lab`, RouterOS **7.24.5**). Полная
> сверка с живым конфигом через REST: **2026-10-18** (разделы 3.5–3.10 и таблицы 3.7
> соответствуют правилам роутера по `.id`, включая порядок). Секреты (пароль admin,
> Wi-Fi PSK, MAC, адреса uplink) в этом документе НЕ публикуются — подставьте свои (раздел 5).
> Актуальная карта сети: `network-map-detail.md`.

## 1. Железо

| Компонент | Модель / версия |
|---|---|
| Роутер | MikroTik L009UiGS-2HaxD (RouterBOARD ipq5000) |
| RouterOS | 7.24.5 + firmware 7.24.5 |
| Коммутатор | L2 (Tenda), **статическая** агрегация портов 7–8 (без LACP) |
| Узлы | 4× GMKtec mini-PC на портах 1–6 коммутатора |

## 2. Схема

- `ether1` = **WAN** (uplink площадки, адрес по DHCP — свои адреса не публикуем);
- `bridge` = LAN `192.168.10.1/24`; порты бриджа: `ether2–ether6`, `sfp1`, `wifi1`, `bond1`;
- `bond1` = `ether7` + `ether8`, mode `balance-xor` → коммутатор (порты 7–8);
- ноды и консоль — за коммутатором / по Wi-Fi; backend-сеть `10.20.20.0/26` — на вторых
  интерфейсах нод, роутер в неё не входит;
- Wi-Fi — встроенный AP в бридже.

## 3. Пошаговая настройка (Terminal/Winbox, стиль `/export`)

### 3.1 Базовое

```
/system identity set name=gw-demo-ai-lab
# Сразу сменить пароль admin:  /user set admin password=<STRONG_PASSWORD>
```

### 3.2 Мост и адрес

```
/interface bridge add name=bridge comment=defconf
/ip address add address=192.168.10.1/24 interface=bridge comment="LAN demo"
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
/ip dns static add name=router.lan address=192.168.10.1 comment=defconf
# split-DNS стенда (LAN/Wi-Fi резолвят сервисы напрямую на ingress-VIP, минуя WAN):
# ⚠️ имя "*.domain" в dns static — НЕ wildcard (литеральное имя); wildcard делается
#    ТОЛЬКО полем regexp (точка экранируется):
/ip dns static add name=demo-ai-lab.ru address=192.168.10.230 comment="split-DNS -> ingress-VIP"
/ip dns static add regexp="(.*)\\.demo-ai-lab\\.ru" address=192.168.10.230 comment="split-DNS wildcard -> ingress-VIP"
# ⚠️ AAAA закрывается ОТДЕЛЬНО: A-записи выше перекрывают только A, а AAAA уходит в публичный
#    резолвер (`servers=8.8.8.8,1.1.1.1` в /ip dns set) и возвращает anycast Cloudflare (2606:4700:…).
#    Клиент с IPv6-предпочтением (iPhone/Android/Linux-браузер: happy eyeballs) уходит из LAN
#    в Cloudflare, а не на .230 — «в локальной сети трафик идёт наружу». IPv6 на стенде нет ни на
#    одном узле, поэтому правильный ответ — мёртвый loopback-адрес:
/ip dns static add name=demo-ai-lab.ru type=AAAA address=::1 comment="no IPv6 on stand (AAAA -> loopback)"
/ip dns static add regexp="(.*)[.]demo-ai-lab[.]ru" type=AAAA address=::1 comment="no IPv6 on stand (AAAA -> loopback; wildcard)"
# Грабля (проверено 2026-10-27 на 7.24.5): `address=::` и полная форма `0:0:0:0:0:0:0:0`
#    ОТВЕРГАЮТСЯ — `failure: bad AAAA data: IPv6 address expected`; принимаются `::1`, `fd00::1`,
#    `2001:db8::1`. Берём `::1`: connect падает на loopback за <1 мс, клиент сразу идёт на A=.230.
#    В wildcard-записи точку писать классом `[.]`, а не `\.` — экранирование в CLI съедается
#    (`expected regexp value`). Добавление — только SSH: `POST /rest/ip/dns/static` → 400.
# Приёмка (apex и wildcard):
#    dig +short @192.168.10.1 demo-ai-lab.ru     A    → 192.168.10.230
#    dig +short @192.168.10.1 owu.demo-ai-lab.ru AAAA → ::1   (ни одного 2606:4700:…)
#    с клиента: getent ahosts owu.demo-ai-lab.ru → ::1 + 192.168.10.230, адресов Cloudflare нет

```

Резервирование адресов нод: дождаться лизинга ноды и `/ip dhcp-server lease make-static`
(значения MAC/client-id — приватные, в репо не публикуются). Консоль — так же: статик-лиз
`192.168.10.188`, адрес намеренно внутри пула (его держит сам лиз с MAC; пулом выводят только
VIP `.230/.240`, у которых MAC нет). ⚠️ Грабля (2026-10-17):
RouterOS матчит лизинг по **client-id**, Ubuntu 24.04 шлёт DUID от `machine-id` — после
переустановки ОС статик-запись перестаёт срабатывать (узел получает динамический адрес);
лечится обновлением `client-id` в static-записи, а не удалением резервации. Вторая грабля
(2026-10-18): PUT-регенерация lease выжигает поля `address`/`server`/`mac-address` — запись
пропадает из UI, а резервация молча перестаёт работать (узел получает адрес из пула, эффект
виден только на следующем ребайнде). Лечение: PATCH полным набором полей; приёмка — `address`
совпадает с `active-address` у всех нод. Создание нового lease по REST по-прежнему заблокировано.

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

**Что проверено живьём (2026-10-28).** С хоста в uplink-сети (`<uplink-host>`) на WAN-адрес роутера
(`<wan-ip>`), т.е. заведомо «снаружи» для dstnat:

| имя | :80 | :443 |
|---|---|---|
| `demo-ai-lab.ru` | 200 | 200 |
| `api.demo-ai-lab.ru` | 200 | 200 |
| `argo.demo-ai-lab.ru` | 200 | 200 |
| `hgc.demo-ai-lab.ru` | 200 | 200 |
| `auth.demo-ai-lab.ru` | 302 (Keycloak) | 302 |

Серт на `:443` — Let's Encrypt `CN=demo-ai-lab.ru`; бандл 3.9 MB с `api` отдаётся за 0.09 с (~45 MB/с),
т.е. MTU/потери на пути не мешают. Счётчики: `dstnat` растёт по входящим, правило возвратного пути —
по ответам (≈3.5 ответа на 1 запрос). Изоляция LAN→uplink при этом сохраняется: с консоли стенда
`<uplink-host>`, `<uplink-neighbour>` по `443` по-прежнему закрыты.

Как тестировать в следующий раз: консоль стенда в uplink не ходит (изоляция), поэтому доступ к
uplink-хосту даётся **временным** accept-правилом перед изоляцией (`src=<консоль>`,
`dst=<uplink-host>`, `tcp:22`, `place-before=<isolate>`); после теста правило удаляется — иначе в
конфиге остаётся незаметная дырка из LAN в сеть площадки.

**Снаружи (из интернета) путь пока НЕ работает** — и это не роутер: публичный адрес держит
аплинк-роутер площадки (`:80` → `301` на https, `:443` → TLS alert `unrecognized name`), на
`<wan-ip>` порты 80/443 не проброшены, счётчик `dstnat` при внешней пробе остаётся 0. Нужен проброс
`80/443 → <wan-ip>` на стороне площадки.

**Риск (осознанно принят владельцем):** прямой вход обходит Cloudflare — для внешних клиентов нет
WAF/Access, а публичный адрес origin'а становится виден. Рабочий внешний путь остаётся прежним:
Cloudflare Tunnel → `.230` → Higress (ADR-0004, external-access E5).

### 3.7 Firewall — порядок правил важен

**input** (фактический порядок по `.id` живого роутера):

| # | Правило |
|---|---|
| 1 | accept `established,related,untracked` |
| 2 | drop `invalid` |
| 3 | accept `icmp` |
| 4 | accept to `127.0.0.1` (CAPsMAN) |
| 5 | **drop всё, что пришло не из LAN** (главная защита WAN-интерфейса) |
| 6 | accept `tcp 8728` «API - local» — стоит ПОСЛЕ drop №5, поэтому допускает RouterOS API только из LAN (перенос выше drop открыл бы API наружу) |

**forward** (фактический порядок по `.id`; он и есть рабочий механизм):

| # | Правило |
|---|---|
| 1–2 | accept in/out `ipsec` policy |
| 3 | fasttrack-connection `established,related` |
| 4 | accept `established,related,untracked` |
| 5 | drop `invalid` |
| 6 | drop `new` из WAN с `connection-nat-state=!dstnat` — стоит ДО правил Web; пробросы проходят, т.к. у них `connection-nat-state=dstnat` |
| 7 | accept mDNS (`bridge`→`bridge`, `224.0.0.251:5353` udp) |
| 8 | accept tcp `443` из WAN (Web 443) |
| 8a | **accept `connection-nat-state=dstnat`** LAN → `<uplink-subnet>` — **возвратный путь проброса** (2026-10-28). Обязателен и обязан стоять ПЕРЕД изоляцией: без него ответы ingress-VIP клиентам uplink режет правило №9 |
| 9 | **drop LAN → `<uplink-subnet>`** (изоляция стенда от сети площадки) |
| 10 | accept tcp `80` из WAN (Web 80 → ingress) |
| 11 | passthrough-заглушка «show fasttrack counters» (косметика из Winbox, функционально ничего) |

> Правила №8/№10 (`accept tcp 443/80 из WAN`) создавались под проброс на `.253`. После его отключения
> (2026-10-19) они были инертны; с 2026-10-28 проброс включён (на `.230`) и они снова видят этот трафик,
> но остаются **избыточными**: dstnat-поток пропускает правило №6 (`connection-nat-state=!dstnat` его не
> матчит), а новый входящий не-dstnat с WAN режет то же правило №6 ещё до них.
> **Решение владельца 2026-10-24: правила снимаются** (в конфиге на 2026-10-28 они ещё есть — снятие
> через Winbox владельцем). В рецепте «с нуля» их не создаём.

### 3.8 Wi-Fi (встроенный AP)

```
/interface wifi security add name=sec1 authentication-types=wpa2-psk,wpa3-psk passphrase=<YOUR_WIFI_PSK>
/interface wifi set wifi1 configuration.mode=ap configuration.ssid=<YOUR_SSID> \
    configuration.country=<YOUR_COUNTRY_CODE> security=sec1
```

SSID — публичный (у нас — бренд конференции); PSK — только свой, в репо не кладём.
Country code: для РФ — `ru` (в живом стенде стоял `us` — для 2.4GHz это не критично, но
ставится код своей страны).

### 3.9 Службы управления (только LAN)

Оставить включёнными: `ssh` (22), `www` (8080, REST API), `winbox` (8291), `api` (8728),
`api-ssl` (8729). Отключить: `ftp` (21), `telnet` (23), `www-ssl` (443 — не нагружаем
порт, проброшенный на ingress), `reverse-proxy`. Все службы дополнительно закрыты
правилом «drop всё не из LAN» (а `api` — ещё и правилом «API - local» после него, см. 3.7).
Прочие активные записи в списке служб (`btest`, `detnet`, `ntp`, `dhcp`, `resolver`,
`discover`) — встроенные служебные юниты RouterOS, наружи не видны тем же правилом drop.

### 3.10 Облако — выключить полностью

`/ip/cloud` `ddns-enabled=auto`: в RouterOS 7.24 значение принимает только `yes`/`auto`,
где `auto` = DDNS живёт лишь при включённом Back To Home; он `revoked-and-disabled` —
значит DDNS фактически выключен (проверено: `update-time` пуст, публичное имя резолвится
NXDOMAIN у 8.8.8.8 и 1.1.1.1).

## 4. Ключевые значения (проверено живьём 2026-10-18, REST)

| Параметр | Значение |
|---|---|
| identity | `gw-demo-ai-lab` |
| LAN / шлюз | `192.168.10.1/24` (bridge) |
| DHCP pool | `192.168.10.10–.229,.231–.239,.241–.254` (`.240` = API-VIP, `.230` = ingress-VIP — не выдавать), lease `1h10m`, DNS = `192.168.10.1` |
| split-DNS | `demo-ai-lab.ru` + regexp `(.*)\.demo-ai-lab\.ru` → `192.168.10.230` (ingress-VIP); публичная зона при необходимости — отдельно, RFC1918 в неё НЕ публикуется |
| DNS статик | `router.lan` → `192.168.10.1` |
| DHCP-резервации | 4 static bound (.250/.252/.253/.254) + консоль `.188` (внутри пула, держится лизом); ⚠️ REST 7.24 отдаёт связанный лизинг через `active-address`, поле `address` у него пустое — аудиторским скриптам читать оба |
| LAG | `bond1` = ether7+ether8, `balance-xor`, hash `layer-2` |
| srcnat | `masquerade` out WAN |
| dstnat | WAN tcp `80,443` → **`192.168.10.230`** (ingress-VIP, Higress 02/03) — **включено** (2026-10-28); адрес был `.253`, правило стояло disabled с 2026-10-19 |
| forward (проброс) | accept `in-interface-list=LAN` + `dst-address=<uplink-subnet>` + `connection-nat-state=dstnat` — возвратный путь проброса, стоит перед правилом изоляции (2026-10-28) |
| Wi-Fi | mode `ap`, 2.4GHz-n, wpa2-psk+wpa3-psk |
| Службы | ssh / www:8080 / winbox / api / api-ssl; ftp, telnet, www-ssl, reverse-proxy — off |
| Cloud | DDNS выключен, Back To Home revoked |

## 5. Чек-лист «замени под себя» (обязательно)

- [ ] пароль `admin` — сменить сразу после установки
- [ ] Wi-Fi PSK (`passphrase`)
- [ ] SSID (публичный — можно оставить брендовый)
- [ ] country code Wi-Fi (`ru` для РФ)
- [ ] сеть uplink в правиле изоляции (`<uplink-subnet>`) — свои адреса не публиковать
- [ ] MAC нод при DHCP-резервации — в открытые доки не выносить
- [ ] public IP / публичные DNS-имена — не фиксировать в публичных доках

## 6. Управление и чтение

- Каналы: Winbox (8291), REST (8080, основное чтение: `http://192.168.10.1:8080/rest/...`),
  SSH (22, разовые команды), API (8728). Изменения — через UI владельцем, не API.
- ⚠️ Кворки REST 7.24.5 (замерено 2026-10-18): добавление записей заблокировано у нескольких
  коллекций (`POST .../ip/dhcp-server/lease`, `.../ip/dns/static` → «no such command» — только
  SSH); **`PUT` = полная замена записи** — не указанные поля сбрасываются в дефолты
  (инцидент: PUT пула с одними ranges переименовал `dhcp` в `pool0`; чинится `PATCH`);
  `PATCH` — точечное обновление.
- ⚠️ Wildcard в `ip dns static` — только полем `regexp`, имя `"*.домен"` — литерал.

См. также: `network-map-detail.md` (карта сети), `architecture/ARCHITECTURE.md`,
`adr/adr-0001-higress-as-sole-ingress.md`.