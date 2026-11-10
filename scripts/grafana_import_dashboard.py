#!/usr/bin/env python3
"""Импорт дашборда в Grafana консоли Higress (ns higress-system) через API.

Зачем скрипт: Grafana консоли не имеет provisioning-каталога (dashboards засеяны в
/var/lib/grafana, provisioning пустой), а SaaS-путь «руками в UI» не воспроизводим.
Скрипт кладёт JSON из репозитория поверх дашборда с тем же uid — идемпотентно.
Дашборд живёт в PVC Grafana и переживает рестарт пода; `helm upgrade higress-console`
его не удаляет (uid/JSON в БД), но переустановка Grafana с нуля — удалит, тогда
запустить скрипт снова (architecture/specs/monitoring-spec.md).

Использование:
    python3 scripts/grafana_import_dashboard.py                 # все JSON из каталога дашбордов
    python3 scripts/grafana_import_dashboard.py path/to/dash.json
    python3 scripts/grafana_import_dashboard.py --check          # только проверить наличие/версию
    python3 scripts/grafana_import_dashboard.py --context demo-ai-lab

Креды администратора Grafana — из окружения консоли (HIGRESS_CONSOLE_DASHBOARD_USERNAME/PASSWORD),
в репозиторий не попадают. Код выхода: 0 — импортировано/на месте, 1 — ошибка.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

NS = "higress-system"
CONSOLE_DEPLOY = "higress-console"
GRAFANA_SVC = "higress-console-grafana"
GRAFANA_PORT = 3000
DASH_GLOB = "gitops/infra-apps/monitoring/dashboards/*.json"


def sh(*args: str) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {res.stderr.strip()}")
    return res.stdout


def console_env(ctx: str) -> tuple[str, str]:
    raw = sh("kubectl", f"--context={ctx}", "-n", NS, "get", "deploy", CONSOLE_DEPLOY, "-o", "json")
    env = {e["name"]: e.get("value", "")
           for e in json.loads(raw)["spec"]["template"]["spec"]["containers"][0]["env"]}
    user = env.get("HIGRESS_CONSOLE_DASHBOARD_USERNAME", "")
    pwd = env.get("HIGRESS_CONSOLE_DASHBOARD_PASSWORD", "")
    if not user or not pwd:
        raise RuntimeError("в окружении консоли нет Grafana-кредов (HIGRESS_CONSOLE_DASHBOARD_*)")
    return user, pwd


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PortForward:
    def __init__(self, ctx: str):
        self.port = free_port()
        self.proc = subprocess.Popen(
            ["kubectl", f"--context={ctx}", "-n", NS, "port-forward",
             f"svc/{GRAFANA_SVC}", f"{self.port}:{GRAFANA_PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.25)
        self.close()
        raise RuntimeError("port-forward до Grafana не поднялся")

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def api(port: int, path: str, auth: str, data: dict | None = None,
        method: str | None = None) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{port}/grafana/api/{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Basic " + auth)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=None)
    ap.add_argument("--context", default="demo-ai-lab")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(DASH_GLOB))
    if not files:
        print(f"FAIL: нет файлов дашбордов ({DASH_GLOB})", file=sys.stderr)
        return 1
    user, pwd = console_env(args.context)
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()

    pf = PortForward(args.context)
    rc = 0
    try:
        for path in files:
            dash = json.load(open(path))
            uid, title = dash.get("uid"), dash.get("title")
            status, cur = api(pf.port, f"dashboards/uid/{uid}", auth)
            if args.check:
                state = "есть" if status == 200 else "нет"
                ver = cur.get("dashboard", {}).get("version", "-") if status == 200 else "-"
                print(f"{uid}: {state} (version={ver}, panels={len(dash.get('panels', []))}) — {title}")
                rc |= 0 if status == 200 else 1
                continue
            st, body = api(pf.port, "dashboards/db", auth,
                           {"dashboard": dash, "overwrite": True, "message": "import from repo"})
            if st != 200:
                print(f"FAIL {path}: {st} {body}", file=sys.stderr)
                rc = 1
                continue
            print(f"OK {uid}: импортирован (version={body.get('version')}, url={body.get('url')})")
    finally:
        pf.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
