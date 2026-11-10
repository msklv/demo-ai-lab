#!/usr/bin/env python3
"""Добавить/обновить job `dcgm_gpu` в Prometheus консоли Higress и перезапустить его.

Зачем скрипт, а не манифест: конфиг `higress-console-prometheus` целиком рендерится
Helm-чартом higress-console (шаблон, без values-хука), поэтому scrape-job нельзя
держать в gitops/ — его пришлось бы патчить поверх Helm. Скрипт идемпотентен и
возвращает конфиг в нужное состояние после любого `helm upgrade higress-console`
(подробности: architecture/specs/monitoring-spec.md).

Использование:
    python3 scripts/prometheus_dcgm_job.py                      # боевой таргет (ns monitoring)
    python3 scripts/prometheus_dcgm_job.py --target 192.168.10.252:9400
    python3 scripts/prometheus_dcgm_job.py --check              # только показать состояние
    python3 scripts/prometheus_dcgm_job.py --context demo-ai-lab

Код выхода: 0 — job на месте (или добавлен), 1 — не удалось.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

NS = "higress-system"
CM = "higress-console-prometheus"
DEPLOY = "higress-console-prometheus"
JOB = "dcgm_gpu"
DEFAULT_TARGET = "dcgm-exporter.monitoring.svc.cluster.local:9400"


def kubectl(ctx: str, *args: str, stdin: str | None = None) -> str:
    cmd = ["kubectl", f"--context={ctx}", *args]
    res = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {res.stderr.strip()}")
    return res.stdout


def job_block(idx: int, target: str) -> dict:
    return {
        "job_name": JOB,
        "static_configs": [{"targets": [target]}],
        "scrape_interval": "15s",
        "scrape_timeout": "10s",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", default="demo-ai-lab")
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--check", action="store_true", help="только отчёт, без изменений")
    args = ap.parse_args()

    import yaml  # PyYAML: на консоли агента есть; при отсутствии — pip install pyyaml

    cm = json.loads(kubectl(args.context, "-n", NS, "get", "cm", CM, "-o", "json"))
    cfg = yaml.safe_load(cm["data"]["prometheus.yml"])
    jobs = cfg.setdefault("scrape_configs", [])
    before = [j for j in jobs if j.get("job_name") == JOB]
    new = job_block(len(jobs), args.target)

    if before == [new]:
        print(f"OK: job {JOB} уже настроен на {args.target}")
    elif args.check:
        print(f"DRIFT: job {JOB} сейчас {before or 'отсутствует'}, ожидается {new}")
    else:
        cfg["scrape_configs"] = [j for j in jobs if j.get("job_name") != JOB] + [new]
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": CM,
                "namespace": NS,
                "labels": cm["metadata"].get("labels", {}),
                "annotations": cm["metadata"].get("annotations", {}),
            },
            "data": {"prometheus.yml": yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)},
        }
        kubectl(args.context, "apply", "-f", "-", stdin=json.dumps(manifest))
        # --config.file читается только на старте процесса
        kubectl(args.context, "-n", NS, "rollout", "restart", f"deploy/{DEPLOY}")
        kubectl(args.context, "-n", NS, "rollout", "status", f"deploy/{DEPLOY}", "--timeout=180s")
        print(f"OK: job {JOB} -> {args.target}, Prometheus перезапущен")

    # Проверка по факту: цель должна быть в /api/v1/targets (external-url /prometheus).
    # После rollout restart Prometheus отдаёт 503, пока проигрывает WAL, — ждём с запасом.
    active, last_err = [], ""
    for _ in range(24):
        pod = kubectl(args.context, "-n", NS, "get", "pod", "-l", f"app={DEPLOY}",
                      "--field-selector=status.phase=Running",
                      "-o", "jsonpath={.items[0].metadata.name}").strip()
        if not pod:
            pod = kubectl(args.context, "-n", NS, "get", "pod", "-l", "app.kubernetes.io/name=prometheus",
                          "--field-selector=status.phase=Running",
                          "-o", "jsonpath={.items[0].metadata.name}").strip()
        try:
            raw = kubectl(args.context, "-n", NS, "exec", pod, "--",
                          "wget", "-qO-", "http://localhost:9090/prometheus/api/v1/targets?state=active")
            # сразу после старта Prometheus отдаёт 200 с пустым набором — ждём появления цели
            active = [t for t in json.loads(raw)["data"]["activeTargets"]
                      if t["labels"].get("job") == JOB]
            if active:
                break
        except RuntimeError as exc:
            last_err = str(exc)
        time.sleep(5)
    if not active:
        print(f"FAIL: цель {JOB} не активна в Prometheus", file=sys.stderr)
        return 1
    for t in active:
        print(f"target={t['scrapeUrl']} health={t['health']} "
              f"lastError={t.get('lastError') or '-'}")
    return 0 if all(t["health"] == "up" for t in active) else 1


if __name__ == "__main__":
    sys.exit(main())
