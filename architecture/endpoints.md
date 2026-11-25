# Публичные адреса сервисов стенда

Один список имён: какой хост у сервиса, что за ним и кто его пускает. Статусы и приёмки —
`ARCHITECTURE.md` §7; детали сервисов — их спеки; механика внешнего входа —
`architecture/specs/external-access-spec.md`; SSO — `architecture/specs/keycloak-spec.md`.

## Правила

- Все имена — в зоне `demo-ai-lab.ru`, **короткие** (3–4 символа). Исторические `auth.` (Keycloak)
  и `api.` (GPUStack) не переименовываются: они в спеках, `base_url` клиентов и конфиге входа.
- `*.demo-ai-lab.ru` — `A *` в зоне reg.ru → адрес внешней VM и regexp-wildcard в split-DNS
  MikroTik → `.230`. **Новый хост не требует правок в DNS:** достаточно Ingress + `Certificate`;
  `haproxy` на VM пропускает любой валидный SNI зоны.
- **AAAA в LAN не отдаётся:** split-DNS отвечает `AAAA = ::1` для apex и wildcard — иначе клиент
  с IPv6-предпочтением уходит мимо `.230` в публичный резолвер.
- TLS — свой `Certificate` **в namespace Ingress'а** (wildcard-секрет из `demo-test` не
  переиспользуется), issuer — `letsencrypt-http01`. Исключение: `llm-svc.` живёт на копии
  wildcard-секрета (`llm-svc-wildcard-tls`, до 17.01.2027) без автопродления.
- **Служебные UI — только LAN** (`argo`, `hgc`, `lng`, `mon`): снаружи рвутся SNI-денилстом
  haproxy, а гейт `lan-only-ui` (`ip-restriction`, allow только `192.168.10.0/24`) отдаёт `403`
  и снаружи, и из пода кластера; из LAN — обычный ответ. Манифест —
  `gitops/infra-apps/infra/lan-only-ui.yaml`, разбор — `external-access-spec` E9.

## Адреса

