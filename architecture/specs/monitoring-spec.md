# Спецификация наблюдаемости стенда: метрики Prometheus и GPU-телеметрия (DCGM)

> **Версия:** v1.0 (2026-11-10) · **Статус:** действует (развёрнуто на стенде)
> **Роль:** что мы измеряем метриками (в отличие от black-box аптайма и on-demand проверки здоровья),
> откуда берутся GPU-метрики, как устроены скрейп и дашборд, что чинить после обновления консоли Higress.
> **Не входит:** аптайм/SSL хостов — ADR-0009 и `monitoring` (Kuvasz); проверка готовности «здоров ли стенд
> и готов ли к показу» — `architecture/specs/health-check-spec.md`; инвентаризация источников метрик
> «что уже есть» — `references/health-runbook.md`.
> **Связанные:** ADR-0001 (Higress как единственный ingress), ADR-0009 (Kuvasz), ADR-0007 (бюджет GPU).

## 1. Разделение инструментов: три разных вопроса

| Вопрос | Инструмент | Окно | Где смотреть |
|---|---|---|---|
| «Стенд здоров и готов к показу?» | `scripts/k8s_health.py`, `scripts/env_health.py` + `health-check-spec` | на момент запуска | консоль агента |
| «Хосты живы, сертификаты не протухли?» | Kuvasz (`mon.demo-ai-lab.ru`, ADR-0009) | постоянно, чёрный ящик | UI `mon.` (только LAN) |
| «Что с ресурсами и с GPU во времени?» | Prometheus консоли Higress + Grafana + **dcgm-exporter** (эта спека) | **6 часов** (retention консольного бандла) | Grafana, дашборд `demoai-gpu` |

Правило: метрикой не называется то, чего нельзя показать на графике. «GPUStack показывает VRAM в UI» —
не метрика: истории нет, выгрузить нечем, окно неизвестно.

## 2. Что есть в кластере (факт, проверено 2026-11-10)

| Источник | Состав | Ограничение |
|---|---|---|
| `higress-system` | `higress-console-prometheus` v2.40.7 (PVC 10Gi Longhorn, `--web.external-url=/prometheus`, `--storage.tsdb.retention=6h`), `higress-console-grafana` 9.3.6, `higress-console-loki` | бандл консоли, рендерится Helm-чартом; Alertmanager нет; jobs `prometheus`, `k8s_nodes`, `k8s_pods`, **`dcgm_gpu`** |
| `monitoring` | Kuvasz 4.6.0 + PostgreSQL, **`dcgm-exporter` (DaemonSet, GPU-нода)** | ns под Argo CD (Application `monitoring`, `prune` + `selfHeal`) |
| `kube-system` | `metrics-server` | только `kubectl top`, истории нет |
| GPUStack | `/metrics` → **404** | метрик по Prometheus нет; GPU-цифры — только UI |
| Longhorn `:9500`, kueue `:8443`, шлюз `:15020/stats/prometheus` | свои `/metrics` есть | к сбору не подключены |

Платформенного Prometheus/Alertmanager/node-exporter/kube-state-metrics в кластере нет. Следствие:
**алертов по метрикам нет ни одного** — эта спека их не добавляет (см. §7).

## 3. GPU-телеметрия: dcgm-exporter

**Зачем.** До 2026-11-10 GPU наблюдалась только руками (`nvidia-smi` по SSH) и в UI GPUStack. Вопросы
«сколько VRAM занимает модель», «сколько ватт уходит в простое», «грелась ли карта ночью» не имели
ответа после факта.

**Манифест:** `gitops/infra-apps/monitoring/40-dcgm-exporter.yaml` — ConfigMap (конфиг экспортёра +
список счётчиков), Service `dcgm-exporter:9400`, DaemonSet `dcgm-exporter`.

| Решение | Значение | Почему так |
|---|---|---|
| Образ | `nvidia/dcgm-exporter:4.7.0-4.9.0-distroless@sha256:2490e1df…eea9` | официальный NVIDIA, пин по **digest** (тег mutable); distroless — нет shell, атакуемая поверхность минимальна |
| Размещение | `nodeSelector: feature.node.kubernetes.io/pci-10de.present=true` | NFD-метка присутствия NVIDIA-PCI: сейчас одна нода (k8s-04, RTX 5070 Ti), при появлении второй GPU-ноды DaemonSet поднимется сам — манифест править не нужно |
| `runtimeClassName: nvidia` | обязательно | узлы подключают `/dev/nvidia*` через CDI (тот же путь, что у `gpustack-worker-nvidia`); hostPath `/dev` не нужен |
| `privileged: true` | обязательно | с CDI containerd подставляет `NVIDIA_MIG_CONFIG_DEVICES`/`MONITOR_DEVICES` и **отказывается** создавать непривилегированный контейнер: `invalid MIG capability request: cannot set NVIDIA_MIG_*_DEVICES in a non-privileged container`. Грабля стоила двух итераций: без privileged под падает на OCI spec, а не в приложении |
| `allowPrivilegeEscalation` | не задан | API **не принимает** `false` вместе с `privileged: true` (`cannot set allowPrivilegeEscalation to false and privileged to true`) |
| Профилировщик | не включён | `DCGM_FI_PROF_*` требует `SYS_ADMIN` и мешает другим пользователям GPU (занимает счётчики); нам нужны счётчики состояния — они доступны без него |
| Конфиг экспортёра | `config.yaml` (version 2) в ConfigMap | 4.9 читает `DCGM_EXPORTER_CONFIG_FILE=/etc/dcgm-exporter/config.yaml` — **без файла под падает на старте**; `enrichment` вложен в `metrics[0]`, на верхнем уровне — `unknown key` |
| Набор счётчиков | `counters.csv`, 13 полей | дефолтный набор 4.x — ~60 серий на карту, для борда лишнее; имена полей должны существовать в DCGM (см. §3.2) |
| Ресурсы | requests 100m/128Mi, limits 300m/512Mi | замер: 8–20 MiB RSS в простое |

