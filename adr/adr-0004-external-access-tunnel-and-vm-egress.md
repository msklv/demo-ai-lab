# ADR-0004: Внешняя доступность стенда — внешняя VM (haproxy) + SSH-hop'ы, без Cloudflare

- Дата: 2026-10-18
- Статус: **Accepted** (решение владельца: «Зафиксируй решение — работать через Cloudflare», 2026-10-18);
  **ревизия 2026-11-05 отменяет Cloudflare** — действующая схема в разделе «Решение 2026-11-05»
- Ревизия: 2026-11-05 — **Cloudflare выведен из внешнего пути** (решение владельца). Публичный вход —
  напрямую адрес внешней VM (`:443`, адрес — `[confidential]`, в инвентаре): haproxy на внешней VM,
  TLS passthrough, SNI-роутинг в два SSH-hop'а до origin. DNS-зона `demo-ai-lab.ru` ушла с Cloudflare
  на **reg.ru** (`ns1/ns2.reg.ru`), записи `A @`/`A *` → адрес VM. Туннель и `cloudflared` выведены из
  пути. Обязательное последствие — **ACME перестаёт работать** (solver `cloudflare` в зоне, которой
  больше нет): переводится на `regru`/`acme-dns`
- Ревизия: 2026-10-18 — принято решение по TLS: сертификат origin от Let's Encrypt, режим Full(strict)
  (**вариант 2**, владелец) — см. раздел «Решение по TLS»; п. 4 «Решения» уточнён на месте
- Ревизия: 2026-10-24 — R1 (uplink площадки режет порт `7844`): коннектор перенесён на внешнюю VM,
  origin доводится SSH reverse-hop + haproxy (`architecture/specs/external-access-spec.md` E7); стендовые коннекторы на
  k8s-02/03 выведены (`disable --now`)
- Ревизия: 2026-10-24 (2) — **область решения расширена**: это уже не только Cloudflare Tunnel, а
  весь внешний путь «edge → VM-egress (коннектор + haproxy) → два SSH-туннеля с k8s-02/03 → origin».
  Файл переименован в `adr-0004-external-access-tunnel-and-vm-egress.md`; ссылки обновлены.
- Ревизия: 2026-11-04 — **доступ к служебным UI ограничен allowlist'ом на Higress** (только локальные
  сети; снаружи `403`). Правило распространяется на `argo.`, `hgc.`, `lng.` (Longhorn UI), `mon.` и любой
  будущий непользовательский UI; подпункт 5 «Решения» исправлен — служебные маршруты существуют (E9), но
  не открыты наружу. **Реализовано в тот же день**: два `WasmPlugin` `ip-restriction`
  (`gitops/infra-apps/infra/lan-only-ui.yaml`) — allow по `X-Forwarded-For` и страховка по настоящему
  peer'у, домены `argo`/`hgc`/`lng`/`mon`; живой замер и грабли — `external-access-spec` E9.2.
- Ревизия: 2026-10-24 (3) — **сверено с живым состоянием** (см. «Проверено на стенде»): туннель
  healthy, 4 соединения, egress = внешняя VM; DNS — CNAME apex и wildcard; haproxy 2/2 UP;
  `cloudflared` на 02/03 `disabled`/`inactive`, `vmhop` `enabled`/`active`; SSL-режим зоны `strict`.

## Решение 2026-11-05: отказ от Cloudflare (действующая схема)

Владелец отказался от Cloudflare как звена внешнего пути. Причины: зона и трафик зависели от
чужого аккаунта и его ToS; публичный периметр настраивался в чужой панели; единственное WAF-правило
зоны (`block, not ip.src eq <egress площадки>`) пропускало **только сам стенд** — для всех остальных
внешний зритель получал `403`, то есть Cloudflare уже не отдавал демо; фильтрацию трафика по IP
владелец хочет держать своей, а не арендовать.