| Имя | Хост | Сервис | Авторизация | Доступ |
|---|---|---|---|---|
| `apex` | [`demo-ai-lab.ru`](https://demo-ai-lab.ru) | apex-Ingress → `service/echo` + `/testfiles/{4kb,50kb,500kb}.html` | нет | публичный |
| `echo` | [`echo.demo-ai-lab.ru`](https://echo.demo-ai-lab.ru) | smoke-контейнер (проверка LAN- и внешнего пути) | нет | публичный, постоянный |
| `auth` | [`auth.demo-ai-lab.ru`](https://auth.demo-ai-lab.ru) | Keycloak, realm `dev` | пользовательские пути (`/realms/dev*`, `/resources*`) публичны; `/admin*` и `/realms/master*` не маршрутизируются (`404`), консоль — `port-forward` | работает |
| `api` | [`api.demo-ai-lab.ru`](https://api.demo-ai-lab.ru) | GPUStack: UI `/` + OpenAI-API `/v1/*` (chat, embeddings, rerank, audio) | UI — SSO (`gps`); API — ключ GPUStack | работает |
| `llm` | [`llm.demo-ai-lab.ru`](https://llm.demo-ai-lab.ru) | внешний LLM через `ai-proxy` (DeepSeek) + DLP + страж + лимиты | JWT Keycloak (`client_credentials`) | маршрут есть, развитие на паузе (`llm-svc.` в работе) |
| `llm-svc` | [`llm-svc.demo-ai-lab.ru`](https://llm-svc.demo-ai-lab.ru) | тот же внешний LLM для сервисов | статический ключ: `x-api-key` или `Bearer` | работает |
| `owu` | [`owu.demo-ai-lab.ru`](https://owu.demo-ai-lab.ru) | Open WebUI (чат к моделям; RAG на `bge-m3` + реранк 780M) | SSO | работает |
| `rag` | [`rag.demo-ai-lab.ru`](https://rag.demo-ai-lab.ru) | RAGFlow; MCP — `POST /api/v1/mcp` (in-cluster) | SSO нет (OSS без OAuth), пароль | план (`rag-spec`) |
| `doc` | [`doc.demo-ai-lab.ru`](https://doc.demo-ai-lab.ru) | Docling: OCR/разбор на `/`; MCP `/mcp` — только in-cluster | нет | работает |
| `spk` | [`spk.demo-ai-lab.ru`](https://spk.demo-ai-lab.ru) | Speakr (транскрибация, саммари через `llm-svc.`) | SSO + локальная форма (запасной вход) | работает |
| `ysrch` | внешнего адреса нет | Yandex Search MCP `/mcp` — только in-cluster | ключ Search API внутри сервиса | работает (в каталоге `mcp.`) |
| `dsh` | [`dsh.demo-ai-lab.ru`](https://dsh.demo-ai-lab.ru) | DeepSeek Harness (агент-харнесс) | SSO через `oauth2-proxy` (`dsh`, confidential) | план (`dsh-spec`) |
| `hm` | [`hm.demo-ai-lab.ru`](https://hm.demo-ai-lab.ru) | Hermes Agent: панель `/`, gateway 8642 не публикуется | SSO (public+PKCE, `hm`); `/api/status`, `/api/health` → `404` | работает |
| `mcp` | [`mcp.demo-ai-lab.ru`](https://mcp.demo-ai-lab.ru) | MCP Registry: витрина `/`, API `/v0`, `/docs` | чтение публично; публикация — доменный токен; админ — OIDC (`mcp`) | работает |
| `argo` | [`argo.demo-ai-lab.ru`](https://argo.demo-ai-lab.ru) | Argo CD | собственный вход Argo CD | только LAN (`403` снаружи) |
| `hgc` | [`hgc.demo-ai-lab.ru`](https://hgc.demo-ai-lab.ru) | консоль Higress + o11y (`/grafana/`, `/prometheus/`, `/loki/`) | admin (`higress-console-admin.local.md`) | только LAN |
| `mon` | [`mon.demo-ai-lab.ru`](https://mon.demo-ai-lab.ru) | Kuvasz (аптайм и TLS) | admin + API-ключи, SSO нет; `/mcp` — только из кластера | только LAN |
| `lng` | [`lng.demo-ai-lab.ru`](https://lng.demo-ai-lab.ru) | Longhorn UI + API `/v1/*` | Basic Auth (`admin` + `lng-admin.local.md`) поверх allowlist | только LAN |

MCP-серверы внешних адресов не имеют (ADR-0012): `doc` публикует только конвертацию на `/`;
`ysrch` — `yandex-search.ysrch.svc:8766`; `mon/mcp` — LAN + `X-API-KEY`; **GitHub MCP** —
`http://github-mcp.mcp-github.svc:8101/mcp`, ClusterIP без Ingress и SSO. Вызовы агентов — по
in-cluster DNS, `mcp.*` — каталог, не вызовы.

## Связка с SSO (клиенты Keycloak)

| Хост | clientId | Тип | Примечание |
|---|---|---|---|
| `owu` | `owu` | confidential | redirect — из лога сервиса |
| `spk` | `spk` | confidential | то же |
| `dsh` | `dsh` | public, PKCE | вход на Higress (`oauth2-proxy`), redirect `/auth/callback` |
| `hm` | `hm` | public, PKCE | то же |
| `api` | `gps` | confidential | redirect строго `<server-url>/auth/oidc/callback` |
| `mcp` | `mcp` | confidential, client-credentials | админ/права публикации реестра |
| — | `agent-runtime` | confidential, client-credentials | M2M, роль `agent-service` |
| — | `smoke-cli` | public, direct access grant | только для curl-проверок |
| `rag` | — | — | SSO нет (OSS без OAuth) |
| `doc` | — | — | авторизации нет |

## Новый адрес — чек-лист

1. Ingress в нужном ns (класс `higress`) + свой `Certificate` (`letsencrypt-http01`).
2. `dig @192.168.10.1 <имя>` → `192.168.10.230`; `curl https://<имя>/` из LAN → 200.
3. Снаружи: `curl --resolve <имя>:443:<адрес VM> https://<имя>/` → 200 (не `000`/`502`).
4. Если сервис за SSO — клиент в Keycloak, redirect проверен на месте.
5. Строка в этой таблице + статус в `ARCHITECTURE.md` §7.
