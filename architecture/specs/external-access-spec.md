# Спецификация внешнего доступа стенда demo-ai-lab

> **Версия 2.0** (2026-11-25), статус: **действующий контур — внешняя VM + два SSH-hop'а**;
> облачный туннель выведен из пути (ADR-0004, ревизия 2026-11-05). Решение и обоснование —
> `adr/adr-0004-external-access-tunnel-and-vm-egress.md`; схема и риски — `architecture/ARCHITECTURE.md` §6.2;
> карта сети — `network/map.md`; имена — `architecture/endpoints.md`; рецепт роутера —
> `network/mikrotik.md`. Секреты (адрес VM, SSH-ключи) — `inventory.local.md`, вне git.

## 1. Контур

| Сущность | Значение | Статус |
|---|---|---|
| Домен | `demo-ai-lab.ru` | зона на `ns1/ns2.reg.ru`; `A @`/`A *` → адрес VM, `AAAA` нет |
| Публичный вход | внешняя VM (Cloud.ru, 2 vCPU/4.1G), `haproxy :443` `mode tcp` | TLS **не терминируется**, SNI-роутинг только на зону, прочий SNI — reset |
| `:80` на VM | 301 на https | нужен для ACME HTTP-01: валидатор идёт `:80 → :443` |
| Origin | `192.168.10.230:443` — ingress-VIP пары 02/03 (Higress) | отдельный от API-VIP `.240` (ADR-0001), не склеивать |
| Origin-leg | `vmhop.service` на 02/03: SSH `-R 127.0.0.1:18443/18444 → .230:443`; `haproxy` балансирует два бэкенда | `check inter 2s fall 2 rise 2`, stats-сокет `/run/haproxy/admin.sock` |
| Фильтрация | на VM: `conn-rate` по источнику + SNI-денилст служебных UI | снаружи `argo`/`hgc`/`lng`/`mon` рвутся на TLS |
| split-DNS | MikroTik: `demo-ai-lab.ru` + regexp-wildcard → `.230`, `AAAA → ::1` | LAN не зависит от внешнего DNS; `network/mikrotik.md` §3.5 |
| Резерв | туннель и `cloudflared` установлены, но из пути выведены; `haproxy` слушает `127.0.0.1:19443` под туннельный ingress | не рабочий путь; менять только по решению |

Не входит: маршруты Higress, AI-плагины и guard-маршруты (`k8s-install-spec` §10),
установка кластера, адреса сервисов (`architecture/endpoints.md`).

## 2. Схема

```
интернет ──▶ <адрес VM>:443   haproxy `mode tcp`
               ├─ SNI demo-ai-lab.ru / *.demo-ai-lab.ru → бэкенды hop'ов
               │     ├─ 127.0.0.1:18443  ← SSH -R с k8s-02 (`vmhop.service`)
               │     └─ 127.0.0.1:18444  ← SSH -R с k8s-03
               │           └─ origin https://192.168.10.230:443 (Higress, VIP)
               ├─ :80 → 301 на https (ACME HTTP-01)
               └─ прочий SNI / заход по IP → reset
LAN ──split-DNS @192.168.10.1──▶ 192.168.10.230:443 ──▶ Higress
```

- Наружу из uplink площадки не идёт ничего: hop'ы — исходящие SSH-сессии 02/03 → VM (TCP/22);
  входящий NAT 80/443 на площадке открыт только с адреса VM.
- Hop — чистый TCP-пайп: TLS не терминируется ни на VM, ни в SSH; SNI доезжает до Higress,
  клиент видит сертификат Let's Encrypt от cert-manager.
- `.230` обслуживает пара 02/03: kube-vip LB-инстанс `pool .230` только на них,
  Higress `externalTrafficPolicy: Local` — VIP отвечает там, где живой endpoint.

## 3. E7 — VM + два SSH-hop'а (выполнено 2026-10-24)

Почему VM: uplink площадки режет исходящие сессии к облачному edge — историю и замеры см. в
ADR-0004; действующая схема от этого не зависит.

| Слой | Что именно |
|---|---|
| Вход | `haproxy` на VM: `:443` `mode tcp`, SNI-роутинг, бэкенды `18443/18444`; `:80` → 301 |
| Origin-нога | `vmhop.service` на k8s-02 (`-R 127.0.0.1:18443:192.168.10.230:443`) и k8s-03 (`18444`), ключ `id_vmhop` (свой на узел), `ServerAliveInterval=20 CountMax=3`, `ExitOnForwardFailure=yes`, `Restart=always/10` |
| Безопасность SSH | `GatewayPorts no` (по умолчанию) — проброс слушается только на `127.0.0.1`; менять нельзя |
| Резерв | `cloudflared` на VM + `listen 127.0.0.1:19443` в haproxy — туннельный ingress, вне DNS |

