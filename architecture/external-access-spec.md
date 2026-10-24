# Спецификация внешнего доступа стенда demo-ai-lab

> **Версия 1.5** (2026-10-24, ночь), статус: **E1–E5 + E7 выполнены**; сквозной внешний 200 идёт через
> **второй egress** — коннектор на внешней VM (SberCloud) + два SSH-проброса origin до `.230` (E7).
> Причина: с uplink площадки РФ-провайдер режет порт `7844` (TLS/QUIC до edge рвётся через минуты),
> с сети VM те же сессии стоят без разрывов — риск R1 переведён из «ждём погоды» в «обойдён».
> **E6 снят решением владельца 2026-10-24** — служебные сервисы живут только в LAN. Цель — `demo-ai-lab.ru` живёт снаружи
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
| Туннель | `demo-lab-ingress-v2` (remotely-managed; id волатилен — пересоздан 2026-10-23, в прозе не пинится: резолвится `env_health.py` из DNS CNAME / Cloudflare API) | ingress v3: apex+wildcard → `https://.230` + caPool (E5), с 2026-10-24 → `https://127.0.0.1:19443` (E7); **пересоздан 2026-10-23** (старый объект удалён — edge рвал соединения) |
| Коннекторы | **внешняя VM в SberCloud** (Ubuntu 24.04, 2 vCPU/4.1G, адрес — `inventory.local.md`), `cloudflared.service` + `--protocol http2 --origin-ca-pool`; на k8s-02/03 сервис **`disable --now`** | 2026-10-24: 4 соединения healthy, ротаций нет (E7). Стендовые коннекторы выведены: их сессии edge рвёт через 1–10 мин (DPI на `7844` в сети провайдера площадки), а общий ingress требует локального `127.0.0.1:19443`, которого на нодах нет |
| Origin | `192.168.10.230` — ingress-VIP пары 02/03 (ADR-0001; отдельный от API-VIP `.240`, **не склеивать**) | **E5 2026-10-19: `https://`** — Higress :443 на LE wildcard `demo-wildcard-tls`; с 2026-10-24 коннектор идёт в origin через `https://127.0.0.1:19443` (HAProxy на VM) → SSH-hop на 02/03 → `.230:443` |
| Origin-leg (E7) | два SSH reverse-проброса `vmhop.service` (k8s-02 → `127.0.0.1:18443`, k8s-03 → `127.0.0.1:18444`) + `haproxy` на VM (`listen 127.0.0.1:19443`, mode tcp, `check inter 2s fall 2`) | работает 2026-10-24; TLS не терминируется (hop — TCP-пайп), SNI доходит до Higress, Full strict сохранён. Дрилл: stop `vmhop` на 02 → бэкенд DOWN за ~4 c, внешние ответы 200 через 03 |
| Split-horizon | MikroTik `dns static` + regexp → `.230` для LAN-клиентов | работает 2026-10-18 |
| Служебные хостнеймы | `argocd.*` и будущие админ-UI — **только LAN** (решение владельца 2026-10-24) | маршрутов в Higress нет → туннель отдаёт 404; в LAN доступны через split-DNS при появлении Ingress |
| legacy NAT | dstnat WAN tcp 80/443 → `.253` (историческое, 2026-10-12) | **отключено 2026-10-19 (E5)**: правило `*2` RouterOS `disabled=yes`, tcpdump на `.253` — ноль входящих 80/443 |

Не входит: содержимое ingress (Higress-маршруты, AI-плагины, guard-маршрут) — остаток
§10 инсталл-спеки / план демо; механизм `.230`+Higress — там же (F7/F8);
установка кластера — `k8s-install-spec.md`. Пины: cloudflared `2026.10.1` (deb-репо Cloudflare,
autoupdate выключён флагом), cert-manager `1.21.2` (F5 спеки установки — PKI-провижнер LE),
LE-цепочка ISRG Root X1.

## 2. Целевая схема (два пути, один origin)

```
Внешний зритель ──▶ Cloudflare edge (anycast, IP Cloudflare) ──TCP/7844 http2──▶ cloudflared (VM SberCloud)
                     demo-ai-lab.ru + *.demo-ai-lab.ru                                  │ https://127.0.0.1:19443
                                                                                        ▼
                          haproxy (VM, loopback)  ──check/2s──▶ 127.0.0.1:18444 (k8s-03)
                                     │                                  │ SSH -R
                                     └──────────────────────────▶ 127.0.0.1:18443 (k8s-02)
                                                                        │
LAN-зритель ──dig @192.168.10.1──▶ .230 ───────────────────────────▶ Higress-gateway (02/03)
```

