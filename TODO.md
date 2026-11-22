# TODO стенда

## Железо

- [ ] **k8s-04: замена NVMe Netac 1TB по гарантии.** 4 нечитаемых 4-КиБ блока за 5 дней на диске с
      0 % износа (462 ч, 18 unsafe shutdowns); 22–23.11 они попали в `/usr/sbin/lvm` (SIGBUS у
      `lvs`/`vgs`) и в бинарь `cilium-envoy` (CrashLoopBackOff). Симптомы сняты перезаписью файлов,
      дефект носителя остался. Разобраться: гарантийный срок и порядок обращения, серийник/модель —
      `architecture/hardware-inventory.md`; на этом же диске LV Longhorn 250G и `/data` 454G.
      Наблюдение — `scripts/k8s_health.py` (секция «Диски»), разбор — skill `demo-ai-lab-stand`,
      reference `disk-medium-error-forensics`.
