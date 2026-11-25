# TODO стенда

## Железо

- [ ] **k8s-04: замена NVMe Netac 1TB по гарантии.** 4 нечитаемых 4-КиБ блока за 5 дней на диске с
      0 % износа (462 ч, 18 unsafe shutdowns); 22–23.11 они попали в `/usr/sbin/lvm` (SIGBUS у
      `lvs`/`vgs`) и в бинарь `cilium-envoy` (CrashLoopBackOff). Симптомы сняты перезаписью файлов,
      дефект носителя остался. Разобраться: гарантийный срок и порядок обращения, серийник/модель —
      `architecture/hardware-inventory.md`; на этом же диске LV Longhorn 250G и `/data` 454G.
      Наблюдение — `scripts/k8s_health.py` (секция «Диски»), разбор — skill `demo-ai-lab-stand`,
      reference `disk-medium-error-forensics`.

## TLS и сертификаты

- [ ] **После показа: продление сертов без `letsencrypt-wildcard`.** Issuer и его секреты удалены
      2026-11-25, но на него всё ещё ссылаются 11 `Certificate`: wildcard `demo-wildcard` — до
      17.01.2027, сервисные — до 24.01–02.02.2027. Автопродление cert-manager запускается ~за 30 дней,
      то есть окно работы — конец декабря; сейчас продление упадёт (`IssuerNotFound`). План: публичные
      хосты (`owu`, `spk`, `doc`, `mcp`, `api`, `llm`, `auth`, `hm`, `dsh`, `mon`) перевести на
      `letsencrypt-http01`; для `argo`/`hgc`/`lng`/`mon` исключить `/.well-known/acme-challenge/` из
      LAN-allowlist (`gitops/infra-apps/infra/lan-only-ui.yaml`), иначе LE упрётся в `403`; wildcard —
      `acme-dns`/`regru` DNS-01 либо ручной выпуск. Проверка — `scripts/env_health.py` (TLS-цепочка).