- Наружу из uplink площадки теперь **не идёт вообще ничего** к Cloudflare: единственный «наружу»
  канал — SSH-сессии 02/03 → VM (TCP/22), tunnel-соединения на `7844` поднимает уже VM.
  Входящие по-прежнему не нужны нигде.
- Hop — чистый TCP-пайп: TLS не терминируется ни на VM, ни в SSH; origin-сертификат проверяет
  cloudflared по `ca-pool.pem`, SNI `demo-ai-lab.ru` доезжает до Higress → **Full strict сохранён**.
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
`https://192.168.10.230` + `originRequest.caPool` (v3, с E5 2026-10-19).
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

### E4 — Ingress на `.230` — ✅ принято 2026-10-19 (LAN + сквозной внешний путь)
F7/F8 в инсталл-спеке выполнены 2026-10-19: слушатель на `.230` есть.
**Принято (периметр/LAN, 2026-10-19):**
- `.230` ровно на одном узле пары (ip addr), ARP отвечает (ip neigh с соседа), split-DNS
  из LAN резолвит на `.230` (E3);
- `curl http://192.168.10.230/` (Host `echo.demo-ai-lab.ru`, тестовый ingress) — **200 от
  Higress** (`server: istio-envoy`), не connection refused;
- отказоустойчивость: увод LB-инстанса с держателя → `.230` переехал на второй узел пары,
  трафик без потерь; drill «мастер down» — ingress 200 всё время;
- **все затронутые поды Running** (критерий добавлен 2026-10-19 по команде владельца,
  синхронно с F9): higress-system/cert-manager/argocd — Running/Ready, чужих статусов нет
  (`kubectl get pods -A | grep -vE ' ([0-9]+)/\1 +(Running|Completed)'` пусто); коннекторы
  cloudflared на 02/03 — `systemctl is-active` = active.
**Сквозной внешний путь — принят 2026-10-19 после закрытия E5:**
- `curl --resolve echo.demo-ai-lab.ru:443:<CF-anycast> https://echo.demo-ai-lab.ru/` →
  **HTTP 200** через edge при живых коннекторах (Full strict: 200 из edge невозможен при
  непройденной origin-верификации); вход через legacy-NAT подтверждённо закрыт
  (`tcpdump -i eno1 'tcp and (dst port 80 or dst port 443) and dst host .253'` — 0 пакетов
  за 15 с при живом внешнем пути);
- внешняя приёмка независимо от egress площадки — check-host.net (~55 точек): инфраструктура
  проверок рабочая; в штормовые окна edge отвечает 530 со всех точек одновременно
  (нет ни одной живой сессии туннеля), в здоровые — 200.
**Остаток = операционный, риск R1 (uplink площадки, не контур):** соединения коннекторов к
edge рвутся волнами — QUIC (`datagram manager timeout`) и TCP/http2 (`connection with edge
closed`, ротация сессий каждые 5–7 мин, connIndex гаснет); при нуле сессий edge отдаёт
530/1034. На 02/03 оставлен drop-in `--protocol http2` (переживает шторм лучше QUIC) и
caPool; стабилизация канала — задача на аплинком-провайдера/время суток, мониторинг —
`GET /accounts/{acct}/cfd_tunnel/{tid}` (status=down при нуле сессий).
Публичные проверки с консоли искажаются системным DNS (ZTN `10.69.99.1` отдаёт залежалую
запись старой площадки — «200 openresty без cf-ray» это НЕ наш край;
см. skill `demo-ai-lab-stand`); проверять только `dig @1.1.1.1` + `curl --resolve`.
Бывший «отдельный ingress-план» отменён владельцем: механизм (kube-vip LB-инстанс pool
`.230` + Higress-gateway standalone на 02/03) теперь ставится в `k8s-install-spec.md`
**F7/F8** (конфликт ADR-0001 закрыт рев. 3 — standalone). Здесь E4 остаётся **периметровой
приёмкой** того, что F7/F8 дали слушателя и внешний путь сквозной.

