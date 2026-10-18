# ADR-0001: Higress — единственный ingress-контроллер стенда

- Дата: 2026-10-12
- Статус: Accepted
- Ревизия: 2026-10-18 — привязка ingress решена: **пара k8s-02+k8s-03**, ingress-VIP `.230` (см. «Открытые вопросы» ниже; решение владельца). Контекст ниже — история на дату ADR, не меняется.

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

На стенде ставится **один** ingress-контроллер — **Higress** (через GPUStack-chart).
Версия зафиксирована: **GPUStack v2.2.3**, чарт
`oci://registry-1.docker.io/gpustack/gpustack-chart:2.2.3` (последний стабильный релиз
на 2026-10-18; 2.3.0 — только rc-пре-релизы). Версия higress-core пинится по версии
чарта GPUStack. Traefik/NGINX не
устанавливаются и не планируются. Все сервисы частей 2/3 публикуются роутами
Higress: `api.`, `openwebui.`, `ragflow.`, `docling.`, `speakr.`, `argo.`
на `*.demo-ai-lab.ru`. Higress слушает :80/:443 на k8s-02 (NAT уже смотрит туда).

## Последствия

Плюсы:
- «Инфраструктура во главе с GPUStack» буквально: одна установка поднимает
  GPUStack + gateway; один контроллер на весь стенд.
- NAT/сеть не меняются (проброс уже на .253).

Минусы и риски:
- helm-режим GPUStack и связка с Higress в официальной документации помечены
  **experimental** → обязательная сквозная репетиция установки до демо.
- Higress-конфиг (Ingress + Higress CRD) — новая для нас поверхность.

Открытые вопросы (проверить на репетиции, до записи в доки):
- режим слушания gateway Higress на bare-metal kubeadm без MetalLB
  (hostNetwork vs hostPort vs NodePort) — привязка решена 2026-10-18: пара k8s-02/03, ingress-VIP `.230` (LB-kube-vip, `externalTrafficPolicy: Local`);
- pin версии higress-core (по чарту GPUStack) и порядок обновления.

Референсы: [GPUStack Installation via Helm](https://docs.gpustack.ai/2.2/installation/helm/).

## Альтернативы

- **Traefik + GPUStack standalone (вне k8s)** — GPUStack ставится скриптом на
  k8s-04, наружу через Traefik-роут. Отклонено: ломает связный рассказ «вся
  инфраструктура в k8s», два способа установки GPUStack, лишняя точка отказа.
- **Traefik + GPUStack-helm + отдельный Higress** — два контроллера претендуют на
  :80/:443 одной ноды. Отклонено: конфликт и лишняя сложность без выигрыша.