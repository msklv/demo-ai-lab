# Health-runbook — слой 1 вручную и восстановление стенда

Точка входа и методология проверки (пять слоёв, критерии «что считать фактом») —
`architecture/specs/health-check-spec.md`; как устроены и пишутся автоматические чеки —
`scripts/README.md`. Здесь — ручные команды слоя 1 и разбор отказов: power-cycle, VIP, вебхуки, туннель.

Готовый инструмент — два скрипта в репо (оба stdlib-only, `--brief` / `--json`, коды выхода 0/2/1,
SSH-цели сами берут из `ansible/hosts.cluster.yml` + env `K8S0X_USER` или `inventory.local.md`):
- `scripts/k8s_health.py` — кластер: API/VIP → ноды+pressure → health-gate подов → etcd →
  control-plane/kube-vip → Argo/Longhorn/Higress → SSH-замер нод → origin в LAN.
- `scripts/env_health.py` — обвязка: внешняя VM-egress, Cloudflare-туннель через API, внешний путь.

Ручной проход ниже — то, что они делают, и на случай разбора отдельного слоя. Порядок — от кластерного
уровня к физике и внешнему периметру; каждый шаг даёт факты для ответа.

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf   # standalone-копия, контекст demo-ai-lab
```

## Как читать FAIL health-скрипта

Четыре правила, без которых вердикт «кластер мёртв» ложный.

1. **Надгробия после ребута.** Под в `Completed` / `Error` / `ContainerStatusUnknown` на ноде, которая
   перезагружалась раньше, — остаток старого поколения, а не свежая деградация: его замена уже работает
   на другой ноде с большим AGE. Проверить `last -x reboot` на этой ноде и AGE замены; такие объекты
   удалять, иначе health-gate красит кластер в FAIL бесконечно.
2. **Окно power-cycle.** Сразу после включения нод `Terminating` на только что поднявшейся ноде,
   `Pending` без `nodeName`, падение CNI/static-подов — переходное состояние, а не деградация.
   В этом окне `etcd 3/3` и `control-plane …/3` **ложно зелёные** (член etcd числится `started`,
   статические поды держат старый `Running` до ~5 мин grace-периода): вердикт давать только по строкам
   «Ноды» и «Поды». Полный power-cycle сходится сам за ~5–6 мин; дедлок VIP/etcd (§10) наступает не
   всегда — сначала подождать и перепрогнать гейт, VIP руками разрывать только по симптому
   (`.240` не отвечает, а `:6443` на нодах открыт).
3. **Не-ready поды дольше 5–6 мин — читать снизу вверх: admission → CSI → тома.** `longhorn-manager`
   создаёт instance manager'ы обычными подами, и вебхук `failurePolicy: Fail` на мёртвом контроллере
   (kueue: `mpod.kb.io`, CrashLoop из-за отсутствующего CRD `multikueueclusters`) блокирует создание
   подов во всех ns, кроме `kube-system` и `gpustack`: `instancemanager` 4/4 `error`, подов
   `instance-manager` ноль, тома `detached`, Keycloak/GPUStack — `FailedMount`. Дешёвая проба:
   `kubectl -n longhorn-system run probe --image=busybox:1.36 --restart=Never --dry-run=server -- true`;
   ответ `failed calling webhook` и есть корень. Лечение — §10a (поставить недостающий CRD), не `Ignore`.
4. **Сначала проверить, что консоль в сети стенда.** Иначе весь FAIL-набор ложный:
   `ipconfig getifaddr en0` + одновременный `ping` по `.1` (MikroTik), `.230` (origin), `.240` (VIP).
   Адрес API не угадывать по списку нод — он в kubeconfig (`grep 'server:' ~/.kube/demo-ai-lab.conf`),
   пинговать именно его. **На macOS нет `timeout`**: `bash: timeout: command not found` даёт тот же
   `rc≠0`, что мёртвый API, — сначала читать stderr. Порт проверять `nc -zv -G 3 <ip> <port>` или
   `curl -m 5`, а не `timeout 3 bash -c '... /dev/tcp ...'` (печатает `no` для всех портов). Если мертвы
   все три адреса сразу — виноват путь консоли (другая подсеть), а не кластер: «API недоступен»,
   «SSH недоступен на всех нодах», «origin 000» — одна причина, а не три. Внешнюю сторону проверять
   через anycast `--resolve`, минуя split-DNS (иначе `curl https://<host>/` падает за 3 мс и ничего
   не доказывает); `502` от Cloudflare = туннель жив, origin не отвечает.

## 1. Ноды и pressure

```bash
kubectl get nodes -o wide
kubectl get nodes -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,MEMPRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status,DISKPRESSURE:.status.conditions[?(@.type=="DiskPressure")].status,PIDPRESSURE:.status.conditions[?(@.type=="PIDPressure")].status'
```

## 2. Health-gate подов (критерий владельца)

```bash
kubectl get pods -A --no-headers | grep -vE ' ([0-9]+)/\1 +(Running|Completed)' || echo "OK"
```

Пусто = все поды живы. Считать так, а не глазами по `-o wide`.

## 3. Поды по нодам + рестарты