```
интернет ──▶ <адрес VM>:443     VM Cloud.ru (vm-ce10b9), haproxy `mode tcp`
               ├─ SNI demo-ai-lab.ru / *.demo-ai-lab.ru → бэкенды hop'ов
               │     ├─ 127.0.0.1:18443  ← SSH -R с k8s-02 (`vmhop.service`)
               │     └─ 127.0.0.1:18444  ← SSH -R с k8s-03
               │           └─ origin https://192.168.10.230:443 (Higress, VIP)
               └─ прочий SNI / заход по IP → reset (backend deny_all)
LAN ──split-DNS @192.168.10.1──▶ 192.168.10.230:443 ──▶ Higress (не меняется)
```

1. **DNS.** Зона `demo-ai-lab.ru` делегирована на `ns1.reg.ru` / `ns2.reg.ru`; `A @` и `A *` →
   адрес внешней VM (`[confidential]`, в инвентаре); `TXT` `v=MCPv1; k=ed25519; …` сохранён
   (верификация домена MCP-реестра); `AAAA` отсутствует — у VM нет публичного IPv6, v6-only клиенты
   стенд не видят. TTL записей держать 300–600 (сейчас 86400 — сутки на любую правку и откат).
2. **Точка входа — внешняя VM.** haproxy на `:443`, `mode tcp`, TLS **не терминируется**: браузер
   видит сертификат cert-manager'а (LE `CN=demo-ai-lab.ru`), origin проверяется клиентом напрямую.
   SNI-роутинг только на `demo-ai-lab.ru` и `*.demo-ai-lab.ru`; всё прочее рвётся. Публикуется адрес
   VM — публичный IP площадки в DNS не попадает (требование конфиденциальности сохраняется).
3. **Фильтрация — своя, в двух местах.** На VM: `stick-table` на источник (`conn_cur`, `conn_rate`),
   SNI-денилст служебных UI (`argo`, `hgc`, `lng`, `mon`). На площадке: входящий NAT для 80/443 —
   только для адреса VM. Security group Cloud.ru: `443/TCP` из `0.0.0.0/0`, `22/TCP` — только адреса
   менеджмента (egress площадки динамический — нужен второй разрешённый адрес), порт `80` не публикуется.
4. **Cloudflare не используется.** Туннель `demo-lab-ingress-v2` и `cloudflared` на VM остаются
   установленными, но из пути выведены; зона в Cloudflare — архив. Резервом туннель больше **не**
   является: возврат NS стоит до 4 суток (TTL делегирования `345600`). Резерв — второй бэкенд в
   haproxy, публичный адрес площадки `:443` (`[confidential]`, отвечает валидным LE-сертом).
5. **TLS/ACME.** Выпуск и продление wildcard переводятся с Cloudflare DNS-01 на провайдера, у
   которого живёт зона: lego `regru` (`CLOUDRU_*`→`REGRU_*`-аналоги) либо `acme-dns` + CNAME
   `_acme-challenge`. До перевода продление не работает: серт действует до **17.01.2027**, попытка
   продления ~18.12.2026 закончится ошибкой молча.
6. **Что отменяется этим решением:** п. 1–3 «Решения» от 2026-10-18 (зона в Cloudflare Free;
   публичные ответы — CNAME на `<tid>.cfargotunnel.com`, `proxied=true`; транспорт — Cloudflare
   Tunnel с плечом edge→origin в режиме Full strict). Они сохраняются как история. Пункты 4–5
   (сертификат origin от LE; Access не используем, ограничение служебных UI — на Higress) остаются
   в силе, но allowlist служебных UI требует доработки — см. п. 7.
7. **Остаточные риски, принятые владельцем:** нет рубежа против волюметрических атак (anycast и
   анти-DDoS Cloudflare сняты); нет IPv6 на входе; VM — единая точка отказа внешнего пути.
   **Периметр служебных хостнеймов и админ-путей после переезда требует доработки** — это отдельная
   работа по слою L7, до её завершения внешний вход закрыт на уровне security group (`443` только
   для адресов стенда). Детали, замеры и план устранения — локальный отчёт ИБ от 2026-11-05,
   `security/*.local.md`, вне репозитория.