### E5 — TLS Full strict + переезд tunnel-ingress — ✅ выполнено 2026-10-19
> **История блокера (снят 2026-10-19):** нужен был Cloudflare **custom-токен** — создан
> владельцем и положен строкой в `inventory.local.md` (gitignore): Account
> `Cloudflare Tunnel:Edit` + `Access: Apps and Policies:Edit`, Zone `demo-ai-lab.ru`
> `DNS:Edit` + `SSL and Certificates:Edit` + `Zone:Read`. Грабли токена: без Zone:Read
> функциональные вызовы отвечают `9109` при `verify=active`; `PATCH` zone setting`ов`
> требует `Content-Type: application/json` (форма → `6003`); TTL-окно «start date» в
> будущем ломает токен целиком. Скоупы и рецепты — skill `cloudflare-dns-tunnel`.
**Исполнено (цепочка целиком, 2026-10-19):**
1. Secret `cert-manager/cloudflare-api-token` (ключ `api-token`) → ClusterIssuer
   `letsencrypt-wildcard` Ready (`ACMEAccountRegistered`);
2. `Certificate demo-wildcard` (ns `demo-test`, dnsNames `demo-ai-lab.ru` + `*.demo-ai-lab.ru`,
   secret `demo-wildcard-tls`) — Ready, LE wildcard выпущен;
3. Higress :443 — ingress `echo` + apex-ingress на `demo-ai-lab.ru` с TLS-сертом; из LAN
   через `.230:443` — **200 с цепочкой ISRG** (не Cloudflare);
4. tunnel-ingress переведён API (`/accounts/{acct}/cfd_tunnel/{tid}/configurations`,
   PUT v3): apex+wildcard → `https://192.168.10.230`, `originRequest.caPoolPath=
   /etc/cloudflared/ca-pool.pem`, `noTLSVerify:false`, per-host `originServerName:
   demo-ai-lab.ru` (SNI на IP-literal origin); caPool (ISRG X1/X2 + YR + промежуточный)
   разложен на 02/03, drop-in cloudflared дополнен `--origin-ca-pool`;
5. режим зоны **Full (strict)** — `PATCH /zones/{zone}/settings/ssl {"value":"strict"}` OK;
6. **legacy-NAT снято**: RouterOS dstnat `*2` WAN 80/443→`.253` → `disabled=yes`
   (REST PATCH, чтение back: disabled=true; tcpdump на `.253` — 0 входящих 80/443).
**Приёмка:**
```bash
curl -sSI --resolve demo-ai-lab.ru:443:192.168.10.230 https://demo-ai-lab.ru/   # из LAN: цепочка Let's Encrypt/ISRG, не Cloudflare-origin  → 200 ✅
curl -sSI https://demo-ai-lab.ru                                               # через edge: HTTP/2 200, не 525/526  → 200 зафиксирован ✅ (окна шторма R1 дают 530 — см. E4 «остаток»)
```
- неизвестный SNI на `.230:443` → TLS-рукопожатие сбрасывается (reset), не 200 ✅;
- 525/526 от edge не наблюдались (strict работает: при неверной origin-цепочке 200 невозможен).
Что где живёт после E5: ClusterIssuer `letsencrypt-wildcard` и Secret
`cloudflare-api-token` — ns `cert-manager` (в gitops-каталоге); Certificate `demo-wildcard`
и ingress'ы `echo`/`apex` — ns `demo-test` (echo — **постоянный** тестовый маршрут, решение
владельца 2026-10-24: контейнер живёт всегда как smoke-проверка пути); caPool — `/etc/cloudflared/ca-pool.pem`
на 02/03 (не в git); Secret с токеном — только in-cluster + `inventory.local.md`.