```bash
kubectl get pods -A -o custom-columns='NODE:.spec.nodeName' --no-headers | sort | uniq -c | sort -rn
kubectl get pods -A --no-headers -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,RESTARTS:.status.containerStatuses[*].restartCount' | sort -k3 -nr | head -5
```

Сумма по нодам обязана равняться общему числу подов — расхождение значит, что колонка взята
не та (см. «грабли» ниже).

## 4. etcd

```bash
kubectl -n kube-system exec -i etcd-k8s-01 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key member list -w table
```

Ожидание: 3 члена `started`, IS LEARNER=false.

## 5. Argo, Longhorn, VIP

```bash
kubectl -n argocd get applications                    # root-app + infra: Synced/Healthy
kubectl -n longhorn-system get nodes.longhorn.io -o custom-columns='NODE:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,ALLOWSCHED:.spec.allowScheduling'
kubectl -n longhorn-system get volumes.longhorn.io     # пусто = томов ещё нет, это норма
kubectl get pods -A -o wide --no-headers | grep -Ei 'higress|kube-vip'
```

`k8s-01` в Longhorn — `ALLOWSCHED=false` by design (диск не в пуле), не рапортовать как деградацию.

### 5a. Служебные UI (`argo.`/`hgc.`/`lng.`) и allowlist

Правило: только LAN (`architecture/specs/external-access-spec.md` E9.2). Два `WasmPlugin`
`ip-restriction` + том `wasm-store` в `higress-system`.

```bash
kubectl -n higress-system get wasmplugin lan-only-ui lan-only-ui-lan-source
kubectl -n higress-system get pods -l app=wasm-store
scripts/infra_wasm_plugins.sh --check          # файл в томе + отдача по spec.url
curl -s -o /dev/null -w '%{http_code}\n' https://lng.demo-ai-lab.ru/     # из LAN → 401 (логин включён)
```

Симптомы и что это значит:

| Симптом | Причина | Действие |
|---|---|---|
| `argo.`/`hgc.`/`lng.` из LAN → `500`, в логах gateway `Plugin configured to fail closed failed to load` | конфиг правила пустой/невалиден, либо wasm не скачался | `scripts/infra_wasm_plugins.sh --check`; в `lan-only-ui.yaml` проверить, что у каждого `matchRules` есть блок `config` (без него плагин не загружается) |
| `lng.` из LAN → `200` без логина | пропал `WasmPlugin longhorn-ui-basic-auth` (живёт вне Argo — `scripts/longhorn_ui_auth.sh`) | `scripts/longhorn_ui_auth.sh --check`, затем без флагов (пересоздаст объект из `lng-admin.local.md`) |
| `lng.` из LAN → `401` | норма: так и должно быть (Basic Auth, `external-access-spec` E9.3) | пароль — `lng-admin.local.md`; забыли/утекли — `scripts/longhorn_ui_auth.sh --rotate` |
| из LAN `200`, но и через edge `200` | плагина нет / он выключен — админка открыта | `get wasmplugin` (оба объекта есть?), `bash scripts/infra_wasm_plugins.sh --check`, при необходимости `kubectl apply -f gitops/infra-apps/infra/lan-only-ui.yaml` |
| `403` на пользовательском хосте (`owu.`, `doc.`, `mcp.`) через edge | allowlist попал в `defaultConfig` — а он глобальный на весь шлюз | перенести конфиг в `matchRules[].config`, `defaultConfigDisable: true` |
| из LAN `403` | в списке правила нет адреса клиента (новый сегмент LAN) | добавить диапазон в `matchRules[].config` **обоих** объектов, кроме `172.16.0.0/12` |

Быстрый признак, что 403 пришёл от нашего правила, а не от края Cloudflare: тело
`{"message":"LAN only"}` и в логе gateway `response_code: 403` с `route_name` хоста; у края тело —
HTML-страница CF с `server: cloudflare`.

## 6. Живой замер нод по SSH

```bash
for h in <user>@192.168.10.250 <user>@192.168.10.253 <user>@192.168.10.254 <user>@192.168.10.252; do
  ssh -o BatchMode=yes -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new $h '
    printf "%s up=" $(hostname); cut -d. -f1 /proc/uptime
    cut -d" " -f1-3 /proc/loadavg
    free -g | awk "/Mem:/{printf \"ram=%sG avail %sG\n\", \$2, \$7}"
    df -h / | awk "NR==2{printf \"root=%s used %s\n\", \$2, \$5}"
    systemctl is-active cloudflared 2>/dev/null | sed "s/^/cloudflared=/"' 2>&1
done
```

Логины нод — из `ansible/hosts.cluster.yml` (env `K8S0X_USER`) / `inventory.local.md`; у 04 отдельного
юзера нет (логин как у 03). `cloudflared` на 02/03 выведен (`disable --now`, E7) — коннектор на внешней VM
(см. `env_health.py`); `inactive` здесь — норма.
GPU (только 04): `nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader`.

## 7. Ребуты и их характер

```bash
ssh <node> 'uptime -s; journalctl --list-boots | tail -3; journalctl -b -1 -n 6 --no-pager | tail -6'
```