## Контекст

Демо-сервисам стенда нужна внешняя доступность (домен `demo-ai-lab.ru`), при этом:
- uplink стенда — сеть площадки с динамическим public IP; владелец потребовал **не
  публиковать IP провайдера** (требование конфиденциальности площадки, AGENTS.md);
- входящие соединения в uplink площадки ненадёжны/неконтролируемы (чужая DHCP-сеть,
  NAT, возможный блокирующий firewall — на время демо гарантировать нельзя);
- зона `demo-ai-lab.ru` изначально делегировалась на reg.ru (проверено dig'ом
  2026-10-18; NS-переход инициирован владельцем в тот же день);
- LAN-путь демо уже закрыт split-DNS на MikroTik (regex `*.demo-ai-lab.ru` → ingress-VIP
  `192.168.10.230`, работает с 2026-10-18) — внешнему каналу не противоречит.

## Решение (редакция 2026-10-18 — история; отменено ревизией 2026-11-05)

1. Зона `demo-ai-lab.ru` перенесена в Cloudflare (аккаунт владельца; Free Website, $0;
   создана 2026-10-18, NS `irena/newt.ns.cloudflare.com`; на 2026-10-24 зона `active`). Итого безлимитно по: DNS, Tunnel + трафик, Universal SSL, DDoS, Access до
   50 пользователей (проверено по cloudflare.com/plans 2026-10-18).
2. Публичные DNS-ответы — **только адреса edge Cloudflare**: CNAME `@` и `*` →
   `<tunnel-id>.cfargotunnel.com`, `proxied=true` (проверено по API 2026-10-24: обе записи CNAME,
   id туннеля в прозе не пинится). Internal-адресация (`192.168.10.0/24`) и public IP uplink
   в публичной зоне не публикуются никогда.
3. Транспорт — **Cloudflare Tunnel** `demo-lab-ingress-v2` (remotely-managed; id волатилен —
   пересоздан 2026-10-23, в прозе не пинится: резолвится динамически `env_health.py` из DNS
   CNAME / Cloudflare API). Реальная цепочка (проверено 2026-10-24):

   ```
   edge Cloudflare
     └─ cloudflared на внешней VM (systemd, `tunnel run --protocol http2`,
        `--origin-ca-pool /etc/cloudflared/ca-pool.pem`, 2026.10.3)
          └─ remote ingress v3: `demo-ai-lab.ru` и `*.demo-ai-lab.ru` →
             https://127.0.0.1:19443  (originServerName=demo-ai-lab.ru,
             caPoolPath=/etc/cloudflared/ca-pool.pem, noTLSVerify=false)
                └─ haproxy на VM: `listen origin 127.0.0.1:19443` (mode tcp, roundrobin)
                     ├─ 127.0.0.1:18443 ← SSH -R с k8s-02 (`vmhop.service`)
                     └─ 127.0.0.1:18444 ← SSH -R с k8s-03 (`vmhop.service`)
                          └─ origin: https://192.168.10.230:443 (ingress-VIP, Higress)
   ```

   Origin **не** `.230` напрямую: туннель смотрит только в локальный haproxy на VM, а `.230`
   достигается SSH reverse-hop'ами. Стендовые коннекторы на k8s-02/03 выведены
   (`disable --now`, проверено: `disabled`/`inactive`) — uplink площадки режет порт `7844`
   (R1, `architecture/specs/external-access-spec.md` E7), и включённый коннектор без локального `19443` отдавал бы 502.
   Соединения исходящие (TCP 7844, `http2`) — входящие в uplink не требуются.