### E6 — Cloudflare Access — ⛔ СНЯТ (решение владельца 2026-10-24)
**Не требуется:** все служебные хостнеймы (`argocd.*` и будущие админ-UI) нужны только в LAN,
наружу они не публикуются. Механика текущего состояния: туннель роутит любой валидный Ingress
диапазона `*.demo-ai-lab.ru`, поэтому «не публиковать» = **не заводить Ingress в Higress**
(сейчас у `argocd.*` его нет → edge отвечает 404). В LAN служебный сервис доступен через
split-DNS → `.230`, если для него заведён Ingress.
**Правило остаётся в силе на будущее:** если служебный маршрут всё же выставляется наружу —
Access-приложение на него заводится в тот же день (email-otp; для CLI/API — service token).
История: опция Access на демо-хостнеймы (чтобы сырое демо не индексировалось) рассматривалась,
приёмка была бы: без сессии — 403 от Cloudflare до origin, с сессией — сквозной 200.
> **Решение владельца 2026-10-19: начать с админ-хостнеймов** (argocd.demo-ai-lab.ru и
> будущие служебные), демо-публичные оставить без политики. Факты на 2026-10-19:
> в зоне **DNS wildcard** `*.demo-ai-lab.ru` (proxied) — любой поддомен резолвится, но
> ingress туннеля не роутит незаданные имена → **404 от cloudflare** (`argocd.*` уже
> недоступен извне — нет маршрута). Access накладывается в **момент маршрутизации** хостнейма
> (правило E6: «завёл ingress-правило на служебный хостнейм — Access-приложение в тот же
> день»). Access работает поверх текущего http-origin, ждать E5 не нужно; 502/1033 от
> uplink-шторма он не лечит (гейтит, а не транспортирует). Нюансы: UI Argo — WebSocket
> (после авторизации проходит); CLI/API автоматизации — service token / `cf_at` JWT,
> не email-otp. LAN-путь (split-DNS → `.230`) Access не закрывается — это не замена
> E5 и снятию legacy-NAT. Для API-провижининга в custom-токен добавить скоуп
> **Account → Access: Apps and Policies: Edit** + account id в инвентарь.