- В конце прошлого boot'а **нет** последовательности `Reached target … shutdown/poweroff`, лог
  обрывается на бытовой строке ⇒ питание пропало (жёсткое отключение), а не graceful reboot.
  `last -x reboot` показывает записи о ЗАГРУЗКЕ, доказательством чистого ребута не является.
- **Ноды живут в UTC** (`journalctl`, `uptime -s`, `last`), консоль — MSK: пересчитывать +3,
  иначе инцидент датируется на три часа неверно.
- Пару «умер/поднялся» брать по последней строке boot −1 и первой boot 0, а не по load average.

## 8. Зависший kernel-thread (высокий load при простое)

```bash
ssh <node> 'cat /proc/loadavg; ps -eo pid,pcpu,comm,args --sort=-pcpu | head -5'
ssh <node> 'awk "{print \$14+\$15}" /proc/<pid>/stat; sleep 3; awk "{print \$14+\$15}" /proc/<pid>/stat'
```

Прирост ~300 тиков за 3 с = 100% одного ядра, поток в state `R` (`wchan=0`). Идентификация очереди
(`/proc/<pid>/stack`, `dmesg`) требует root: `kernel.dmesg_restrict=1` на нодах — без sudo не гадать,
а честно назвать гипотезу и спросить разрешение на root-проверку.

## 9. Внешний путь и origin

```bash
for i in 1 2 3 4 5 6; do curl -s -o /dev/null -w "%{http_code} " --max-time 10 https://demo-ai-lab.ru/; sleep 2; done; echo
curl -sk -o /dev/null -w 'lan230 https=%{http_code}\n' --resolve demo-ai-lab.ru:443:192.168.10.230 https://demo-ai-lab.ru/
```

Разбор кодов edge: **502** — коннектор ответил, но не дотянулся/не прошёл TLS до origin;
**530 `error code: 1033`** — здоровых коннекторов нет; **200** — сквозной путь цел.
Отличать R1 (шторм канала коннектор→edge) от поломки origin'а: если origin из LAN (`--resolve … :443:192.168.10.230`)
отдаёт 200, а edge флапает 502/530 — виноват канал, а не кластер. Серия из ≥6 запросов обязательна:
одиночный 502 ничего не доказывает, одиночный 200 тоже.
- Тело ошибки печатать (`curl -s … | sed 's/<[^>]*>/ /g'`): `error code: NNNN` сразу говорит, чей это слой.
- Сертификат origin: `echo | openssl s_client -connect 192.168.10.230:443 -servername demo-ai-lab.ru | openssl x509 -noout -subject -issuer -dates`.

## 9a. Туннель по API (когда edge 530/502, а коннекторы «Registered»)

Проверяется `scripts/env_health.py` (Cloudflare API: status туннеля, число соединений, colo, сверка egress
коннектора с адресом внешней VM). Ручной разбор ниже — как читать то, что он печатает.

`status=down, conns=0` при локальных `INF Registered tunnel connection` = коннекторы не
дорегистрировались в control plane (R1) → 530/1033 у edge. С E7 коннектор живёт на внешней VM
(SberCloud): рестарт — `systemctl restart cloudflared` там (не на 02/03 — там сервис `disable --now`).
DNS CNAME должен указывать на `<id>.cfargotunnel.com` и быть proxied; ingress-конфиг (v3) —
`https://127.0.0.1:19443` (haproxy на VM) + `originServerName` + `caPoolPath`.

**Когда лечить пересозданием объекта (проверено 2026-10-23).** Признак «объект туннеля испорчен»:
локально `INF Registered tunnel connection`, а API отдаёт `status=down/degraded`, счётчик соединений
0–1, edge 530/502 — и это НЕ лечится рестартом и пере-отправкой конфига. Отличать от инцидента CF так:
создать одноразовый туннель тем же API и поднять коннектор его токеном с той же машины; если тестовый
туннель healthy, а рабочий — нет, виноват объект: новый туннель → PUT конфига → проверить коннектором
ДО DNS → переключить CNAME → новый токен на коннекторе → рестарт → удалить старый и диагностический.
**Приёмка только с коннектора/внешней точки:** консоль Mac выходит в CF через ZTN и попадает в другой
colo — `curl` с неё даёт 502 при полностью живом туннеле.

## 10. Восстановление после полного обесточивания (power-cycle всех нод)

Кластер сам НЕ выходит из этого состояния. Симптом на консоли: `kubectl` →
`192.168.10.240:6443: no route to host`, все ноды пингуются, `ss -ltn` на 01 даёт только
`:2379/:2380` (apiserver нет), `kube-apiserver-*` в CrashLoopBackOff.

**Мёртвый VIP не мешает прочитать состояние** — тот же kubeconfig с override адреса на нодовый
apiserver (креды и контекст сохраняются, проверка TLS снимается):
`kubectl --kubeconfig ~/.kube/demo-ai-lab.conf --server=https://192.168.10.254:6443 \
--insecure-skip-tls-verify get nodes`. При кворуме 2/3 API живёт на нодовых адресах — мёртв только
VIP, и это видно по тому, что `:6443` открыт на нодах, а `.240` нет. До любых изменений так
снимаются ноды/поды/кворум/лизы — чтобы в отчёте были факты, а не догадки.