4. TLS терминируется на edge Cloudflare (Universal SSL). Плечо edge→origin — Full(strict) на
   собственном сертификате (ревизия, см. «Решение по TLS»); внутренний TLS между Higress и подами
   — отдельная задача cert-manager (не затронута).
5. Cloudflare Access **не используем**: E6 снят решением владельца 2026-10-24. **Ограничение доступа к
   непользовательским сервисам — на самом Higress** (ревизия 2026-11-04): на Ingress служебного хоста
   включается `ip-restriction` с allowlist `10.0.0.0/8`, `172.16.0.0/12`, `192.168.10.0/24`, а реальный
   реальный клиентский адрес — из первого элемента `X-Forwarded-For` (туннель несёт публичный адрес
   клиента, LAN — адрес из локальной сети) — поэтому запрос, пришедший через туннель, получает `403`,
   а LAN-путь (split-DNS → `.230`) работает как раньше. Почему не «сырой» source и почему понадобился
   второй объект-страховка — `external-access-spec` E9.2 (измерено: edge отдаёт origin с адресов
   `172.64.0.0/13`, а XFF клиента дописывается слева, т.е. подделывается). Правило применяется к `argo.`, `hgc.`,
   `lng.` (Longhorn UI), `mon.` (ADR-0009) и к любому будущему служебному UI; туннельные маршруты при
   этом **не снимаются**.
   `auth.demo-ai-lab.ru` (Keycloak) — **частичное исключение**: пользовательские пути публичны (иначе
   не работает вход внешних зрителей), а админ-пути `/admin*` и `/realms/master*` закрыты тем же
   allowlist'ом через путь-скоуп на отдельном Ingress (`architecture/specs/keycloak-spec.md` §4.5,
   ревизия 2026-11-04). Раньше п. 5 читался как
   «служебные UI наружу не публикуются вовсе» — это расходилось с E9 (маршруты `argo.`/`hgc.` заведены);
   теперь формулировка приведена к фактическому состоянию. Access остаётся запасным вариантом.

## Последствия

- Доступность демо извне зависит от аккаунта Cloudflare и его ToS: Free-план
  позиционируется для non-business-использования; при коммерциализации стенда —
  апгрейд Pro ($20/мес) (проверено по тарифной странице 2026-10-18).
- Cloudflare видит **IP внешней VM** (source IP коннектора; адрес — `[confidential]`, в инвентаре) — не IP площадки:
  стендовые коннекторы выведены, исходящих к edge с uplink площадки нет. Публично адрес площадки
  не определяется ни в DNS, ни в трафике к edge.
- Токен туннеля — секрет: хранится в `/etc/cloudflared/token.env` (600, root) на внешней VM
  (копия на 02/03), в git не попадает; ротация — через Cloudflare Zero Trust.
- До активации зоны и до подъёма Higress публичный ответ — 5xx/нерезолвится; это штатное
  состояние переходного периода, а не авария.
- Привычный «голый NAT 80/443 на публичный IP» как путь в архитектуре отсутствует;
  правило dstnat на MikroTik **отключено** (disabled=yes — по инвентарю 2026-10-19; живьём
  в проверке 2026-10-24 не переподтверждено: REST/443 на роутере закрыт, чтение — через UI/SSH):
  маршрутизация — Cloudflare Tunnel → VM-egress → hop'ы → ingress-VIP `.230` + Higress.

## Решение по TLS (ревизия 2026-10-18) — сертификат origin, Full strict

Сопоставлены две модели TLS. Снаружи браузер зрителя в **обоих** вариантах видит Cloudflare
Universal SSL (proxied-запись всегда отдаёт его) — различаются плечо edge→origin, поведение LAN
и ограничения приложений:

