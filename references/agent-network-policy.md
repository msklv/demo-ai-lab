# Сетевой периметр агентов: NetworkPolicy для `her` и `dsh`

Один источник правила «куда агенту можно». Спеки ссылаются сюда: `hermes-spec` §7.2, `dsh-spec` §6.1 и W8,
блокер кейса 06 — `cases/README`. Внедрение — `gitops/apps/her/50-networkpolicy.yaml`,
`gitops/apps/dsh/50-networkpolicy.yaml` (в `gitops/` сейчас нет ни одного объекта NetworkPolicy — периметр держится только на ключах и LAN-гейте).

## 1. Инвариант и границы

Агент исполняет чужой текст (письмо, PDF, страница, issue) — значит его сеть это поверхность атаки, а не
удобство. Инвариант: **внутри кластера агент видит ровно то, что описано в каталоге MCP, плюс инференс и шлюз — и
ничего больше: ни чужих Postgres/Redis/MinIO, ни apiserver, ни второго агента.** Наружу (в интернет) агент
ходит как хочет: **исходящий трафик за пределы кластера дополнительно не ограничиваем** (решение владельца
28.11) — ни allowlist по именам, ни запрета на прямые внешние вызовы.

- NetworkPolicy — **последний эшелон**, не замена: SSO на входе (`oauth2-proxy`/Keycloak), ключи на
  сервисах, DLP и страж на llm-маршруте остаются как были.
- Что политика **не** решает: злоупотребление разрешённым инструментом (например, `web_search` по чужим
  формулировкам). Это политика инструментов, `tools.include/exclude` и лимиты шлюза.
- Точка описания взаимодействия — **каталог MCP** (`gitops/mcp-servers/*/server.json`, `mcp.`): запись в
  каталоге = разрешение, нет записи = нет правила (§5).

## 2. Разрешённый egress — таблица (имена и порты из манифестов, не «по памяти»)

| Назначение | ns / селектор | Порт | L7 | Кому | Зачем |
|---|---|---|---|---|---|
| DNS | `kube-system` / pods `k8s-app=kube-dns` | 53 UDP+TCP | — | оба | имена в конфиге (`*.svc.cluster.local`) |
| Docling MCP | `doc` / `app.kubernetes.io/name=docling` | **8000** | `/mcp` (POST, GET, DELETE) | оба | конверсия PDF/URL |
| Yandex Search MCP | `ysrch` / `app=yandex-search` | **8766** | `/mcp` | оба | поиск внутри контура (не вместо прямого egress) |
| Kuvasz MCP | `monitoring` / `app=kuvasz` | **8080** | `/mcp` | оба (hermes — когда `enabled`) | мониторинг, инциденты |
| GitHub MCP | `mcp-github` / `app.kubernetes.io/name=github-mcp` | **8101** | `/mcp` | оба | код, issues, PR |
| Firecrawl MCP | `fc` / `app=firecrawl-mcp` | **8080** | `/mcp` | оба | страницы, crawl, скриншоты |
| RAGFlow MCP *(план, R1–R8)* | `rag` / `app.kubernetes.io/name=ragflow` | 9380 | `/api/v1/mcp` | оба | знания (после деплоя `rag-spec`) |
| Инференс | `gpustack` (любой под ns) | **30080** | `/v1/.*` | оба | локальные модели (`api.`) |
| Шлюз | `higress-system` (любой под ns) | **443** | — (TLS) | оба | `api.`, `llm-svc.`, `auth.`, `mcp.`, `mon.` |
| Интернет | `ipBlock 0.0.0.0/0` **кроме** кластера и LAN | любой | — | оба | «наружу — как хотят»: `web_fetch`, git, внешние API |

**Явно не разрешено** (это и есть проверки §6): Docling `:5001` (веб-API, агенту не нужен); `fc` —
`nuq-postgres:5432`, `redis:6379`, `rabbitmq:5672`, `playwright-service:3000`, `firecrawl-api:3002`;
`postgres` в `keycloak` и `monitoring`; сервисы `owu`/`spk`/`rag`; `gpustack` `:443`/`:80` (UI) и весь
`/v2/*` (админ-API моделей и ключей); apiserver; поды другого агента. Интернет в этом списке **нет** — он
разрешён целиком.