**Сначала отделить «нода не включалась» от «нода уехала по DHCP»** — иначе лечишь не то.
`GET /rest/ip/dhcp-server/lease` на роутере: `status=waiting` + пустой `active-address` + `last-seen`
в часах/сутках = нода НЕ выходила в сеть (питание/кнопка; WoL на стенде нет). `status=bound`, но адрес
другой = уехала по DHCP (тогда см. «Найти нового хоста»). ARP-таблицы для вердикта мало: MAC может
остаться в `/interface/bridge/host` динамической записью ещё несколько минут после выключения ноды.

Причина — двойной дедлок:
1. **etcd-поды стартуют раньше выдачи DHCP-адреса**: `fatal … listen tcp 192.168.10.25X:2380:
   bind: cannot assign requested address` → CrashLoopBackOff. Первая нода с живым etcd кворума не даёт.
2. **kube-vip ходит в API через VIP**: `/etc/kubernetes/admin.conf` → `server: https://192.168.10.240:6443`,
   а VIP держит только избранный лидер kube-vip → все инстансы падают (`could not create k8s REST
   config from external file`), VIP не появляется, kubelet на k8s-04 не регистрируется (он тоже на .240).

Лечение (проверено 2026-10-23):

```bash
# 1) дождаться, пока etcd на 01 и 03 выйдут из backoff (кворум 2/3) — API на нодовых адресах :6443
# 2) разорвать дедлок VIP вручную на одном CP-узле — kube-vip сразу дорегистрируется и заберёт адрес
ssh <cp-node> 'sudo ip addr add 192.168.10.240/32 dev eno1'
# 3) убедиться, что kube-vip стал лидером (lease plndr-cp-lock) и адрес переехал в его руки
kubectl -n kube-system get lease plndr-cp-lock     # HOLDER
# 4) снять ручной адрес — иначе два держателя VIP (ARP-конфликт)
ssh <тот же cp-node> 'sudo ip addr del 192.168.10.240/32 dev eno1'
# 5) kube-vip-* в CrashLoopBackOff после этого перезапустить (манифест-под): delete pod → kubelet пересоздаст
kubectl -n kube-system delete pod kube-vip-k8s-01 --wait=false
# 6) cloudflared на внешней VM — рестарт (иначе туннель в CF API висит down при живом коннекторе)
# 7) дождаться, пока longhorn-csi-plugin/longhorn-manager/csi выйдут из backoff сами (~3–5 мин)
```

Проверка после: `.240` и `.230` на разных узлах, `kubectl get nodes` = 5×Ready, health-gate пусто,
Longhorn `Ready=true` на всех нодах (у k8s-01 и k8s-05 `SCHED=false` by design), Argo Synced/Healthy.
`sudo` на нодах — пароль из локального приватного хранилища; `sudo -S` читает пароль со stdin, поэтому
на несколько команд в одном ssh-вызове пароль подавать **в каждый** вызов или объединять их в один
`sudo bash -c "..."` (иначе второй получает «no password was provided»).

### 10a. Вебхук с `failurePolicy: Fail` на мёртвом контроллере блокирует ВСЁ создание подов

Симптом после power-cycle (проверено 2026-10-27): ноды `Ready`, etcd/control-plane в норме, но Longhorn
не поднимается — `instancemanager` 4/4 `error`, **подов `instance-manager` нет вообще**, тома
`detached`/`unknown`, `longhorn-driver-deployer` в CrashLoop с `fatal`, Postgres/Keycloak/GPUStack висят
на `FailedMount` (`driver name driver.longhorn.io not found in the list of registered CSI drivers`),
воркеры GPUStack — `Failed to register worker: [Errno -2] Name or service not known`. Гейт показывает
3–4 FAIL сразу в подах, Ingress и origin, и легко уйти искать несуществующую проблему в самом Longhorn.

Причина одна: цепочка **admission → CSI → тома**. `longhorn-manager` создаёт instance manager'ы обычными
подами в `longhorn-system`, а mutating-вебхук kueue (`mpod.kb.io`, `failurePolicy: Fail`, исключены
только `kube-system`/`gpustack`) не может ответить, потому что `kueue-controller-manager` в CrashLoop
(`Unable to setup indexes: no matches for kind "MultiKueueCluster" in version kueue.x-k8s.io/v1beta2` —
в установленном наборе CRD нет `multikueueclusters`). Без instance manager'ов нет CSI → ни один PVC не
монтируется → валится всё, что стоит на Longhorn.

Быстрая диагностика (не трогая состояние):
```bash
kubectl -n longhorn-system run webhook-probe --image=busybox:1.36 --restart=Never --dry-run=server -- true
# Error from server (InternalError): failed calling webhook "mpod.kb.io": …
#   dial tcp 10.99.208.133:443: connect: no route to host   → это и есть корень
kubectl -n longhorn-system get pods | grep -c instance-manager    # 0
kubectl -n gpustack logs deploy/kueue-controller-manager --tail=30 | grep -i 'unable to setup'
```