| Критерий | Вариант 1 — flexible (на `.230` только :80) | Вариант 2 — Full strict (LE wildcard на origin) — **выбран** |
|---|---|---|
| Серт в браузере снаружи | Cloudflare Universal SSL | он же, Cloudflare |
| Плечо tunnel→`.230` | HTTP открытым текстом | HTTPS, собственный сертификат LE |
| LAN по split-DNS (MikroTik → `.230`, Cloudflare не участвует) | только `http://`, TLS нет и взяться ему неоткуда | `https://` с публичным сертификатом LE — идентично внешнему пути |
| Приложение с редиректом http→https / cookie `Secure` | в LAN ломается (к `.230:443` — connection refused) | работает одинаково в LAN и снаружи |
| Устойчивость демо к отказу/торможению Cloudflare | LAN живёт, но только в http | полноценный https в LAN: сертификат в кластере, показу продление не нужно |
| Новое приложение `app.demo-ai-lab.ru` | 1 Ingress Higress (wildcard-DNS и catch-all туннеля уже есть) | то же + 2 строки `tls.secretName` на уже созданный wildcard-secret |

**Решение: вариант 2.** Реализовано связкой F5 (cert-manager) + F7/F8 (ingress-VIP `.230`, Higress) инсталл-спеки и E5 external-access (2026-10-19):

1. cert-manager (спека F5) + ClusterIssuer `letsencrypt-wildcard`: solver **cloudflare DNS01**,
   API-токен (право `DNS:Edit` на зону `demo-ai-lab.ru`) в k8s Secret — в git не кладётся.