Почему инференс **напрямую**, а не через `api.`: HTTPS на шлюзе L7-фильтровать нельзя (§7.3), а прямой
`http://gpustack-server-cluster-ip.gpustack.svc:30080/v1` позволяет закрыть `/v2/*` (управление моделями и
ключами) на уровне политики. Внешняя модель (`llm-svc.`) остаётся только через шлюз — там DLP и страж, и
это правильная цена.

## 3. Модель в трёх объектах на namespace

1. **default-deny** — пустой `podSelector`, `Ingress` + `Egress`.
2. **allow** — правила §2. Для MCP и инференса — `CiliumNetworkPolicy` (нужен L7), для DNS и шлюза —
   обычная `NetworkPolicy` (L4 достаточно).
3. **ingress** — в агентский под пускаем только шлюз: `hermes:9119`, `dsh-auth:4180`; `dsh` (3080/4181) —
   только от `dsh-auth`, потому что он и есть вход.

**Наружу — открыто.** Исходящий трафик в интернет не ограничиваем: разрешаем `0.0.0.0/0` с `except` на
кластер, LAN и link-local. Так «не ограничивать внешнее» и «не пускать к соседям» живут в одном правиле без
перечисления доменов: `toFQDNs`/allowlist по именам не нужны, DNS-прокси не требуется. Следствия, которые
надо знать, а не обнаруживать: (1) `git clone` в init-контейнере `dsh` работает как раньше — вынос скиллов
в образ остаётся гигиеной, а не условием W8; (2) прямой вызов внешней модели мимо `llm-svc.` технически
возможен — границу DLP держат не сетью, а отсутствием у агента провайдерских ключей и списком инструментов;
(3) формулировка ARCHITECTURE §6.2 «наружу — только разрешённое и обезличенное» (ADR-0008) для агентских
подов сетью **не обеспечивается**: она держится конфигом (`llm-svc.` как единственный провайдер) и ключами.
Жёсткий запрет прямого egress к провайдеру — отдельное решение (allowlist на ISP/ADR-0008), не эта политика.

**Правило одной цели:** L7-ограничение действует, только если цель **не** описана в L3/L4-политике.
Политики складываются как ИЛИ: `NetworkPolicy` с `port: 8000` + `CiliumNetworkPolicy` с `path: /mcp` дадут
доступ на весь 8000. Поэтому каждая цель — ровно в одном объекте.

### 3.1 `gitops/apps/her/50-networkpolicy.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: agent-default-deny, namespace: her}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# DNS и шлюз — L4 достаточно
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: agent-egress-l4, namespace: her}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: hermes}}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
          podSelector: {matchLabels: {k8s-app: kube-dns}}
      ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]
    - to:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: higress-system}}
      ports: [{protocol: TCP, port: 443}]
    # Наружу — как хотят: весь интернет, кроме кластера, LAN и link-local.
    # 10.0.0.0/8 накрывает pod-CIDR (Cilium cluster-pool), serviceSubnet 10.99.0.0/16
    # (в т.ч. ClusterIP apiserver) и backend p2p 10.20.20.0/26.
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except: [10.0.0.0/8, 192.168.10.0/24, 169.254.0.0/16]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: agent-ingress, namespace: her}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: hermes}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: higress-system}}
      ports: [{protocol: TCP, port: 9119}]
---
# MCP + инференс — единственное место, где живут эти цели (L7)
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: {name: agent-egress-l7, namespace: her}
spec:
  endpointSelector: {matchLabels: {app.kubernetes.io/name: hermes}}
  egress:
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": doc, "app.kubernetes.io/name": docling}
      toPorts:
        - ports: [{port: "8000", protocol: TCP}]
          rules: {http: [{method: POST, path: "/mcp"}, {method: GET, path: "/mcp"}, {method: DELETE, path: "/mcp"}]}
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": ysrch, "app": yandex-search}
      toPorts:
        - ports: [{port: "8766", protocol: TCP}]
          rules: {http: [{method: POST, path: "/mcp"}, {method: GET, path: "/mcp"}]}
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": monitoring, "app": kuvasz}
      toPorts:
        - ports: [{port: "8080", protocol: TCP}]
          rules: {http: [{method: POST, path: "/mcp"}, {method: GET, path: "/mcp"}]}
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": mcp-github, "app.kubernetes.io/name": github-mcp}
      toPorts:
        - ports: [{port: "8101", protocol: TCP}]
          rules: {http: [{method: POST, path: "/mcp"}]}
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": fc, "app": firecrawl-mcp}
      toPorts:
        - ports: [{port: "8080", protocol: TCP}]
          rules: {http: [{method: POST, path: "/mcp"}, {method: GET, path: "/mcp"}]}
    - toEndpoints:
        - matchLabels: {"k8s:io.kubernetes.pod.namespace": gpustack}
      toPorts:
        - ports: [{port: "30080", protocol: TCP}]
          rules: {http: [{method: GET, path: "/v1/.*"}, {method: POST, path: "/v1/.*"}]}