Лечение (проверено 2026-10-27, 15 минут до зелёного гейта) — **чинить причину, а не снимать вебхук**:
```bash
# 1) какой CRD не хватает — сверить установленный набор с релизом kueue той же версии
kubectl get crd | grep -o '^[a-z]*\.kueue\.x-k8s\.io' | cut -d. -f1
#    было: admissionchecks clusterqueues cohorts localqueues multikueueconfigs resourceflavors
#          topologies workloadpriorityclasses workloads   (нет multikueueclusters)
# 2) поставить недостающий CRD из тега, совпадающего с gitVersion контроллера (здесь v0.17.6)
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/kubernetes-sigs/kueue/v0.17.6/config/components/crd/bases/kueue.x-k8s.io_multikueueclusters.yaml
# 3) контроллер выходит из CrashLoop сам (deployment пересоздаёт под) → kueue 1/1 Running
# 4) instance manager'ы Longhorn появляются в пределах ~2 мин (ретрай longhorn-manager = 2m)
#    → тома `attached/healthy` → postgres → keycloak → gpustack-server → gpustack-worker
```
`provisioningrequestconfigs` из того же релиза ставить не нужно: без cluster-autoscaler контроллер это
место пропускает сам (`Skipping admission check controller setup: Provisioning Requests not supported`).

**Не оставлять `failurePolicy: Ignore` как «починку»**: поды начинают создаваться, но `kueue` продолжает
CrashLoop, гейт красится в FAIL вечно, а первый же `helm upgrade` оператора вернёт `Fail` и снова
заморозит создание подов. `Ignore` допустим только как временная мера на время работ — и тогда
обязательно вернуть `Fail` после того, как у вебхука появился живой бэкенд, и проверить приёмкой:
`kubectl -n longhorn-system run webhook-probe --image=busybox:1.36 --restart=Never -- sleep 5` (под
должен реально создаться и уйти в `Running`).

Higress-gateway после power-cycle в этом сценарии поднимается **сам** (`Readiness succeeded in 27m20s`):
envoy не смог скачать wasm-плагины в момент загрузки, но повторяет попытку — рестарт деплоймента не нужен,
достаточно дождаться.

## 10b. Шлюз Higress: авария Envoy (fd) и OOM — «отвалились все сервисы»

Симптом со стороны пользователя: одновременно пропадают **все** хосты `*.demo-ai-lab.ru` (VIP `.230`),
в приложениях — `Server disconnected` (например, загрузка файла в OWU: `status=failed`).

```bash
kubectl -n higress-system get pods -l app=higress-gateway \
  -o custom-columns='N:.metadata.name,NODE:.spec.nodeName,READY:.status.containerStatuses[0].ready,R:.status.containerStatuses[0].restartCount,LAST:.status.containerStatuses[0].lastState.terminated.reason'
kubectl -n higress-system logs <pod> --previous | grep -E "Too many open files|xds-grpc closed|exited with error" | tail -5
# лимиты внутри пода (envoy — дочерний процесс, у pid 1 другие)
kubectl -n higress-system exec <pod> -- sh -c 'for x in $(ls /proc | grep -E "^[0-9]+$"); do
  [ "$(cat /proc/$x/comm)" = envoy ] && grep "Max open files" /proc/$x/limits; done'
```

Признаки и что это значит:

| В логе / статусе | Что случилось | Куда |
|---|---|---|
| `envoy assert … socket(2) failed, got error: Too many open files` + `Envoy exited with error: signal: aborted` | кончился `RLIMIT_NOFILE` контейнера (дефолт containerd 1024); все коннекты через этот под рвутся мгновенно | норма `8192 8192`; как поднимается — `architecture/specs/k8s-install-spec.md` F8 |
| `OOMKilled` при RSS 2.5–4.2 GiB | лимита памяти пода не хватило: холодный старт тянет `pilot-agent` до 2.4 GiB + envoy до 1.75 GiB в одном cgroup | лимит держать `6Gi` (F8), иначе поды флапают при каждом пересоздании |
| `StreamAggregatedResources … closed since Ns … 10.99.100.0:15012: connect: no route to host` | шлюз без xDS: единственный `higress-controller` был на ребутнувшейся ноде, конфиг устарел → `NR/filter_chain_not_found` на чужих SNI | дождаться контроллера (`kubectl -n higress-system get pods higress-controller`); лечение причины — F8 п.3 |
| под в `Terminating` минутами, новый — `Pending` (antiaffinity ждёт ноду) | envoy дренируется/залип | `kubectl delete pod … --grace-period=0 --force`, затем дождаться `2/2 Ready` |
| приложение получает `413 Payload Too Large` на `llm.`/`llm-svc.` (OWU показывает «Payload Too Large» в диалоге), в access-логе `response_code_details=request_payload_too_large` | тело запроса больше лимита буфера слушателя: плагины маршрута (OPA/DLP/страж) читают JSON целиком, Envoy буферизует его до `downstream.connectionBufferLimits`; чартовый дефолт — 32 КиБ по HTTP/1.1 и 65 535 B по HTTP/2. Клиенты на HTTP/1.1 (aiohttp/OWU) упираются первыми | лимит держать `1 МиБ` (`1048576`) в `higress-config`, замеры и правка — `architecture/specs/llm-proxy-spec.md` §2.1 |
| приложение падает `FileNotFoundError: No usable temporary directory … /tmp` или любая ошибка записи в `/` сразу после правки containerd | контейнер создан с **read-only корнем** или другим битым базовым спеком: `base_runtime_spec` собран из `runc spec` без `root.readonly=false` / без `process.cwd` | вернуть `base_runtime_spec = ''`, `systemctl restart containerd`, пересоздать затронутые поды; полный разбор — §10d |

