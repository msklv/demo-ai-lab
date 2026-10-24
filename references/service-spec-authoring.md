# Спека нового сервиса для стенда: как писать и чем проверять

Для запроса «сделай спецификацию на установку X в существующий кластер» / «оформи план сервиса».
Результат — `architecture/<service>-spec.md` в корне репозитория плюс приватные файлы с кредами.
Стиль-образцы: `architecture/k8s-install-spec.md` (фазы F*), `architecture/external-access-spec.md` (E*).
Сервисные спеки нумеруются своей буквой (Keycloak — K1–K7), фазы F/E не пересматриваются.

## 1. Сначала живой замер, потом текст

Всё, что попадает в §«Предпосылки», снимается командами и переносится с датой замера; из старых доков
цитаты не годятся (доки отстают от факта).

```bash
export KUBECONFIG=~/.kube/demo-ai-lab.conf
kubectl get sc; kubectl get ingressclass
kubectl get nodes -o custom-columns='NODE:.metadata.name,RAM:.status.allocatable.memory,CPU:.status.allocatable.cpu,TAINTS:.spec.taints[*].key'
kubectl get pods -A -o wide | head            # живые pod-IP: реальный pod-CIDR, а не .spec.podCIDR ноды
kubectl get cm -n kube-system cilium-config -o jsonpath='{.data.cluster-pool-ipv4-cidr} {.data.cluster-pool-ipv4-mask-size}'
kubectl get ingress,certificate -A -o wide    # какие TLS-секреты и где лежат
kubectl get apps -n argocd                    # Synced/Healthy у infra/root-app = Argo реально работает
dig +short {svc}.demo-ai-lab.ru @1.1.1.1      # снаружи → anycast Cloudflare
dig +short @192.168.10.1 {svc}.demo-ai-lab.ru # из LAN → 192.168.10.230
```