```

Для `dsh` тот же файл с заменой `namespace: dsh` и `endpointSelector: {app.kubernetes.io/name: dsh}`, плюс
блок §3.2. Добавляя RAGFlow — строка `rag` / `ragflow:9380` / `path: /api/v1/mcp` в этот же CNP.

### 3.2 `dsh`: вход и init-контейнер

```yaml
# вход: шлюз → oauth2-proxy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: agent-ingress, namespace: dsh}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: dsh-auth}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: higress-system}}
      ports: [{protocol: TCP, port: 4180}]
---
# dsh-auth — к dsh (3080/4181) и в шлюз (discovery/JWKS auth.)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: dsh-serving, namespace: dsh}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: dsh}}
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: {matchLabels: {app.kubernetes.io/name: dsh-auth}}
      ports: [{protocol: TCP, port: 3080}, {protocol: TCP, port: 4181}]
```

**Init-контейнер `seed-skills` делает `git clone` с github.com** — и это больше не блокер: egress наружу
открыт (§3), клон идёт как раньше. Вынос скиллов в образ (пин коммита при сборке) или в ConfigMap остаётся
рекомендацией по гигиене — меньше сети в старте и воспроизводимее сборка, — но W8 от него не зависит.

## 4. Ingress на самих MCP-серверах (иначе периметр односторонний)

Пока у MCP-серверов нет ingress-политик, звать их может **любой** под кластера. С тем же коммитом, что и
§3, каждой цели добавляется «кто может»:

| Цель | Кто пускается | Порт | Что остаётся публичным |
|---|---|---|---|
| `docling` (`doc`) | `her/hermes`, `dsh/dsh` | 8000 | шлюз → 5001 (сервис `doc.` для людей) |
| `yandex-search` (`ysrch`) | те же | 8766 | шлюз → `/mcp` (LAN-гейт E9) |
| `kuvasz` (`monitoring`) | те же | 8080 | шлюз → UI/`/mcp` по LAN-гейту |
| `github-mcp` (`mcp-github`) | те же | 8101 | ничего: ClusterIP-only |
| `firecrawl-mcp` (`fc`) | те же | 8080 | ничего: ClusterIP-only |
| `gpustack-server` | те же | 30080 | шлюз → 30080 (`api.` для людей) |

## 5. Инвариант каталога (что проверять в ревью)

1. **Запись в каталоге → правило.** Новый MCP-сервер: `gitops/mcp-servers/<имя>/server.json` + строка в §2 +
   правило в CNP агентов + ingress-правило на сервере — **один коммит**.
2. **Нет записи → нет правила.** Правило для сервиса, которого нет в каталоге, — ошибка ревью: агент не
   должен видеть то, что не опубликовано.
3. **Порт — только опубликованный.** У сервиса может быть несколько портов (Docling 5001/8000): в правило
   идёт тот, который указан в `config.yaml` агента, не «соседний».
4. Сверка при внедрении: список `ns:port` из `CiliumNetworkPolicy` должен совпадать с `remotes` каталога и
   с `mcp_servers.*.url` в конфигах обоих агентов (сейчас: `her` — 4 записи + `kuvasz` в резерве,
   `dsh` — 5). Автоматическую сверку (`scripts/netpol_check.py`) пока делаем руками; когда появится скрипт,
   это станет гейтом перед коммитом.

## 6. Приёмка: что обязано открыться и что обязано упасть

Проверка порта без `nc` (в образах его нет):

```bash
P='import socket,sys;s=socket.socket();s.settimeout(3);sys.exit(s.connect_ex((sys.argv[1],int(sys.argv[2]))))'
# открыто → rc=0; заблокировано → rc≠0 (обычно 110, таймаут drop'а)
kubectl -n her exec deploy/hermes -- python3 -c "$P" docling.doc.svc.cluster.local 8000   # 0
kubectl -n her exec deploy/hermes -- python3 -c "$P" yandex-search.ysrch.svc.cluster.local 8766  # 0
kubectl -n her exec deploy/hermes -- python3 -c "$P" postgres.keycloak.svc.cluster.local 5432    # ≠0
kubectl -n her exec deploy/hermes -- python3 -c "$P" docling.doc.svc.cluster.local 5001          # ≠0
kubectl -n her exec deploy/hermes -- python3 -c "$P" nuq-postgres.fc.svc.cluster.local 5432      # ≠0
kubectl -n her exec deploy/hermes -- python3 -c "$P" 10.99.0.1 443                               # ≠0 (apiserver, serviceSubnet 10.99.0.0/16)
kubectl -n her exec deploy/hermes -- curl -m5 -sS -o /dev/null -w '%{http_code}\n' https://example.com   # 200 — наружу открыто
kubectl -n dsh exec deploy/dsh -- curl -m5 -sS -X POST http://docling.doc.svc.cluster.local:8000/mcp \
  -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}' | head -c 200   # 200/итог initialize
