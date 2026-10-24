# Проход «какой сейчас статус нод» (health sweep стенда)

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

## Скрипт вместо ручного прохода (запрос «проверять состояние кластера скриптом»)

**Язык — Python 3 (только stdlib), не bash и не PowerShell 7.** Аргумент фактический, не вкусовой:
`python3` + `PyYAML` есть на всех нодах, а **`jq` нет ни на одной** — bash-вариант
`kubectl -o json | jq` тянет новую зависимость на каждый хост, а без jq остаётся разбор текстового
вывода (`get`/`describe` без `-o json`), т.е. ровно «сбор информации по крупицам». PowerShell 7 стоит
на всех нодах (snap 7.6.6), но консоль Mac — 7.5.4: нужен `#Requires -Version 7.2` и политика
синхронного патча; берём только если в контуре появится Windows-сегмент.

**Правило класса: один верхнеуровневый идемпотентный запрос на домен, ноль обходов объектов.**
Замена `kubectl describe` и grep'а логов:

- API-сервер: `kubectl get --raw='/readyz?verbose'` — все проверки одним ответом.
- Ноды: `kubectl get nodes -o json` → `status.conditions[type=Ready|…Pressure]`.
- Нагрузки: ОДИН bulk `kubectl get pods,deploy,sts,ds,svc,ingress -A -o json` → сверка с декларативным
  списком `(kind, ns, name, minReady)` по `readyReplicas`/`updatedReplicas`/`observedGeneration`;
  события и `describe` не читать.
- Argo CD: `kubectl get applications.argoproj.io -A -o json` → `status.health.status` +
  `status.sync.status` — собственный агрегат здоровья не писать, он уже посчитан.
- Ожидание/раскатка: `kubectl wait --for=condition=Ready … --timeout=…`, `kubectl rollout status`.
- Внешние точки: по одному HTTP-запросу, параллельно (`concurrent.futures`), общий бюджет таймаута на
  прогон; печатать код+латентность, тело ошибки — только при не-200.
- Runtime-условия (Certificate Ready, Longhorn node Ready, тоннель) — из `conditions` CR, а не из логов.

**Контракт скрипта (такой у `scripts/k8s_health.py` — следовать ему, а не изобретать второй):**
флаги `--brief` / `--json` / `--timeout`, коды выхода `0` = всё зелёное, `2` = есть WARN, `1` = есть FAIL
(машиночитаемый режим возвращает `{worst, counts, checks[]}` с `status` по каждому чеку), проверка =
чистая функция «снапшот → вердикт» (повторный запуск ничего не меняет).
Поток вывода: шаг объявляется в stderr (`… <шаг>`), вердикт шага печатается сразу по готовности с его
временем — длинные шаги (внешний путь, VIP по SSH) не должны выглядеть зависанием; `--json` прогресс
выключает, цвет — только оформление (TTY / `--no-color` / `NO_COLOR` / `FORCE_COLOR`).
Гонять с консоли (`KUBECONFIG=~/.kube/demo-ai-lab.conf`), не на нодах — там user-kubeconfig нет.

**Грабли написания самих чеков:**
- **Образ etcd — distroless: shell нет.** `kubectl exec <etcd-pod> -- sh -c 'etcdctl …'` падает;
  `etcdctl` вызывать напрямую аргументами: `kubectl exec -n kube-system etcd-k8s-01 -- etcdctl
  --endpoints=https://127.0.0.1:2379 --cacert=… --cert=… --key=… member list`.
- Вывод `member list` разделён запятыми С ПРОБЕЛОМ (`id, started, k8s-03, …`): поля стрипить перед
  сравнением, иначе `f[1] == "started"` не совпадёт и чек соврёт «кворума нет» при живом etcd.
- `kubectl logs` у CrashLoop-пода отдаёт последнюю попытку и может выглядеть «старьём»: для вердикта
  брать статусы/`conditions`/счётчики рестартов, логи — только как контекст к причине.
- `kubectl exec` без stdin у static-подов висит дольше обычного — оборачивать в таймаут (10–30 с).
- Если SSH-цели берутся разбором `inventory.local.md` по шаблону `user@ip`, в список попадает и роутер
  (`admin@192.168.10.1`): фильтровать цели по фактическому набору InternalIP из `get nodes`, иначе
  счётчик нод и опрос уезжают на лишний хост.
- `account_id` для Cloudflare API брать из объекта зоны (`zones[0].account.id`): у токена с DNS:Edit
  список `/accounts` может быть пуст, и `accounts[0]` даёт ложное «CNAME на туннель не найден».

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
`192.168.10.240:6443: no route to host`, все четыре ноды пингуются, `ss -ltn` на 01 даёт только
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

Проверка после: `.240` и `.230` на разных узлах, `kubectl get nodes` = 4×Ready, health-gate пусто,
Longhorn `Ready=true` на 4 нодах (у k8s-01 `SCHED=false` by design), Argo Synced/Healthy.
`sudo` на нодах — пароль из локального приватного хранилища; `sudo -S` читает пароль со stdin, поэтому
на несколько команд в одном ssh-вызове пароль подавать **в каждый** вызов или объединять их в один
`sudo bash -c "..."` (иначе второй получает «no password was provided»).

## Грабли (проверено живым прогоном)

- `kubectl get pods -A -o wide --no-headers | awk '{print $8}'` даёт **AGE, а не NODE** (при `-A`
  колонок больше). Поды по нодам считать только через `-o custom-columns='NODE:.spec.nodeName'`.
- `kubectl top nodes` → `error: Metrics API not available`: metrics-server установлен (F10, 2026-10-24) —
  это **регресс фазы**, а не норма; смотреть под `metrics-server` и APIService `v1beta1.metrics.k8s.io`.
- RSS/диск по `free -g`/`df -h /` округлены до гигабайт — не выдавать их за точные значения.
- Reboot-счётчики подов (`restarts` у longhorn-manager, kube-vip, cilium-operator) — следствие
  аварийного питания и переездов лидера, а не текущая деградация; смотреть на `AGE` последнего рестарта.