Общее правило: пересоздавать поды шлюза **по одному** и ждать `1/1` у замены — при двух репликах
и `externalTrafficPolicy: Local` клиенты с ноды без готового шлюза получают отказ.

## 10c. Консольный Prometheus: `OOMKilled` в цикле и переполненный том

Симптом в health-скрипте: `Health-gate подов` → `higress-system/higress-console-prometheus-… (0/1 ready)`,
в `Рестартах контейнеров` у него десятки рестартов; при этом шлюз, Argo и все сервисы живы —
консоль теряет только метрики o11y (`/prometheus/`, `/grafana/` на `hgc.`).

```bash
kubectl -n higress-system get pod -l app.kubernetes.io/name=higress-console-prometheus \
  -o jsonpath='{.items[0].status.containerStatuses[0].lastState}{"\n"}'      # ждём OOMKilled/exit 137
kubectl -n higress-system get pvc higress-console-prometheus -o wide          # capacity vs requests
kubectl -n longhorn-system get volumes.longhorn.io <volume> \
  -o jsonpath='size={.spec.size} actual={.status.actualSize}{"\n"}'           # actual > size = том полон
kubectl -n higress-system logs <pod> --previous | grep -E "WAL segment loaded|preallocate|no space" | tail -5
```

Механика отказа (проверено 2026-11-06): том упирается в 100 % → компакция не идёт → WAL растёт
(286 сегментов) → каждый рестарт грузит весь WAL в память (replay 76k серий ≈ 4 GiB) → `OOMKilled`
→ WAL снова не компактится. Это **не** нехватка памяти сама по себе: без свободного места на томе
лимит не поможет.

Лестница лечения:

1. Расширить PVC (Longhorn `allowVolumeExpansion: true`, живой resize без даунтайма):
   `kubectl -n higress-system patch pvc higress-console-prometheus -p '{"spec":{"resources":{"requests":{"storage":"10Gi"}}}}'`
   — `FileSystemResizeSuccessful` в событиях пода подтверждает, что ФС догнала размер.
2. Поднять лимит памяти до `6Gi` (компакция 76k серий держит ≈4,2 GiB RSS) и CPU до `2`
   (пик на старте ≈1 ядро):
   `kubectl -n higress-system set resources deploy/higress-console-prometheus --limits=cpu=2,memory=6Gi --requests=cpu=500m,memory=2Gi`.
   После правки — `rollout status`, рестарт контейнера означает, что лимита всё ещё мало.
3. Только если после этого повторится — резать кардинальность (убрать джоб `k8s_nodes`/cadvisor
   из ConfigMap `higress-console-prometheus`), это ломает node-дашборды консоли. Дефолтный рецепт
   держать ресурсы в `ansible/values-higress-console.yaml`, а `helm upgrade` консоли делать осознанно:
   чарт вернёт свои `storage`/`resources`.

## 10d. `base_runtime_spec`: ноды живы, но любой новый контейнер не стартует (инцидент 04.11–08.11.2026)

Симптомы по слоям: health-gate красит поды Longhorn/шлюза/сервисов **на 02 и 03**; в статусах
`StartError: failed to create containerd task: OCI runtime create failed: runc create failed:
Cwd property must not be empty` (exit 128, контейнер при этом не создаётся вообще);
`longhorn-manager`/`longhorn-global-manager` в CrashLoopBackOff, `instance-manager` `Unknown`,
CSI-сайдкары Error; kube-vip-поды в `Running`, но лиз `plndr-cp-lock` держит **одна и та же identity**
на двух нодах → `.240`/`.230` висят на 02 и 03 одновременно (ARP-конфликт в `k8s_health.py`).

Бросается в глаза `hostname` ноды = `runc`, хотя `/etc/hostname` = `k8s-0X`: это не «сбилось имя»,
а следствие того же файла.

Причина: на нодах включён `base_runtime_spec = '/etc/containerd/base-ulimits.json'`
(правка 04.11 ради fd-лимита Envoy; F8 ставил этот путь как «рабочий» — отклонён, см. спеку).
В спеке:
1. **нет `process.cwd`** → runc 1.3 отклоняет создание любого нового контейнера;
2. `"hostname": "runc"` из шаблона `runc spec` уезжает в UTS песочницы hostNetwork-подов
   (kube-vip, cilium) → `sethostname("runc")` на **самой ноде**;
3. caps CRI берёт **не** из базового спека: `CapEff=0` у контейнеров, root без `CAP_FOWNER/CHOWN`
   → postgres-поды падают `chmod: changing permissions of '/var/lib/postgresql/data/pgdata':
   Operation not permitted`.

