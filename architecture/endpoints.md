# Публичные адреса сервисов стенда

Один список имён — чтобы не искать по спекам, какой хост у сервиса и что за ним стоит.
Источник решений по SSO — `architecture/keycloak-spec.md`; механика внешнего доступа —
`architecture/external-access-spec.md`.

## Правила

- Все имена — в зоне `demo-ai-lab.ru`, **короткие** (3–4 символа): `owu`, `rag`, `spk`, `qm`, `her`, `argo`, `hgc`.
  Исторические `auth.` (Keycloak) и `api.` (GPUStack) оставлены как есть: они уже в спеках,
  в `base_url` клиентов и в конфиге туннеля — переименование дороже, чем экономия символов.
  Argo CD переименован 2026-10-28 (`argocd.` → `argo.`) — он был единственным новым хостом
  с длинным именем.
- `*.demo-ai-lab.ru` — wildcard в Cloudflare (proxied) и regexp-wildcard в split-DNS MikroTik → `.230`.
  **Новый хост не требует правок в Cloudflare или туннеле:** достаточно завести Ingress в Higress —
  туннель роутит любой валидный Ingress зоны (`external-access-spec.md`, E5/E7).
- **AAAA в LAN не отдаётся** (с 2026-10-27): split-DNS отвечает `AAAA = ::1` для apex и wildcard —
  IPv6 на стенде нет, а без этой записи AAAA уходил в публичный резолвер и возвращал anycast
  Cloudflare, уводя клиентов с IPv6-предпочтением мимо `.230`.
- TLS — по правилу E-серии: сертификат живёт **в namespace Ingress'а**, wildcard-секрет из `demo-test`
  не переиспользуется. Для каждого нового ns — свой `Certificate` от `letsencrypt-wildcard`.
- Снаружи и из LAN адрес один и тот же; LAN-путь идёт через split-DNS на `.230` и не зависит от туннеля.
- Служебные UI наружу: **Argo CD публикуется** (решение владельца 2026-10-28, теперь `argo.demo-ai-lab.ru`),
  **консоль Higress публикуется** (решение владельца 2026-10-28, `hgc.demo-ai-lab.ru`); Longhorn
  остаётся **только LAN**. Механика «не публиковать» — не заводить Ingress в Higress (туннель роутит
  любой валидный Ingress зоны), авторизация внешних админок — открытый вопрос
  (`external-access-spec.md` E9); у консоли Higress вход собственный (admin), у Argo CD — свой.

## Адреса

| Короткое имя | Хост | Сервис | Авторизация | Статус |
|---|---|---|---|---|
| `apex` | `demo-ai-lab.ru` | apex-Ingress (заглушка/витрина) | без авторизации | работает |
| `echo` | `echo.demo-ai-lab.ru` | smoke-контейнер (проверка LAN- и внешнего пути) | без авторизации | работает (постоянный, решение 2026-10-24) |
| `auth` | `auth.demo-ai-lab.ru` | Keycloak, realm `dev` | **публично целиком, включая `/admin`** — план Б, без Access (`keycloak-spec.md` §4.5) | **установлен 2026-10-27** (K1–K7) |
| `api` | `api.demo-ai-lab.ru` | GPUStack: UI + OpenAI-совместимый API | UI — SSO Keycloak (клиент `gps`), API-путь — ключ GPUStack (браузерный SSO для `/v1/*` не применяется) | **установлен 2026-10-28**: G0–G7 закрыты (чат `gemma-4-12B` + ASR `whisper-turbo` на 5060 Ti, SSO включён); G8 — приёмка/репетиция |
| `owu` | `owu.demo-ai-lab.ru` | Open WebUI (чат к моделям) | SSO | план: шаг 2 |
| `rag` | `rag.demo-ai-lab.ru` | RAGFlow | SSO | план: шаг 2 |
| `doc` | `doc.demo-ai-lab.ru` | Docling (OCR/разбор документов) | **без авторизации** (решение 2026-10-24) | план: шаг 2 |
| `spk` | `spk.demo-ai-lab.ru` | Speakr (транскрибация) | SSO | план: шаг 2 |
| `qm` | `qm.demo-ai-lab.ru` | qm (мультиагентный рантайм) | SSO | план: шаг 3 |
| `her` | `her.demo-ai-lab.ru` | Hermes (агентский рантайм) | SSO | план: шаг 3 |
| `mcp` | `mcp.demo-ai-lab.ru` | **MCP Registry** (`modelcontextprotocol/registry`) — каталог MCP-серверов (веб-UI нет, API `/v0`, `/docs`) | чтение — публично; публикация — по доменному токену (неймспейс `ru.demo-ai-lab`); админ — SSO Keycloak (`MCP_REGISTRY_OIDC_*`) | план: шаг 3 (`architecture/mcp-registry-spec.md`) |
| `argo` | `argo.demo-ai-lab.ru` | Argo CD (GitOps-контроллер) | собственный вход Argo CD; SSO/политика — открытый вопрос (`external-access-spec.md` E9) | публикуется наружу по решению 2026-10-28; Ingress+Certificate заведены 2026-10-28 (хост переименован из `argocd.`) |
| `hgc` | `hgc.demo-ai-lab.ru` | консоль Higress (маршруты, плагины, сертификаты; релиз helm `higress-console` 2.1.9 в `higress-system`) | собственный вход (admin), пароль — `higress-console-admin.local.md` (gitignored) | **опубликована 2026-10-28** (решение владельца; до этого «только LAN») |
| — | `longhorn.*` | Longhorn UI | — | не публикуется, только LAN |

Инструменты MCP (план шага 3) отдельных хостов не получают: `mcp-server`/`mcp-proxy` в Higress
вешаются на маршруты сервисов (`owu/…`, `rag/…` и т.д.), а `mcp.*` — каталог (реестр), не вызовы.

## Связка с SSO (кто получает клиента в Keycloak)

| Хост | clientId | Тип | Примечание |
|---|---|---|---|
| `owu` | `owu` | confidential | redirect берётся из доки/лога сервиса |
| `rag` | `rag` | confidential | то же |
| `spk` | `spk` | confidential | то же |
| `qm` | `qm` | confidential | то же |
| `her` | `her` | confidential | то же |
| `api` | `gps` | confidential | redirect строго `<server-url>/auth/oidc/callback` (дока GPUStack) |
| `doc` | — | — | авторизации нет |
| `mcp` | `mcp` | confidential, client-credentials | админ/права публикации реестра (`MCP_REGISTRY_OIDC_*`); механизм сверить при деплое |
| (машины) | `agent-runtime` | confidential, client-credentials | M2M шага 3, роль `agent-service` |
| (приёмка) | `smoke-cli` | public, direct access grant | только для curl-проверок K5 |

## Что проверить при добавлении нового адреса

1. Ingress в нужном ns, класс `higress`, TLS-секрет из своего `Certificate`.
2. `dig @192.168.10.1 <имя>` → `192.168.10.230`; `curl https://<имя>/` из LAN → 200.
3. Снаружи `curl --resolve <имя>:443:<IP edge>` (или просто `curl https://<имя>/`) → 200, не 530/1033.
4. Если сервис за SSO — клиент в `keycloak-clients.local.md`, redirect проверен на месте.
5. Строка в этой таблице и статус в `ARCHITECTURE.md` §7 обновлены.