**Приёмка:** `ss -tlnp | grep -E '443|80|18443|18444'` на VM; `echo 'show stat' | nc -U
/run/haproxy/admin.sock` — оба бэкенда `UP`; `curl https://demo-ai-lab.ru/` снаружи — 200;
`check-host.net` — 200 из ≥5 стран; `openssl s_client -connect <VM>:443 -servername demo-ai-lab.ru`
— LE `CN=demo-ai-lab.ru`.

**Дрилл (выполнен):** `systemctl stop vmhop` на 02 → бэкенд `DOWN` за ~4 с, внешние запросы
обслуживает 03; `start` → оба `UP`.

**Грабли:** после правки `haproxy.cfg` обязателен `restart` (сервис `active`, но `:443` не слушает);
`pkill -f 127.0.0.1:18443` внутри `bash -c` убивает сам скрипт; внешнюю приёмку делать не только
с консоли (ZTN-DNS/colo искажают ответ).

## 4. Служебные UI — E9 (внедрено 2026-11-04, ревизия 2026-11-25)

Правило: **непользовательские сервисы — только из LAN**: `argo.`, `hgc.`, `lng.`, `mon.`.
Не «не публиковать Ingress» (внешний вход пропускает любой валидный SNI зоны), а allowlist на шлюзе.