Стендовые факты, которые уже проверены и переоткрывать не нужно:
- DNS-wildcard `*.demo-ai-lab.ru` есть и снаружи (proxied), и в split-DNS MikroTik (regexp → `.230`):
  **новое имя не заводится**, но и **любой заведённый Ingress сразу публикуется наружу** (туннель роутит
  валидные Ingress'ы диапазона). Отсюда правило E6: служебные пути/админки гейтятся в тот же день.
- SC `longhorn` default (replica=2), ingressclass `higress`, ingress-VIP `.230` на k8s-02/03,
  `externalTrafficPolicy: Local`.
- **TLS-секрет читается только в namespace Ingress'а.** Wildcard-серт `demo-wildcard-tls` из `demo-test`
  переиспользовать нельзя: свой `Certificate` в своём ns с кластерным `ClusterIssuer letsencrypt-wildcard`
  (DNS-01 через Cloudflare-токен). Помнить про лимит LE 50 сертов/нед — не гонять перевыпуск в цикле.
- Pod-сеть — Cilium cluster-pool `10.0.0.0/8` маской 24; `kubectl get nodes .spec.podCIDR` показывает
  kubeadm-шные `10.42.x`, которые Cilium НЕ использует. Для trusted-addresses/allowlist брать `10.0.0.0/8`.
- **Размещение выбирается по сбоям, а не по свободной RAM.** `kubectl top nodes` + `describe` дают
  steady-state; в спеку идёт ещё и матрица отказов. Правила, проверенные на SSO:
  hard `nodeSelector` на один узел = при его потере под висит `Pending` до возврата железа (не «переедет
  за минуту»); ставить `preferred` `nodeAffinity` + `preferred` `podAntiAffinity`, а `required` — только
  если простой допустим. Узел, который на демо занят своим делом (k8s-04 = GPUStack/инференс), — плохой
  дом для сервиса, который должен отвечать во время показа: он и конкурент за RAM, и падает вместе с ним.
  Пара k8s-02/03 (~11 Gi свободно на каждой) — штатное место лёгких сервисов (ADR-0003), k8s-01 — резерв
  (там спайки RAGFlow/Docling).
- Если сервис без состояния, но с сессиями — реплики ×2 + общий кэш через БД (для Keycloak
  `--cache-stack=jdbc-ping`) вместо одной реплики «на всякий случай»; RTO и остаточный SPOF (обычно БД —
  1–3 мин на переаттач тома Longhorn) пишутся в §4/§8 спеки явно, вместе с drill-приёмкой.

## 2. Пины и доступность образов — доказать, а не предположить

1. digest из реестра: `quay.io/api/v1/repository/<org>/<repo>/tag/?specificTag=<tag>&onlyActiveTags=true`,
   Docker Hub — `hub.docker.com/v2/repositories/library/<repo>/tags?page_size=15&name=<tag>`.
2. доступность с площадки — короткоживущий пробный под (он же предтяжка на нужную ноду):
   ```bash
   kubectl -n default run <probe> --image=<img>@sha256:<digest> --restart=Never \
     --image-pull-policy=IfNotPresent --command -- <команда версии> \
     --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"k8s-04"}}}'
   kubectl -n default get pod <probe> -o jsonpath='{.spec.nodeName}{" "}{.status.containerStatuses[0].imageID}{"\n"}'
   kubectl -n default delete pod <probe>
   ```
   **Грабля:** `--overrides` с `nodeSelector` под может проигнорировать (под уехал на другой узел).
   Всегда читать `.spec.nodeName` в ответе; если размещение принципиально — подавать манифест/`nodeName`.
   Пины, проверенные таким пробой, идут в §1 спеки с digest и версией из фактического вывода.
3. Образы килобайтных размеров на канале 4–6 МБ/с: предтяжка в K1 (критерий — нужный digest в `imageID`).

## 3. Скелет спеки (не отклоняться)

1. Шапка-цитата: версия, статус («спека, не установлено» / «K1–K7 выполнены»), цель, внешнее имя,
   **механизм развёртывания одной строкой** (Argo CD, secrets вне git).
2. §1 «Что ставим и где» — таблица решений: параметр → решение → обоснование (пины, ns, узел, реплики,
   данные/PVC, TLS, ingress, публичность, способ деплоя, секреты, PriorityClass).
3. §2 «Предпосылки — проверено <дата>» — команды + фактический вывод; DNS/DNS-записи, NTP, образы.
4. §3 Секреты: таблица приватных файлов (что внутри / кто читает), правило `.gitignore`, приёмка гигиены,
   Secret'ы в кластере (что создаёт скрипт, когда), жизненный цикл bootstrap-учётки.
5. §4 Развёртывание: состав каталога в gitops, sync-waves, ключевые YAML-фрагменты (env/args, probes,
   resources, nodeSelector, PVC) + почему именно так (сноски на доки продукта).
6. §5 Конфигурация домена сервиса (для Keycloak — realm/роли/пользователи/клиенты) и идемпотентный
   seed-скрипт как единственный источник правды (ручные правки в UI не считаются).
7. §6 Фазы K1..Kn с приёмкой: каждая фаза — блок команд с ожидаемым результатом.
8. §7 Операции: health-smoke, бэкап/восстановление, ротация паролей, апгрейд.
9. §8 Риски-таблица (R-K1…) с «что делаем», §9 «что забывают в таких спеках» + открытые вопросы.
10. §10 Связанные документы + история версий (v1.0 — что проверено живьём).

Язык — русский, плотные таблицы, вместо абзацев — команды. Оценок времени в спеке не даём.

## 4. Приватные файлы с кредами

- Отдельные файлы на «роль» кредов: админ сервиса / пользователи / клиенты-секреты (напр.
  `keycloak-admin.local.md`, `keycloak-users.local.md`, `keycloak-clients.local.md`) в корне репо.
- `.gitignore`: одно широкое правило `*.local.md` (покрывает и будущие), explicit-строка для
  `inventory.local.md` остаётся. Проверка: `git check-ignore -v <файлы>` → каждый матчится.
- Формат: `ключ: значение` по строке — скрипты читают `awk -F': ' '/^ключ: /{print $2}'`, значения
  не печатают (в терминал, в чат, в доки). Генерация — `execute_code`/python `secrets`, `chmod 600`.
- Приёмка утечки: программно собрать секретные значения из файлов и прогнать по всем `git ls-files`;
  отдельно — пре-коммит grep-фильтр из `AGENTS.md`. Файлы-дампы/бэкапы с хэшами паролей — ВНЕ репо.

## 5. Регистрация в репо — одним заходом (и без коммита)

`README.md` (строка в таблицу документации + оговорка «на стенде не установлено»),
`architecture/ARCHITECTURE.md` §7 (новый номер строки борда) и §8 (перечень файлов),
`gitops/README.md` (состав `infra-apps/<ns>/`), `AGENTS.md` (приватные файлы + check-ignore).
Коммит/пуш — только по явной команде владельца.

## 6. Чек-лист «что обычно забывают» (применять к любому сервису)

| Пункт | Как закрыть |
|---|---|
| БД/хранилище состояния | свой PostgreSQL/PVC в том же ns + путь миграции на общий data-tier, когда он появится |
| TLS в namespace Ingress'а | свой `Certificate`, не wildcard-секрет из `demo-test` |
| Публичность и админ-консоль на одном хосте | гейт админских путей (Cloudflare Access path-app) + проверка в ОБЕ стороны: снаружи 403, из LAN 200 |
| Backchannel для клиентов внутри кластера | внутренний адрес сервиса в метаданных (для Keycloak `--hostname-backchannel-dynamic`), чтобы не зависеть от Cloudflare/R1 |
| SMTP отсутствует | регистрация/сброс пароля/verify email выключены, пароли не временные |
| Bootstrap-учётка | действует только на первом старте: сменить пароль → снять env правкой в git |
| Приоритет на узле с GPUStack | `PriorityClass` выше 0 + requests/limits |
| Бэкап | `pg_dump`/снапшот ДО апгрейда, дампы вне репо, восстановление описано |
| Лимиты CA | LE 50/нед: не перевыпускать в цикле |
| Redirect/logout URI приложений | не угадывать — брать из доки/лога при первом деплое сервиса |
| NTP | расхождение часов ломает JWT |
| Одна реплика / жёсткий пин на узел | либо ×2 реплики + общий кэш и `preferred`-affinity, либо явный RTO; hard `nodeSelector` = `Pending` при потере узла |