### E7 — Второй egress: коннектор на внешней VM + два SSH-hop — ✅ выполнено 2026-10-24
**Проблема.** С uplink площадки РФ-провайдер режет Cloudflare-туннель: сессии коннектора к `198.41.x:7844`
живут 1–10 мин и рвутся стороной edge (`connection with edge closed`), туннель уходит в `status=down,
соединений 0`, внешние запросы получают 530/1033 со всех точек мира. QUIC с этого канала не поднимается
вовсе (`timeout: no recent network activity`); при этом ICMP — 0% потерь, MTU 1472 проходит, обычный
`443` до Cloudflare тянет мегабайты. Диагноз подтверждён сообществом (cloudflared#1456) и экспериментом:
коннектор с VM в SberCloud на тех же DME-коло держит соединения без единой ротации.

**Схема.** Коннектор переехал на внешнюю VM; origin до `.230` доводится SSH-пробросами.

| Слой | Что именно |
|---|---|
| Edge-нога | `cloudflared` (deb-репозиторий/github, `2026.10.3`) на VM как `cloudflared.service`, `EnvironmentFile=/etc/cloudflared/token.env` (600), `tunnel run --protocol http2 --origin-ca-pool /etc/cloudflared/ca-pool.pem`, `Restart=always/5` |
| Origin-нога | `vmhop.service` на k8s-02 (`-R 127.0.0.1:18443:192.168.10.230:443`) и на k8s-03 (`-R 127.0.0.1:18444:…`), `User=<node-user>`, ключ `~/.ssh/id_vmhop` (ed25519, свой на узел, добавлен в `authorized_keys` на VM), `ServerAliveInterval=20 CountMax=3`, `ExitOnForwardFailure=yes`, `Restart=always/10` |
| Балансировка | `haproxy` на VM: `listen origin bind 127.0.0.1:19443` в `mode tcp`, бэкенды `127.0.0.1:18443` и `127.0.0.1:18444`, `check inter 2s fall 2 rise 2`, stats-сокет `/run/haproxy/admin.sock` (для `show stat`) |
| Tunnel-ingress | remote config (Cloudflare API, `PUT /accounts/{acct}/cfd_tunnel/{tid}/configurations`) v3: apex + wildcard → `https://127.0.0.1:19443`, `originRequest.originServerName=demo-ai-lab.ru`, `caPoolPath=/etc/cloudflared/ca-pool.pem`, `noTLSVerify=false` |
| Стендовые коннекторы | `systemctl disable --now cloudflared` на 02/03 — ingress общий, а локального `127.0.0.1:19443` на нодах нет; включённый коннектор отдаёт 502 и мешает демо |

**Приёмка (2026-10-24, ночь).**
```bash
# туннель и коннектор
# Cloudflare API: status=healthy, 4 соединения, все с egress внешней VM; ротаций за 7 мин — 0
# hop-и и балансировщик (на VM)
ss -tlnp | grep -E '19443|18444'          # 127.0.0.1:19443 haproxy, 127.0.0.1:18444 sshd
echo 'show stat' | nc -U /run/haproxy/admin.sock | grep '^origin'   # оба бэкенда UP
# сквозной путь
curl -s -o /dev/null -w '%{http_code}\n' https://demo-ai-lab.ru        # 200 (консоль)
# check-host.net, 8 локаций (CA/DE/HK/NL/RU×2/US×2) — 200 везде
# health-gate: python3 scripts/env_health.py → 0 FAIL (туннель, VM, hop-и, edge)
```
**Дрилл отказа (выполнен):** `systemctl stop vmhop` на k8s-02 → HAProxy за ~4 с переводит бэкенд в
`DOWN`, пять внешних запросов подряд — 200 (обслужил k8s-03); `start` → оба бэкенда `UP`.

**Грабли (важные, повторять при переносе):**
- ingress у туннеля **общий для всех коннекторов**: любой коннектор обязан уметь достучаться до указанного
  в нём origin. Поэтому либо все коннекторы имеют локальный `19443`, либо стендовые гасятся.
- `GatewayPorts` у sshd на VM по умолчанию `no` — это и нужно: проброс слушается только на `127.0.0.1`
  (наружу порт не торчит). Менять на `yes` нельзя.
- `apt install haproxy` поднимает сервис с дефолтным конфигом **до** записи нового — после правки
  `haproxy.cfg` обязателен `systemctl restart haproxy` (иначе `19443` не слушается, сервис при этом `active`).
- `pkill -f '127.0.0.1:18443'` внутри `bash -c` убивает сам скрипт: шаблон есть в его же командной строке.
  Гасить по `systemctl stop` / pid.
- Внешнюю приёмку делать **не только с консоли**: консоль стоит за ZTN и уходит в colo FRA (даёт 502/530
  даже при здоровом туннеле). Истина — `check-host.net` (csrf+cookie, `check-result/{id}`) и Cloudflare API.
- Пины разъехались осознанно: узлы — `cloudflared 2026.10.1`, VM — `2026.10.3`; при следующем апгрейде
  выравнивать.

## 4. Общий health-gate контура (E-приёмка)

Один проход — `python3 scripts/env_health.py` (реестр → внешняя VM/hop-и → Cloudflare-туннель →
внешний путь с подтверждением check-host; коды `0`/`2`/`1`). Кластер отдельно:
`python3 scripts/k8s_health.py`. Ниже — ручные пробы по слоям:

```bash
dig +short NS demo-ai-lab.ru @1.1.1.1                     # NS Cloudflare
dig +short demo-ai-lab.ru                                  # anycast Cloudflare, не IP площадки
dig +short @192.168.10.1 demo-ai-lab.ru                    # LAN → .230
curl -sSI https://demo-ai-lab.ru                           # edge → 200 (после E4/E5)
# Cloudflare API: туннель healthy, 4 соединения, egress = внешняя VM (E7)
# на VM: ss -tlnp | grep -E '19443|1844[34]'; show stat → оба бэкенда UP
# на 02/03: systemctl is-active vmhop = active; systemctl is-active cloudflared = inactive (E7)
# check-host.net (не только консоль): 200 из ≥5 стран
# grep -R по ответам/заголовкам публичных страниц: IP площадки не встречается
```
Сценарии деградации (прогонять после изменений):
1. `systemctl stop vmhop` на 02 → HAProxy за ≤5 c переводит бэкенд в DOWN, внешний путь жив через 03;
2. обрыв SSH-канала 02/03 → VM (обе ноги) → 502 от edge (туннель жив, origin недостижим): поднимать
   `vmhop`, проверить `show stat`;
3. падение VM → 530 (у туннеля нет соединений): переключение на стендовые коннекторы = вернуть
   tunnel-ingress на `https://192.168.10.230` + `systemctl enable --now cloudflared` на 02/03
   (работает только в «хорошие окна» uplink, см. R1);
4. обрыв WAN → LAN-путь через `.230` жив (split-horizon не зависит от Cloudflare);
5. `systemctl stop higress`/ребут узла пары → `.230` переезжает на второй узел пары, DNS не трогается.

## 5. Риски и грабли

- **Public IP площадки — [confidential]**: в наружу идёт только anycast Cloudflare; в доках/логах
  наружные IP не печатать (фильтр AGENTS.md). Публичное имя `demo-ai-lab.ru` — публиковать можно.
- 530/502 на edge до E4 — норма (origin не слушает); не «чинить туннель». **После E5/E7**:
  530/1033 = у туннеля нет ни одной живой сессии (упала VM или её cloudflared); 502 = туннель жив,
  но origin-leg не отвечает (hop/HAProxy). Это два разных лечения — сначала смотреть `show stat` и
  `systemctl is-active vmhop`.
- **R1 (7844 против uplink площадки) — обойдён, не вылечен.** С сети провайдера площадки сессии
  коннектора к edge живут 1–10 мин (медиана ~10 мин, min 165 c), QUIC не поднимается вовсе;
  стендовые коннекторы поэтому выведены (`disable --now`). Возврат к ним — только если uplink
  разблокируют; проверка — 4 соединения без ротаций ≥15 мин через Cloudflare API.
- **VM — единственная точка отказа внешнего пути** (до появления второй VM/hop-а в другом облаке).
  Симптомы: 530 при живом стенде. Лечение — поднять VM/cloudflared, либо аварийный откат на схему
  «origin `https://.230` + коннекторы на 02/03» (пункт 3 сценариев §4).
- **Токен туннеля теперь на двух сторонах** (стенд + VM, файлы 600). При смене владельца VM/отзыве
  доступа — ротировать токен в Cloudflare UI и разложить заново. SSH-доступ: по одному ed25519-ключу
  на узел, отзывается удалением строки из `authorized_keys` на VM.
- Cloudflare API: `PATCH` zone settings — только JSON (`Content-Type: application/json`;
  форма → `6003`); custom-токен без `Zone:Read` даёт `9109` на функциональных вызовах при
  `verify=active`; ретраи солвера после 9109 ловят `10502` (rate-limit) — лечить паузой/
  scale cert-manager в 0, не частыми попытками. Внешняя приёмка при капризном egress
  площадки — check-host.net (report API: csrf+cookie, JSON `check-result/{id}`).
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
- **v1.5** (2026-10-24, ночь): **E7 добавлен и выполнен** — второй egress: `cloudflared` переехал на
  внешнюю VM (SberCloud), origin доводится двумя SSH reverse-hop (`vmhop.service` на 02/03) через
  `haproxy` на loopback VM; tunnel-ingress v3 → `https://127.0.0.1:19443`; стендовые коннекторы
  `disable --now`. Причина — РФ-провайдер режет `7844` на uplink площадки (R1), с сети VM сессии
  стоят. Приёмка: 4 соединения без ротаций, 200 из 8 стран, дрилл отказа hop-а (failover за ~4 c).
  Full strict сохранён (hop — TCP-пайп, TLS не терминируется).
- **v1.4** (2026-10-24): **E6 снят** — служебные хостнеймы (`argocd.*`, админ-UI) живут только в LAN,
  наружу публикуются только демо-сервисы; механика «не публиковать» = отсутствие Ingress
  (туннель на wildcard отдаёт 404). Зафиксировано также: `echo.demo-ai-lab.ru` — постоянный
  тестовый маршрут, контейнер живёт всегда.
- **v1.3** (2026-10-19, день): **E5 закрыт** — токен владельца в inventory → Secret/Issuer →
  LE wildcard `demo-wildcard-tls` → Higress :443 (LAN 200 с ISRG) → tunnel-ingress v3 на
  `https://.230` + caPool + `originServerName` → зона **Full (strict)** (PATCH JSON, грабельный
  `6003` на форме) → legacy-NAT `*2` отключена (tcpdump на `.253` чист). Сквозной внешний
  200 через edge зафиксирован; E4 принята целиком. Операционный остаток — R1 (шторм канала
  коннектор→edge, 530-окна). Cloudflare API-идентификаторы (zone/account/tunnel id) —
  в gitops/инвентаре; скоупы токена расширены `Zone:Read` (+ Access Edit про запас для E6).
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