| Параметр | Значение |
|---|---|
| Механизм | `WasmPlugin ip-restriction` в `higress-system`, `gitops/infra-apps/infra/lan-only-ui.yaml` |
| Allow | только `192.168.10.0/24` (с 2026-11-25; `10.0.0.0/8` — диапазон hop'а — снят) |
| Источник | XFF (реальный клиент) + страховка по настоящему peer'у без `172.16.0.0/12` |
| Снаружи | `403` `{"message":"LAN only"}`; из LAN — обычный ответ сервиса |
| `lng.` | дополнительно `basic-auth` (`WasmPlugin` вне Argo, `scripts/longhorn_ui_auth.sh`) |
| Проверка | `k8s_health.py` — строка `Allowlist служебных UI`; `env_health.py` — SNI-обрыв снаружи |

### E9.1 — по хостам

| Хост | Ingress | Гейт |
|---|---|---|
| `argo.` | `gitops/infra-apps/argocd/30-ingress.yaml` | `lan-only-ui`; вход Argo CD собственный |
| `hgc.` | `gitops/infra-apps/infra/higress-console-ingress.yaml` | `lan-only-ui`; вход admin |
| `lng.` | `gitops/infra-apps/infra/longhorn-ui-ingress.yaml` | `lan-only-ui` + `basic-auth` (E9.3) |
| `mon.` | `gitops/apps/monitoring/` (ADR-0009) | `lan-only-ui`; `/mcp` — только из кластера |

### E9.2 — что выяснилось замером (повторять при правке)

1. **Peer в одиночку негоден:** адреса hop/edge попадают в `172.16.0.0/12`, allowlist по peer'у
   пропустил бы внешний трафик; XFF клиент подделывает — нужны оба фильтра по «И».
2. **`defaultConfig` глобальный** — allowlist там применяется ко всем хостам шлюза
   (`owu`/`spk`/`doc`/`mcp` начали отдавать `403`); правило — в `matchRules[].config`,
   `defaultConfigDisable: true`.
3. **Правило без `config` ломает плагин:** «allow and deny cannot be empty» → `500` на всех
   хостах правила; добавляя домен, копировать блок целиком.
4. **`10.0.0.0/8` в allow-списке делал гейт фиктивным** (это диапазон SSH-hop'а): снаружи
   `peer 10.0.0.59` проходил. Список исправлен на `192.168.10.0/24` — из LAN `200`,
   из пода кластера `403`.

### E9.3 — `lng.`: Basic Auth поверх allowlist

У Longhorn UI нет своей аутентификации, а `/v1/*` даёт полный контроль дискового слоя. Гейты:
сетевой allowlist (снаружи) + `basic-auth` (внутри LAN: чужой ноутбук, гостевой Wi-Fi).
`WasmPlugin` `basic-auth` (`phase: AUTHN`, `priority: 320`, `failStrategy: FAIL_CLOSE`),
`matchRules.domain: [lng...]`, `allow: [admin]`, `global_auth: false`. Учётка одна, пароль — в
`lng-admin.local.md`, ротация — `scripts/longhorn_ui_auth.sh --rotate`; объект вне Argo
(credential инлайнится в `defaultConfig`). Из LAN без кредов `401`, с кредами `200`, снаружи `403`.

Пользовательские хосты правилом не закрываются: apex, `echo`, `api`, `owu`, `spk`, `doc`, `rag`,
`ysrch`, `llm`, `llm-svc`, `mcp`. У `auth.` публичны только `/realms/dev*` и `/resources*`;
админ-пути не маршрутизируются (`keycloak-spec` §4.5).

## 5. Приёмка контура

```bash
python3 scripts/env_health.py            # DNS → VM (haproxy, бэкенды) → публичный путь → check-host
python3 scripts/k8s_health.py            # кластер, VIP, ingress, allowlist служебных UI
dig +short demo-ai-lab.ru                # один адрес VM; AAAA нет
dig +short @192.168.10.1 demo-ai-lab.ru  # LAN → 192.168.10.230
curl -sSI https://demo-ai-lab.ru         # 200, LE-сертификат
```

Сценарии деградации: stop `vmhop` на 02 → путь жив через 03 (~4 с); обрыв обеих SSH-ног →
`502` от haproxy; падение VM → внешний путь недоступен (LAN жив); сбой higress/ребут узла пары →
`.230` переезжает на второй узел.

## 6. Риски и остатки

- **VM — единственная точка отказа внешнего пути.** Лечение — поднять VM/haproxy/hop'ы;
  вторая VM — отдельная работа.
- **ACME:** wildcard-серт действует до 17.01.2027, DNS-01 недоступен (зона на reg.ru);
  ClusterIssuer `letsencrypt-wildcard` и его секреты удалены 2026-11-25 — 11 `Certificate`
  ссылаются на него и живут до 17.01–02.02.2027, автопродление не сработает. Новые хосты —
  `letsencrypt-http01`; план — `TODO.md`.
- **Периметр:** нет anti-DDoS и IPv6 на входе; фильтрация источника — `conn-rate` + SNI-денилст
  на VM. Детали и остаточные риски — локальный отчёт ИБ, вне репозитория.
- **Публичный IP площадки не публикуется:** в DNS только адрес VM (`[confidential]`).
- RouterOS-грабли (lease, wildcard-DNS) — `network/mikrotik.md` §3.5, `k8s-install-spec` §9.

## 7. История Cloudflare-периода (закрыт 2026-11-05)

Ревизия ADR-0004 отказалась от облачного посредника: зона и трафик зависели от чужого аккаунта,
публичный периметр настраивался в чужой панели. Таблица — только чтобы понимать отсылки в старых
документах; детали и замеры — ADR-0004 и git-история спеки.

| Фаза | Что было | Сейчас |
|---|---|---|
| E1 | зона в Cloudflare, proxied CNAME на туннель | зона на reg.ru, `A` на VM |
| E2 | `cloudflared` на 02/03, туннель `demo-lab-ingress-v2` | коннекторы `disable --now`, туннель вне пути |
| E3 | split-horizon DNS на MikroTik | без изменений (действует) |
| E4 | ingress на `.230`, внешний путь через edge | ingress `.230`; вход — VM `:443` |
| E5 | DNS-01 через Cloudflare, Full (strict), caPool | DNS-01 недоступен; HTTP-01; TLS на origin |
| E6 | Cloudflare Access | снят 2026-10-24; служебные UI — allowlist E9 |
| E8 | WAF-allowlist зоны | неактуально: зона и edge вне пути |

История версий: v1–v1.7 — Cloudflare-период (зона, туннель, Full strict, E1–E6);
v1.8–v1.9 — allowlist служебных UI и логин Longhorn (E9.1–E9.3); v1.10 — TLS `mon.` через HTTP-01;
**v2.0 (2026-11-25) — спека приведена к действующему контуру: Cloudflare-детали вынесены в
ADR-0004, оставлены E7, E9 и риски.**

## 8. Связанные документы

- `adr/adr-0004-external-access-tunnel-and-vm-egress.md` — решение и ревизии;
- `architecture/ARCHITECTURE.md` §6.2 — схема, ACME, риски; `network/map.md` — карта и VIP;
- `network/mikrotik.md` §3.5/§3.6 — рецепт роутера;
- `architecture/endpoints.md` — имена и SSO;
- `architecture/specs/keycloak-spec.md` §4.5 — админ-пути SSO.