Диагностика (ничего не меняя):
```bash
grep -n base_runtime_spec /etc/containerd/config.toml                # на всех нодах
grep -nE '"(cwd|hostname|noNewPrivileges)"' /etc/containerd/base-ulimits.json
kubectl -n longhorn-system get pod longhorn-manager-XXXX \
  -o jsonpath='{range .status.containerStatuses[*]}{.lastState.terminated.message}{"\n"}{end}'
hostname; cat /etc/hostname                                          # расходятся → тот же корень
kubectl get lease -n kube-system plndr-cp-lock -o jsonpath='{.spec.holderIdentity}'   # не имя ноды?
```

Лечение (проверено 2026-11-08, 02 и 03):
```bash
sudo sed -i "s|base_runtime_spec = '/etc/containerd/base-ulimits.json'|base_runtime_spec = ''|" \
  /etc/containerd/config.toml && sudo systemctl restart containerd
sudo hostnamectl set-hostname k8s-0X                # вернуть kernel hostname (static в /etc/hostname уже верный)
kubectl -n kube-system delete pod kube-vip-k8s-02 kube-vip-lb-k8s-02 kube-vip-k8s-03 kube-vip-lb-k8s-03
#   старые процессы могут пережить удаление пода: pgrep -af 'kube-vip manager' → kill <pid>
#   иначе лиз продолжает держать identity 'runc' и VIP остаётся на двух узлах
kubectl -n longhorn-system delete pod -l app=longhorn-manager --field-selector spec.nodeName=k8s-02
kubectl -n longhorn-system rollout restart deploy csi-attacher csi-provisioner csi-resizer csi-snapshotter
#   затем пересоздать залипшие сервисные поды (postgres → keycloak, registry, gpustack-server/worker)
```

Приёмка: `hostname` на нодах = `k8s-0X`; `plndr-cp-lock`/`plndr-svcs-lock` держит имя ноды;
VIP `.240`/`.230` — по одному держателю (на лидере; в норме могут быть на одном узле — главное
не два); тест-под на ноде: `ulimit -Sn`/`-Hn` = `1024`/`524288`, `grep CapEff /proc/self/status`
ненулевой, `chown 999:999 /tmp/t` проходит; `k8s_health.py --brief` → 0 FAIL.

Правило: **`base_runtime_spec` на стенде не использовать.** `default_ulimits` в containerd 2.2
не существует (ключ игнорируется), а базовый спек управляет cwd/hostname/caps/root и ломает ноду
целиком при каждом пересоздании подов. Дефолтные `RLIMIT_NOFILE` (1024 soft / 524 288 hard) Envoy
поднимает себе сам (F8).

## 11. GPU-телеметрия: dcgm-exporter (ns `monitoring`)

Установлено 2026-11-10: телеметрия RTX 5070 Ti на k8s-04 в Prometheus консоли + дашборд Grafana
`demoai-gpu`. Спека — `architecture/specs/monitoring-spec.md`, манифест —
`gitops/infra-apps/monitoring/40-dcgm-exporter.yaml`, скрейп-job — `scripts/prometheus_dcgm_job.py`,
дашборд — `scripts/grafana_import_dashboard.py`. Ниже — разбор на случай «под не стартует», «серия
исчезла», «панель пустая».

### 11a. Объект в ns `monitoring` исчезает через ~30 с после `kubectl apply`

ns под Argo CD (Application `monitoring`, `automated: {prune: true, selfHeal: true}`): всё, чего нет в
`origin/main`, вычищается. Симптом обманчив — `apply` печатает `created`, через полминуты `NotFound`,
событий нет, логов нет. Это не сломанный образ и не admission.

- временная валидация — **вне** Argo-пути (`-n default`, другое имя), после проверки снести;
- боевое размещение — только через git: правка в `gitops/infra-apps/monitoring/`, push в `main`, затем
  `kubectl -n argocd annotate application monitoring argocd.argoproj.io/refresh=normal --overwrite`
  (иначе ждать полла до 3 мин: в `status.sync.revision` виден **старый** коммит).

### 11b. Под падает на OCI-спеке: `invalid MIG capability request`

```
failed to create containerd task: ... error modifying OCI spec: failed to create the automatic CDI
modifier: invalid MIG capability request: cannot set NVIDIA_MIG_CONFIG_DEVICES or
NVIDIA_MIG_MONITOR_DEVICES in a non-privileged container
```

С `runtimeClassName: nvidia` containerd подставляет MIG-переменные через CDI и отказывается делать это
для непривилегированного контейнера → нужен `privileged: true`. Обратная сторона: с `privileged: true`
API **не примет** `allowPrivilegeEscalation: false` (`cannot set allowPrivilegeEscalation to false and
privileged to true`) — поле не задавать. `SYS_ADMIN` не нужен: он только для профилировщика
(`DCGM_FI_PROF_*`), счётчики состояния (темп/ватты/VRAM/частоты) читаются без него.

### 11c. Под падает после успешного старта контейнера: конфиг и имена полей

Экспортёр 4.9 работает от конфига, а не от `-f`:

