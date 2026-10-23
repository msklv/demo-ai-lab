# ADR-0001: Higress — единственный ingress-контроллер стенда

- Дата: 2026-10-12
- Статус: Accepted
- Ревизия: 2026-10-18 — привязка ingress решена: **пара k8s-02+k8s-03**, ingress-VIP `.230` (см. «Открытые вопросы» ниже; решение владельца). Контекст ниже — история на дату ADR, не меняется.
- Ревизия: 2026-10-18 (2) — уточнена атрибутировка требования по докам и чарту GPUStack 2.2.3: GPUStack **не** запрещает другие ingress-контроллеры в кластере; Higress обязателен только для собственных маршрутов GPUStack. «Единственный контроллер на весь стенд» — решение стенда (см. «Решение»).
- Ревизия: 2026-10-19 (3) — **способ установки решён: Higress standalone** (chart `higress.io/higress-core` **2.1.9** — тот же пин, что сабчарт GPUStack 2.2.3), установка в рамках `k8s-install-spec.md` **F7/F8** (VIP `.230` + gateway на паре 02/03). Формулировка «через GPUStack-chart» в «Решении» снята: GPUStack ставится позже с `higress-core.enabled=false` + `gateway.ingressClassname=higress` — это документированный путь доков GPUStack (Installation via Helm → Limitations: «если ingress-контроллер уже установлен, отключите bundled sub-chart и укажите существующий»), ингресс перестаёт зависеть от выхода GPUStack. Версия стендового Higress пинится вручную = версии сабчарта GPUStack; bump GPUStack ⇒ сверка пина Higress.

## Контекст

Демо делится на 3 части: (1) установка инфраструктуры «во главе с GPUStack»
(бекенды, рантаймы), (2) простые сервисы (Open WebUI, RAGFlow, Docling, Speakr),
(3) агентские сервисы. Кластер — kubeadm на k8s-02/03/04, NAT 80/443 на MikroTik
уже проброшен на k8s-02 (192.168.10.253) — узел, отведённый под ingress.

GPUStack ≥ 2.2 в k8s-режиме ставится официальным helm-чартом
(`oci://registry-1.docker.io/gpustack/gpustack-chart`) и включает собственный
in-cluster API-шлюз **Higress** (Envoy). Чарт позволяет отключить встроенный
Higress (`higress-core.enabled=false`), но тогда в кластере обязан быть **свой**
Higress — параметр `gateway.ingressClassname` принимает только Higress; Traefik/
NGINX в этой схеме не участвуют. Требования чарта: Kubernetes ≥ 1.30, default
StorageClass (Longhorn), Node Feature Discovery для GPU-нод.

## Решение

На стенде ставится **один** ingress-контроллер — **Higress**, **standalone** (ревизия 3):
чарт `higress.io/higress-core` **2.1.9** на паре k8s-02/03, вне установки GPUStack.
Версия зафиксирована: **GPUStack v2.2.3**, чарт
`oci://registry-1.docker.io/gpustack/gpustack-chart:2.2.3` (последний стабильный релиз
на 2026-10-18; 2.3.0 — только rc-пре-релизы). Версия higress-core пинится по версии
чарта GPUStack. Traefik/NGINX не
устанавливаются и не планируются. Это **решение стенда, а не ограничение
GPUStack**: соседство других ingress-контроллеров в кластере допустимо (чарт
прямо предусматривает `higress-core.enabled=false` при уже работающем контроллере),
но **свои маршруты** GPUStack обязан обслуживать Higress — сервер создаёт Ingress'ы
с аннотациями `higress.io/*` и CRD `networking.higress.io`/`extensions.higress.io`,
которые понимает только Higress. Один контроллер на весь стенд — наш выбор: один NAT
на :80/:443, единая точка роутинга и рубильник guard-маршрута. Все сервисы частей 2/3
публикуются роутами
Higress: `api.`, `openwebui.`, `ragflow.`, `docling.`, `speakr.`, `argo.`
на `*.demo-ai-lab.ru`. Higress слушает :80/:443 на ingress-VIP `192.168.10.230` (kube-vip LB-инстанс пары 02/03) —
один адрес и для LAN (split-DNS), и для внешнего пути (Cloudflare Tunnel).

## Последствия

Плюсы:
- Ингресс не зависит от GPUStack: поднимается вместе с кластером (F7/F8) и переживает
  переустановку/апгрейд GPUStack; один контроллер на весь стенд.
- Маршрутизация одна и та же из LAN и снаружи: split-DNS и Cloudflare Tunnel смотрят
  на ingress-VIP `.230`; проброс портов на узел не нужен.

Минусы и риски:
- helm-режим GPUStack и связка с Higress в официальной документации помечены
  **experimental** → обязательная сквозная репетиция установки до демо.
- Higress-конфиг (Ingress + Higress CRD) — новая для нас поверхность.

Открытые вопросы — закрыты ревизией 2026-10-19 (3):
- ~~режим слушания gateway на bare-metal без MetalLB~~ → `Service type=LoadBalancer` +
  kube-vip LB-инстанс (pool `.230`, статподы 02/03), `externalTrafficPolicy: Local` —
  `k8s-install-spec.md` F7/F8;
- ~~pin higress-core и порядок обновления~~ → **2.1.9** (= сабчарт GPUStack 2.2.3);
  bump GPUStack ⇒ сверка/подъём пина Higress одним чек-листом.

Референсы: [GPUStack Installation via Helm](https://docs.gpustack.ai/2.2/installation/helm/).

## Альтернативы

- **Traefik + GPUStack standalone (вне k8s)** — GPUStack ставится скриптом на
  k8s-04, наружу через Traefik-роут. Отклонено: ломает связный рассказ «вся
  инфраструктура в k8s», два способа установки GPUStack, лишняя точка отказа.
- **Traefik + GPUStack-helm + отдельный Higress** — два контроллера претендуют на
  :80/:443 одной ноды. Отклонено: конфликт и лишняя сложность без выигрыша.