2. `Certificate *.demo-ai-lab.ru` → Secret; Higress терминирует :443 на ingress-VIP `.230`.
3. Tunnel-ingress смотрит на `https://127.0.0.1:19443` (haproxy на VM, за ним SSH-hop'ы до `.230`);
   `originRequest.caPoolPath` = `/etc/cloudflared/ca-pool.pem` (корень ISRG), `originServerName` =
   `demo-ai-lab.ru`, `noTLSVerify=false`; SSL-режим зоны Cloudflare = **Full(strict)**
   (проверено по API 2026-10-24: `value=strict`).
4. ACME HTTP-01 принципиально недоступен (входящих в origin нет) — поэтому DNS-01. Выпуск и
   автопродление требуют активной зоны в Cloudflare (propagation NS), но показ демо в LAN от
   этого не зависит — сертификат лежит в кластере.
5. Рецепт split-DNS на MikroTik не меняется: резолв на `.230` корректен в обоих вариантах.

## Проверено на стенде (2026-10-24)

Сверка этого ADR с живым состоянием — не по памяти:

| Слой | Проверка | Факт |
|---|---|---|
| Зона / DNS | Cloudflare API (`zones`, `dns_records`) | зона `active`, план Free, NS `irena`/`newt`; CNAME `demo-ai-lab.ru` и `*.demo-ai-lab.ru` → `<tunnel-id>.cfargotunnel.com`, `proxied=true` |
| Tunnel | API `cfd_tunnel/{id}/configurations` | `demo-lab-ingress-v2`: `status=healthy`; ingress v3: apex + wildcard → `https://127.0.0.1:19443`, `caPoolPath=/etc/cloudflared/ca-pool.pem`, `originServerName=demo-ai-lab.ru`, `noTLSVerify=false`; catch-all `http_status:404` |
| VM-egress | ssh: `systemctl`, `ss`, `haproxy.cfg` | `cloudflared` enabled/active (2026.10.3, `tunnel run --protocol http2 --origin-ca-pool …`), `token.env` 600; `haproxy` active: `listen origin 127.0.0.1:19443` → `127.0.0.1:18443`/`18444` (roundrobin, `check inter 2s`) |
| Стенд | ssh на k8s-02/03 | `cloudflared`: `disabled`/`inactive` (выведены); `vmhop`: `enabled`/`active`, `-R 127.0.0.1:18443:192.168.10.230:443` (02) и `18444` (03); копия `token.env` на узлах осталась (файл, сервис выключен) |
| TLS | API `zones/{id}/settings/ssl` | `strict` (Full strict) |
| Сквозной путь | `scripts/env_health.py` | **15 PASS / 0 FAIL**: egress коннектора = IP VM, 4 соединения, 4/4 запросов к edge — 200, `echo.demo-ai-lab.ru` — 200 |
| Кластер | `scripts/k8s_health.py --brief` | 14 PASS / 1 WARN (рестарты control-plane c 21–23.10) / 0 FAIL — на внешний доступ не влияет |
| Роутер | — | dstnat/forward-правила живьём не перепроверены (REST/443 закрыт); статус — по инвентарю 2026-10-19 |

## Проверено на стенде (2026-11-05, ревизия отказа от Cloudflare)

| Слой | Проверка | Факт |
|---|---|---|
| DNS | `dig` по 10 публичным резолверам (1.1.1.1, 8.8.8.8, 9.9.9.9, OpenDNS, Verisign, Яндекс, SafeDNS, SkyDNS, MSK-IX, AdGuard) | везде `A` = адрес VM, `TXT` MCPv1 на месте, wildcard отвечает на случайное имя; расхождений нет |
| Делегирование | `dig +norecurse NS @a.dns.ripn.net` | `ns1.reg.ru`/`ns2.reg.ru`, TTL `345600` (4 сут — цена отката NS) |
| Зона | `dig @ns1.reg.ru` | `A @`/`A *` → адрес VM, TTL `86400`, `AAAA` отсутствует |
| VM | ssh: `ss -tlnp`, `systemctl`, haproxy stats | `haproxy` active, `:443` (maxconn 1500) + `127.0.0.1:19443`, бэкенды `k8s02`/`k8s03` = `UP` (L4OK); `traefik` и `uptime-kuma` остановлены (`docker stop` + `restart=no`), `:443` освобождён |
| Внешний путь (с разрешённого адреса) | `curl --resolve` на VM:443 | `demo`/`echo`/`owu`/`api`/`mcp` → 200, `doc` 307, `spk`/`auth` 302, `ysrch` 404; серт LE `CN=demo-ai-lab.ru`, `ssl_verify_result=0` |
| Мир | SSL Labs (инфраструктура AWS) | **«Unable to connect»** — security group режет `443` до адреса стенда (правило `/32`); до сужения источника тот же скан давал grade A |
| Служебные UI | запросы через VM: `argo`, `hgc`, `lng`, `mon` | закрыты на входе (SNI-денилст); **периметр админ-путей не завершён** — детали и замеры в локальном отчёте ИБ 2026-11-05 (вне git), поэтому `443` для мира закрыт |
| LAN | split-DNS | `demo-ai-lab.ru` → `192.168.10.230`, 200 — не затронуто |
| Резерв | туннель `127.0.0.1:19443` | 200; `cloudflared` active, но из DNS-пути выведен |

## Альтернативы (рассмотрены и отклонены)

- **Прямой NAT 80/443 + DDNS-скрипт MikroTik → A-запись на IP провайдера** —
  публикует и идентификационно связывает адрес площадки; зависит от входящих чужой сети.
  Отклонено (требование конфиденциальности).
- **Свой VPS как реверс-прокси + SSH-туннель со стенда** — тоже скрывает IP и не требует
  входящих, но добавляет оплачиваемый хост и ещё одно звено с отдельной поверхностью
  обслуживания. Cloudflare Tunnel даёт то же без лишней машины. Отклонено как избыточное
  (VPS остаётся запасным вариантом на случай отказа от Cloudflare). **Ревизия 2026-11-05: этот
  вариант стал решением** — VPS уже был (внешняя VM для коннектора), поэтому переход не потребовал
  новых ресурсов: та же VM, тот же haproxy, те же SSH-hop'ы, сменился только вход (туннель → `:443`
  напрямую) и DNS.
- **Только LAN (без внешней доступности)** — не удовлетворяет сценарий «показать
  публичный URL» на демо.