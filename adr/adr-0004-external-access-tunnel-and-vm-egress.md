# ADR-0004: Внешняя доступность стенда — Cloudflare (Tunnel, Free) + внешняя VM-egress

- Дата: 2026-10-18
- Статус: **Accepted** (решение владельца: «Зафиксируй решение — работать через Cloudflare», 2026-10-18)
- Ревизия: 2026-10-18 — принято решение по TLS: сертификат origin от Let's Encrypt, режим Full(strict)
  (**вариант 2**, владелец) — см. раздел «Решение по TLS»; п. 4 «Решения» уточнён на месте
- Ревизия: 2026-10-24 — R1 (uplink площадки режет порт `7844`): коннектор перенесён на внешнюю VM,
  origin доводится SSH reverse-hop + haproxy (`architecture/specs/external-access-spec.md` E7); стендовые коннекторы на
  k8s-02/03 выведены (`disable --now`)
- Ревизия: 2026-10-24 (2) — **область решения расширена**: это уже не только Cloudflare Tunnel, а
  весь внешний путь «edge → VM-egress (коннектор + haproxy) → два SSH-туннеля с k8s-02/03 → origin».
  Файл переименован в `adr-0004-external-access-tunnel-and-vm-egress.md`; ссылки обновлены.
- Ревизия: 2026-10-24 (3) — **сверено с живым состоянием** (см. «Проверено на стенде»): туннель
  healthy, 4 соединения, egress = внешняя VM; DNS — CNAME apex и wildcard; haproxy 2/2 UP;
  `cloudflared` на 02/03 `disabled`/`inactive`, `vmhop` `enabled`/`active`; SSL-режим зоны `strict`.

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

## Решение

Внешний путь сервиса — **только через Cloudflare, Free-план ($0)**:

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
5. Cloudflare Access **не используем**: E6 снят решением владельца 2026-10-24 — служебные UI
   (Argo CD, консоли) живут только в LAN и наружу не публикуются. Исключение — `auth.demo-ai-lab.ru`
   (Keycloak), который публикуется целиком, включая `/admin`, по отдельному решению (план Б,
   `architecture/specs/keycloak-spec.md` §4.5). Access остаётся запасным вариантом, если служебный маршрут всё же
   понадобится снаружи.

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

## Альтернативы (рассмотрены и отклонены)

- **Прямой NAT 80/443 + DDNS-скрипт MikroTik → A-запись на IP провайдера** —
  публикует и идентификационно связывает адрес площадки; зависит от входящих чужой сети.
  Отклонено (требование конфиденциальности).
- **Свой VPS как реверс-прокси + SSH-туннель со стенда** — тоже скрывает IP и не требует
  входящих, но добавляет оплачиваемый хост и ещё одно звено с отдельной поверхностью
  обслуживания. Cloudflare Tunnel даёт то же без лишней машины. Отклонено как избыточное
  (VPS остаётся запасным вариантом на случай отказа от Cloudflare).
- **Только LAN (без внешней доступности)** — не удовлетворяет сценарий «показать
  публичный URL» на демо.