### 3.1. Метрики (замер 2026-11-10, RTX 5070 Ti, простой)

| Метрика | Что | Значение в замере |
|---|---|---|
| `DCGM_FI_DEV_GPU_TEMP` | температура GPU, °C | 47 |
| `DCGM_FI_DEV_POWER_USAGE` | мгновенное потребление, Вт | 20.5 |
| `DCGM_FI_DEV_POWER_MGMT_LIMIT` | лимит мощности, Вт | 300 |
| `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` | суммарная энергия, мДж | 1.865e9 |
| `DCGM_FI_DEV_GPU_UTIL` | загрузка SM, % | 0 |
| `DCGM_FI_DEV_MEM_COPY_UTIL` | загрузка контроллера памяти, % | 0 |
| `DCGM_FI_DEV_FB_USED` / `FB_FREE` | VRAM занято/свободно, МиБ | 15 639 / 202 |
| `DCGM_FI_DEV_SM_CLOCK` / `MEM_CLOCK` | частоты, МГц | 210 / 405 (P8) |
| `DCGM_FI_DEV_FAN_SPEED` | вентиляторы, % | 0 (Idle Fan Stop) |
| `DCGM_FI_DEV_MEMORY_TEMP`, `DCGM_FI_DEV_XID_ERRORS` | в списке есть, карта не отдаёт | серий нет — панель остаётся пустой, это норма для GeForce |

Метки: `gpu`, `UUID`, `pci_bus_id`, `device`, `modelName`, `hostname` — по `hostname`/`modelName` дашборд
фильтруется переменными, по `UUID` можно разделять карты на одной ноде.

**Грабля на будущее (энергия):** `DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION` отдаётся в **мДж** и растёт
монотонно; в ватты переводится производной (`deriv(...[5m])/1000`) — так на дашборде есть «средняя
мощность за 5 минут», независимая от мгновенных скачков `power.draw`.

### 3.2. Почему в CSV нельзя писать любые имена

Экспортёр падает на старте, если поля нет в DCGM: `could not find DCGM field; unknown ExporterCounter
field 'DCGM_FI_DEV_MEM_TEMP'`. Правильное имя — `DCGM_FI_DEV_MEMORY_TEMP`; `DCGM_FI_DEV_MEM_TEMP`
не существует. Проверка нового поля — по логу пода и по `/metrics`, а не по названию в чужом дашборде.

## 4. Скрейп: job `dcgm_gpu` в Prometheus консоли

**Почему job не в git.** `higress-console-prometheus` — ConfigMap, **целиком отрендеренный Helm-чартом
higress-console** (шаблон, без values-хука; в values можно менять только ресурсы и размер тома).
Скрейп-конфиг не имеет точки расширения: любой `kubectl patch` живёт до `helm upgrade higress-console`,
после которого GPU-серии молча исчезнут. Поэтому:

- истина о job — скрипт `scripts/prometheus_dcgm_job.py` (идемпотентный);
- после **каждого** обновления консоли (`ansible/values-higress-console.yaml`, `higress_console_upgrade.sh`)
  прогонять `python3 scripts/prometheus_dcgm_job.py --check` и, при `DRIFT`, — без `--check`.

```bash
python3 scripts/prometheus_dcgm_job.py --check    # DRIFT/OK, ничего не меняет
python3 scripts/prometheus_dcgm_job.py            # добавить/обновить job + rollout restart, проверить targets
```

Что делает скрипт: читает CM `higress-console-prometheus`, ставит job `dcgm_gpu` на
`dcgm-exporter.monitoring.svc.cluster.local:9400` (интервал 15s, таймаут 10s), применяет CM,
перезапускает Deployment (конфиг читается только на старте) и **проверяет по факту** через
`/prometheus/api/v1/targets`, что цель `health=up`. Код выхода: 0 — up, 1 — нет.