```

L7 проверяется отдельно: запрос на разрешённый порт, но **другой путь** должен упасть —
`curl -m3 http://docling.doc:8000/health` (вне `/mcp`) и `curl -m3 http://gpustack-server-cluster-ip.gpustack:30080/v2/models`
(админ-API моделей). Вердикты — `hubble observe --namespace her --verdict DROPPED` и
`cilium status | grep -i policy`.

Что должно упасть **снаружи** агента: `kubectl -n owu exec … docling.doc:8000` — MCP-порты видны только
двум агентам (§4). Отсутствие этого пункта — самая частая дырка: периметр настроен, а сервер открыт всем.

## 7. Грабли

1. **DNAT.** Правило пишем на поды цели (`namespaceSelector`+`podSelector`), не на ClusterIP. Это работает
   потому, что балансировка у нас в eBPF: Cilium 1.20.3 с `kubeProxyReplacement=true`, kube-proxy не ставим
   (`k8s-install-spec` §3, F3) — DNAT происходит до политики, и она видит под получателя. Если стенд когда-то
   вернут на iptables/kube-proxy, эти правила перестанут совпадать с ClusterIP — тогда `toServices`
   (L7 для них не будет) либо `toCIDR` на ClusterIP сервисов.
2. **L7 складывается как ИЛИ** (§3): одна цель — один объект политики.
3. **TLS на шлюзе не инспектируется.** На `443` в `higress-system` остаётся только порт: path/host агенту не
   ограничить. Компенсации: служебные хосты закрыты LAN-гейтом (`403` из pod-CIDR, `external-access-spec`
   E9), у `llm-svc.` свой ключ, `/v2` GPUStack вынесен из шлюза в прямой HTTP-путь. Это осознанное
   ограничение, а не недоделка.
4. **`init` и сайдкары делят политику пода.** Отдельную политику контейнеру не задать: сеть одна на под.
   Здесь это не мешает — наружу открыто, `git clone` в init идёт как обычно.
5. **Labels шлюза ставит чарт `higress-core`** и они меняются между версиями — селектор по namespace, а не
   по label пода.
6. **Порядок применения.** Любой: `her` и `dsh` применяются независимо, старту пода внешняя сеть не мешает.
   Единственное — `dsh` в момент применения сделает `rollout`, и агентская сессия оборвётся.
7. **`automountServiceAccountToken: false`** в обоих Deployment — без токена агент не говорит с apiserver
   даже если политику снимут при отладке.
8. **«Наружу открыто» не отменяет DLP, но и не держит его.** Пока в Secret агента нет провайдерских ключей,
   внешняя модель доступна только через `llm-svc.` — по конфигу. Появится ключ в `her-secrets`/`dsh-models`
   — появится и прямой путь мимо маскирования; это проверяется на ревью секретов, а не политикой.

## 8. Внедрение и что осталось

1. `her`: `50-networkpolicy.yaml` (§3.1) → приёмка §6 → строка в `hermes-spec` §7.2 становится «внедрено».
2. `dsh`: §3.1+§3.2 → W8 закрывается (второй пункт W8 — запись вне `/opt/data` — проверяется отдельно);
   перенос скиллов из init в образ — необязательная гигиена, не условие.
3. Ingress-политики MCP-серверов (§4) — тем же коммитом.
4. `cases/README` кейс 06: блокер меняется на «нет» только после §6 (сейчас — «внедрение по этой записке»).
5. После внедрения: добавить §6-проверки в `k8s_health.py` (секция «Периметр агентов») — политика, которая
   не проверяется скриптом, расходится молча.