| Сообщение | Причина / лечение |
|---|---|
| `read config file "/etc/dcgm-exporter/config.yaml": no such file or directory` | конфиг обязателен (env `DCGM_EXPORTER_CONFIG_FILE` задан в образе); монтировать `config.yaml` (version 2) в `/etc/dcgm-exporter` |
| `parse config file ... enrichment: unknown key at line N` | `enrichment` вкладывается **внутрь** `metrics[0]`, на верхнем уровне ключа нет |
| `could not find DCGM field; unknown ExporterCounter field 'DCGM_FI_DEV_MEM_TEMP'` | имя поля неверное: правильно `DCGM_FI_DEV_MEMORY_TEMP`; любое несуществующее поле валит старт |
| под `Running`, но `DCGM_FI_DEV_MEMORY_TEMP`/`XID_ERRORS` в `/metrics` нет | GeForce эти датчики не отдаёт — норма, панель остаётся пустой |

Энергия: `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` в **мДж**, растёт монотонно — в ватты переводить
производной (`deriv(...[5m])/1000`), мгновенный `POWER_USAGE` скачет.

### 11d. Job `dcgm_gpu` пропал из Prometheus (после `helm upgrade` консоли)

Конфиг `higress-console-prometheus` **целиком рендерится Helm-чартом** higress-console (шаблон, без
values-хука) — scrape-job в git держать негде, а поставленный вручную `kubectl patch` живёт до ближайшего апгрейда.
Проверка и лечение:

```bash
python3 scripts/prometheus_dcgm_job.py --check   # "OK: job ... настроен" | "DRIFT: job ... отсутствует"
python3 scripts/prometheus_dcgm_job.py           # поставить job + rollout restart + проверка targets
```

Правило: прогонять `--check` после **любого** обновления консоли (`higress_console_upgrade.sh`).
После рестарта Prometheus сначала `503 Service Unavailable` (проигрывает WAL), затем `200` с **пустым**
`activeTargets` до первого скрейпа — это старт, а не поломка (скрипт ждёт до 2 мин).

### 11e. График пустой, а под зелёный — порядок разбора

1. цель `dcgm_gpu` в Prometheus: `/prometheus/api/v1/targets?state=active`, `health=up` (иначе §11d);
2. серии есть: `count({__name__=~"DCGM_FI_DEV_.*"})` → ожидается ~11, свежесть
   `time()-timestamp(DCGM_FI_DEV_GPU_TEMP)` → секунды;
3. окно: дашборд `now-6h`, потому что retention консольного Prometheus — 6h; «за сутки» этой
   инсталляцией не отвечается (нет платформенного Prometheus);
4. дашборд импортирован (`scripts/grafana_import_dashboard.py --check` → `version≥1, panels=12`).

### 11f. Дашборд Grafana: почему только через API

- Провинжининга нет: `/etc/grafana/provisioning/*` пустые, dashboards засеяны в `/var/lib/grafana`
  (PVC), `disable_login_form=true`, анонимный зритель с `org_role: Viewer` — **создать** дашборд из UI
  он не может.
- Креды админа — env `HIGRESS_CONSOLE_DASHBOARD_USERNAME` / `HIGRESS_CONSOLE_DASHBOARD_PASSWORD` у
  `deploy/higress-console` (ими же ходит витрина `hgc.`), в git не попадают.
- Дашборд (`uid demoai-gpu`) хранится в PVC: рестарт пода и `helm upgrade` его не сносят,
  **переустановка Grafana с нуля — сносит**, тогда импорт заново.
- Правка в UI разрешена (`viewers_can_edit=true`), но источник истины —
  `gitops/infra-apps/monitoring/dashboards/gpu-dcgm.json`: следующий импорт перезапишет UI-правку.
  У Application `monitoring` нет `directory.recurse` — JSON в подкаталоге Argo не парсит.

### 11g. Приёмка за четыре команды

```bash
kubectl --context demo-ai-lab -n monitoring get ds,pod -l app=dcgm-exporter -o wide   # 1/1 Running на k8s-04
python3 scripts/prometheus_dcgm_job.py --check                                        # target health=up
python3 scripts/grafana_import_dashboard.py --check                                   # demoai-gpu: есть
python3 scripts/k8s_health.py --brief                                                 # 0 FAIL
```

## Грабли (проверено живым прогоном)

- `kubectl get pods -A -o wide --no-headers | awk '{print $8}'` даёт **AGE, а не NODE** (при `-A`
  колонок больше). Поды по нодам считать только через `-o custom-columns='NODE:.spec.nodeName'`.
- `kubectl top nodes` → `error: Metrics API not available`: metrics-server установлен (F10, 2026-10-24) —
  это **регресс фазы**, а не норма; смотреть под `metrics-server` и APIService `v1beta1.metrics.k8s.io`.
- RSS/диск по `free -g`/`df -h /` округлены до гигабайт — не выдавать их за точные значения.
- Reboot-счётчики подов (`restarts` у longhorn-manager, kube-vip, cilium-operator) — следствие
  аварийного питания и переездов лидера, а не текущая деградация; смотреть на `AGE` последнего рестарта.
- Объект, поставленный `kubectl apply` в ns под Argo (`monitoring`, `infra`, `argocd`), исчезает за
  ~30 с без событий — это `prune+selfHeal`, а не поломка; валидировать во временном ns, ставить через git (§11a).
- Цифра в UI GPUStack — не метрика: истории нет, окна нет, выгрузить нечем. Вопрос «сколько VRAM/ватт было
  час назад» закрывает только `dcgm-exporter` + Prometheus, и окно у него — retention консоли 6h (§11).