Промежуточный путь на будущее: когда появится платформенный Prometheus (ServiceMonitor/VM), job уходит
туда, а с консольного бандла его снимают — иначе два источника с разными окнами ретенции (правило уже
зафиксировано в `references/health-runbook.md`).

## 5. Дашборд Grafana

| Параметр | Значение |
|---|---|
| UID / адрес | `demoai-gpu`, `/grafana/d/demoai-gpu/demo-ai-lab-gpu-dcgm` |
| Файл в репо | `gitops/infra-apps/monitoring/dashboards/gpu-dcgm.json` (каталог вне манифестов: у Application `monitoring` нет `directory.recurse`, JSON в подкаталоге Argo не парсит) |
| Datasource | `Prometheus` (uid `aHslnMqvz`) — тот же, что у консоли |
| Окно / автообновление | `now-6h` / 30s — ровно retention консольного Prometheus |
| Переменные | `instance` (нода), `gpu` (модель карты), multi + All |
| Панели | 6 stat (темп, ватты, VRAM %, загрузка, SM-частота, вентилятор) + 5 графиков (температура, питание+лимит, загрузка SM/памяти, VRAM, частоты) + график «средняя мощность за 5 мин» из энергии |

**Импорт.** Grafana консоли живёт с `disable_login_form=true` и **анонимным viewer** (`org_role: Viewer`),
провижининга дашбордов нет (каталоги `/etc/grafana/provisioning/*` пустые, dashboards засеяны в
`/var/lib/grafana`). Поэтому дашборд ставится админским API:

```bash
python3 scripts/grafana_import_dashboard.py           # импорт всех JSON из gitops/infra-apps/monitoring/dashboards/
python3 scripts/grafana_import_dashboard.py --check   # только состояние (есть/нет, version)
```

Скрипт берёт креды администратора из окружения пода консоли (`HIGRESS_CONSOLE_DASHBOARD_USERNAME` /
`HIGRESS_CONSOLE_DASHBOARD_PASSWORD` — их же использует витрина `hgc.`), поднимает `port-forward` и делает
`POST /grafana/api/dashboards/db` с `overwrite=true`. В репозиторий креды не попадают. Дашборд хранится
в PVC Grafana: рестарт пода и `helm upgrade` его не сносят; **переустановка Grafana с нуля — сносит**,
тогда скрипт запускается снова.

Правки в UI Grafana разрешены (`viewers_can_edit=true`), но источник истины — JSON в репо: правку,
сделанную руками, нужно перенести в файл, иначе следующий импорт её перезапишет.

## 6. Приёмка (что считается доказательством)

```bash
# 1. под экспортёра на GPU-ноде
kubectl --context demo-ai-lab -n monitoring get ds,pods -l app=dcgm-exporter -o wide
kubectl --context demo-ai-lab -n monitoring logs -l app=dcgm-exporter --tail=5   # "HTTP server started"

# 2. метрики отдаются
kubectl --context demo-ai-lab run curl-probe --rm -i --restart=Never --image=curlimages/curl:8.10.1 \
  --command -- curl -s http://dcgm-exporter.monitoring.svc:9400/metrics | grep DCGM_FI_DEV_GPU_TEMP

# 3. скрейп живой
python3 scripts/prometheus_dcgm_job.py --check     # ожидается OK: job ... настроен

# 4. данные дошли до Grafana (запрос через datasource)
python3 scripts/grafana_import_dashboard.py --check   # demoai-gpu: есть (version≥1, panels=12)
```

Признак «панель пустая, а под зелёный»: цель `dcgm_gpu` в Prometheus в состоянии `down` (обычно после
`helm upgrade` консоли) либо истекло окно 6h — проверять в этом порядке, а не дашборд.

## 7. Ограничения и что дальше

- **Ретенция 6 часов.** Истории «неделя/месяц» нет; вопрос «сколько карта грелась за сутки» этой
  инсталляцией не отвечается. Нужен платформенный Prometheus (или VictoriaMetrics) с 30-дневным окном —
  отдельное решение, сюда не входит.
- **Алертов нет.** Нет Alertmanager и нет правил: температура 90 °C или `FB_USED` 100 % ничего не
  сообщат. Kuvasz (ADR-0009) следит за HTTP/TCP/SSL, но не за GPU.
- **Панель на карте (LCD) не оживает этим.** Экранчик на карте управляется вендорской утилитой под
  Windows; к хосту карта не подключена ни по USB, ни отдельной PCI-функцией (проверено 2026-11-10:
  `lsusb`, `lspci`, `hidraw` — чисто). Метрики идут в Grafana, а не на 20-мм дисплей.
- **GPUStack не отдаёт `/metrics`** (404 на 30080). Метрики очередей/моделей GPUStack придётся брать
  из его БД или ждать версии с `/metrics` — отдельная задача.
- **Longhorn/kueue/шлюз** свои `/metrics` отдают, но к сбору не подключены: добавлять по тому же
  принципу (job в статическом конфиге) или вместе с платформенным Prometheus.
