#!/usr/bin/env python3
"""env_health.py — проверка «обвязки» стенда demo-ai-lab (всё, что вне кластера).

Два блока:
  1) внешняя VM-egress (SberCloud, единый коннектор туннеля): SSH-доступ, ресурсы,
     cloudflared, haproxy, оба SSH-hop до origin и сквозной ответ origin через hop;
  2) Cloudflare-туннель через API (status, соединения, egress коннектора) и внешний путь
     через edge — с подтверждением из внешних точек check-host, потому что консоль стоит
     за ZTN и видит edge из colo FRA (её вердикт в одиночку не показателен).

Кластер проверяет scripts/k8s_health.py — здесь только обвязка.

Зависимости: только стандартная библиотека Python 3.9+; из PATH — ssh, curl,
опционально kubectl (взять API-токен Cloudflare из кластерного Secret) и nc (статистика haproxy).

Примеры:
    python3 scripts/env_health.py                    # полный прогон
    python3 scripts/env_health.py --brief            # только «не-зелёное»
    python3 scripts/env_health.py --json             # машинный вывод
    python3 scripts/env_health.py --no-vm            # без SSH к внешней VM
    python3 scripts/env_health.py --vm u@h --no-check-host

Коды выхода: 0 — всё зелёное, 2 — есть WARN, 1 — есть FAIL.

Приватность: в скрипте нет логинов, адресов VM, MAC и токенов. Цель SSH берётся из
(1) --vm user@host, (2) env ENV_HEALTH_VM, (3) inventory.local.md (gitignored).
Токен Cloudflare — из env CF_API_TOKEN / CLOUDFLARE_API_TOKEN либо из кластерного Secret.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import http.cookiejar
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
SEVERITY = {OK: 0, SKIP: 0, WARN: 1, FAIL: 2}

COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[90m"}
RESET = "\033[0m"
ICONS = {OK: "✔", WARN: "▲", FAIL: "✘", SKIP: "·"}
SECTION_TITLES = {
    "vm": "Внешняя VM-egress",
    "tunnel": "Cloudflare-туннель",
    "edge": "Внешний путь",
}

# Публичные константы стенда (см. architecture/external-access-spec.md).
PUBLIC_HOST = "demo-ai-lab.ru"
ECHO_HOST = "echo.demo-ai-lab.ru"
HAPROXY_PORT = 19443
HOP_PORTS = (18443, 18444)


def paint(text: str, status: str, enabled: bool) -> str:
    return f"{COLORS[status]}{text}{RESET}" if enabled else text


def format_line(entry: dict, color: bool, elapsed: float | None = None) -> str:
    head = paint(f"{ICONS[entry['status']]} {entry['title']}", entry["status"], color)
    tail = f"  ({elapsed:.1f} c)" if elapsed is not None else ""
    return f"  {head}: {entry['detail']}{tail}"


class Report:
    """Секции проверок + сводка. Строки печатаются сразу по готовности шага."""

    def __init__(self, stream: bool = False, color: bool = False, brief: bool = False) -> None:
        self.sections: list[dict] = []
        self.stream = stream
        self.color = color
        self.brief = brief
        self._section: str | None = None
        self._t0 = 0.0
        self._elapsed_shown = False

    def phase(self, label: str) -> None:
        self._t0, self._elapsed_shown = time.monotonic(), False
        if self.stream:
            print(paint(f"… {label}", SKIP, self.color), file=sys.stderr, flush=True)

    def add(self, section: str, title: str, status: str, detail: str = "", rows: list[str] | None = None) -> None:
        entry = {"section": section, "title": title, "status": status, "detail": detail, "rows": rows or []}
        self.sections.append(entry)
        if not self.stream:
            return
        if self.brief and status == OK:
            return
        if section != self._section:
            self._section = section
            print(f"\n{SECTION_TITLES.get(section, section)}", flush=True)
        elapsed = None
        if self._t0 and not self._elapsed_shown:
            elapsed, self._elapsed_shown = time.monotonic() - self._t0, True
        print(format_line(entry, self.color, elapsed), flush=True)
        for row in entry["rows"]:
            print(f"      {row}", flush=True)

    def worst(self) -> str:
        worst = OK
        for s in self.sections:
            if SEVERITY[s["status"]] > SEVERITY[worst]:
                worst = s["status"]
        return worst

    def counts(self) -> dict:
        c = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
        for s in self.sections:
            c[s["status"]] += 1
        return c


# ---------------------------------------------------------------- утилиты


def run(cmd: list[str] | str, timeout: int = 25) -> tuple[int, str, str]:
    """Запуск внешней команды. Никогда не бросает: (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd if isinstance(cmd, list) else shlex.split(cmd),
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout {timeout}s"
    except FileNotFoundError as e:
        return 127, "", f"not found: {e}"
    except Exception as e:  # noqa: BLE001 — диагностический скрипт не должен падать
        return 1, "", str(e)


def http_get(url: str, timeout: int = 8, headers: dict | None = None) -> tuple[int, dict, str]:
    """GET без падений: (код, заголовки, тело). Код 000 — сеть/таймаут."""
    req = urllib.request.Request(url, headers=headers or {})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return 0, {}, ""


def resolve_vm_target(cli: str | None) -> str:
    """--vm → env ENV_HEALTH_VM → inventory.local.md (раздел «Внешний egress»)."""
    if cli:
        return cli
    env = os.environ.get("ENV_HEALTH_VM", "").strip()
    if env:
        return env
    inv = REPO_ROOT / "inventory.local.md"
    if not inv.exists():
        return ""
    text = inv.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^##\s+Внешний egress.*?(?=^##\s|\Z)", text, re.M | re.S)
    scope = m.group(0) if m else text
    hit = re.search(r"ssh\s+([\w.@-]+@(?:[0-9]{1,3}\.){3}[0-9]{1,3})", scope)
    return hit.group(1) if hit else ""


# ---------------------------------------------------------------- 1. внешняя VM

VM_SCRIPT = r"""
echo "HOST=$(hostname -s 2>/dev/null)"
echo "UPTIME=$(uptime -s 2>/dev/null)"
echo "LOAD=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
echo "MEM=$(free -m 2>/dev/null | awk '/Mem:/ {print $3"/"$2}')"
echo "DISK=$(df -P / 2>/dev/null | awk 'NR==2 {print $5}')"
echo "CFVER=$(cloudflared --version 2>/dev/null | head -1)"
echo "CFACT=$(systemctl is-active cloudflared 2>/dev/null)"
echo "HPACT=$(systemctl is-active haproxy 2>/dev/null)"
echo "LISTEN=$(ss -tln 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$' | grep -E '^(19443|18443|18444)$' | sort -u | paste -sd, -)"
echo "HAPSTAT=$(echo 'show stat' | sudo -n nc -U /run/haproxy/admin.sock 2>/dev/null | grep '^origin,k8s' | cut -d, -f2,18 | paste -sd' ' -)"
echo "ORIGIN=$(curl -s -o /dev/null -w '%{http_code}' --resolve demo-ai-lab.ru:19443:127.0.0.1 --max-time 10 https://demo-ai-lab.ru:19443/ 2>/dev/null)"
"""


def parse_kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def check_vm(rep: Report, target: str, timeout: int) -> str:
    """Возвращает IP внешней VM (для сверки egress коннектора) или ''."""
    if not target:
        rep.add("vm", "Внешняя VM", SKIP,
                "цель не задана: --vm user@host, env ENV_HEALTH_VM или inventory.local.md")
        return ""

    vm_ip = target.split("@")[-1]
    rc, out, err = run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new",
         target, VM_SCRIPT],
        timeout=timeout,
    )
    if rc != 0 or "HOST=" not in out:
        tail = (err or out).strip().splitlines()[-1] if (err or out).strip() else f"rc={rc}"
        rep.add("vm", "Внешняя VM (SSH)", FAIL, f"{vm_ip}: {tail}")
        return vm_ip

    d = parse_kv(out)
    rep.add("vm", "Внешняя VM (SSH)", OK,
            f"{d.get('HOST', '?')} ({vm_ip}), boot {d.get('UPTIME', '?')}, load {d.get('LOAD', '?')}, "
            f"RAM {d.get('MEM', '?')}M, root {d.get('DISK', '?')}")

    cf_act, cf_ver = d.get("CFACT", "?"), d.get("CFVER", "")
    rep.add("vm", "cloudflared на VM", OK if cf_act == "active" else FAIL,
            f"systemctl: {cf_act}" + (f", {cf_ver}" if cf_ver else ""))

    hp_act = d.get("HPACT", "?")
    rep.add("vm", "haproxy на VM", OK if hp_act == "active" else FAIL, f"systemctl: {hp_act}")

    stat = d.get("HAPSTAT", "")
    backends = dict(x.split(",") for x in stat.split() if "," in x)
    if not backends:
        rep.add("vm", "Бэкенды haproxy (hop-и)", FAIL,
                "статистика недоступна — hop-и не подняты или haproxy без stats-сокета")
    else:
        up = [k for k, v in backends.items() if v == "UP"]
        detail = ", ".join(f"{k}={v}" for k, v in sorted(backends.items()))
        st = OK if len(up) == len(backends) else (WARN if up else FAIL)
        rep.add("vm", "Бэкенды haproxy (hop-и)", st, f"{len(up)}/{len(backends)} UP ({detail})")

    listen = {int(p) for p in (d.get("LISTEN") or "").split(",") if p.strip().isdigit()}
    want = {HAPROXY_PORT, *HOP_PORTS}
    missing = sorted(want - listen)
    rep.add("vm", f"Слушатели {HAPROXY_PORT}/{','.join(map(str, HOP_PORTS))}",
            OK if not missing else (WARN if HAPROXY_PORT not in missing else FAIL),
            "все на месте (loopback)" if not missing else f"нет портов: {', '.join(map(str, missing))}")

    origin = d.get("ORIGIN", "000")
    rep.add("vm", "Origin через hop (19443)", OK if origin == "200" else FAIL,
            f"https://{PUBLIC_HOST} через 127.0.0.1:{HAPROXY_PORT} → {origin}")
    return vm_ip


# ---------------------------------------------------------------- 2. туннель


def cf_token(kubeconfig: str) -> str:
    tok = os.environ.get("CF_API_TOKEN") or os.environ.get("CLOUDFLARE_API_TOKEN")
    if tok:
        return tok.strip()
    rc, out, _ = run(["kubectl", "--kubeconfig", os.path.expanduser(kubeconfig), "get", "secret",
                      "cloudflare-api-token", "-n", "cert-manager", "-o", "jsonpath={.data.api-token}"], timeout=15)
    if rc != 0 or not out.strip():
        return ""
    try:
        return base64.b64decode(out.strip()).decode()
    except Exception:  # noqa: BLE001
        return ""


def check_tunnel(rep: Report, kubeconfig: str, vm_ip: str) -> None:
    tok = cf_token(kubeconfig)
    if not tok:
        rep.add("tunnel", "Cloudflare-туннель (API)", SKIP,
                "нет токена: env CF_API_TOKEN или secret cert-manager/cloudflare-api-token через kubectl")
        return

    def api(path: str):
        req = urllib.request.Request(f"https://api.cloudflare.com/client/v4{path}",
                                     headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=15, context=ssl.create_default_context()) as r:
            return json.loads(r.read())

    try:
        zones = api(f"/zones?name={PUBLIC_HOST}")["result"]
        if not zones:
            rep.add("tunnel", "Cloudflare-туннель (API)", WARN, "зона не найдена токеном (нет Zone:Read?)")
            return
        zone = zones[0]
        acct = (zone.get("account") or {}).get("id")
        if not acct:
            rep.add("tunnel", "Cloudflare-туннель (API)", WARN, "account_id не получен из объекта зоны")
            return
        recs = api(f"/zones/{zone['id']}/dns_records?name={PUBLIC_HOST}")["result"]
        cname = next((r for r in recs if r.get("type") == "CNAME"), None)
        if not cname:
            rep.add("tunnel", "Cloudflare-туннель (API)", WARN, f"DNS {PUBLIC_HOST}: CNAME на *.cfargotunnel.com нет")
            return
        tid = cname["content"].split(".")[0]
        t = api(f"/accounts/{acct}/cfd_tunnel/{tid}")["result"]
        conns = t.get("connections") or []
        colos = sorted({c.get("colo_name", "?") for c in conns})
        status = t.get("status")
        st = OK if status == "healthy" and conns else (WARN if conns else FAIL)
        rep.add("tunnel", "Cloudflare-туннель (API)", st,
                f"{t.get('name', tid)}: status={status}, соединений {len(conns)}"
                + (f" ({', '.join(colos)})" if colos else ""))

        if conns and vm_ip:
            ips = {c.get("origin_ip") for c in conns}
            rep.add("tunnel", "Egress коннектора", OK if ips == {vm_ip} else WARN,
                    f"{', '.join(sorted(i for i in ips if i))}" +
                    ("" if ips == {vm_ip} else f" — ожидался только {vm_ip}"))
    except Exception as e:  # noqa: BLE001
        rep.add("tunnel", "Cloudflare-туннель (API)", SKIP, f"API Cloudflare недоступен: {e}")


# ---------------------------------------------------------------- 3. внешний путь


def edge_codes(host: str, samples: int, timeout: int) -> list[str]:
    codes = []
    for _ in range(samples):
        rc, out, _ = run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout), f"https://{host}/"],
            timeout=timeout + 4,
        )
        codes.append(out.strip() if rc == 0 else "000")
    return codes


def check_host_points(samples_nodes: int = 6, wait: int = 30) -> list[tuple[str, str]]:
    """Внешние точки check-host.net: [(страна, код HTTP)] либо [] если сервис не отдал данные.

    check-host отбивает запросы без браузерного User-Agent (403) — поэтому заголовки заданы явно.
    """
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) env-health/1.0"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        url = (f"https://check-host.net/check-http?host={urllib.parse.quote(f'https://{PUBLIC_HOST}/', safe='')}"
               f"&max_nodes={samples_nodes}")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": ua})
        with opener.open(req, timeout=15) as r:
            start = json.loads(r.read())
        rid, nodes = start.get("request_id"), start.get("nodes") or {}
        if not rid:
            return []
        deadline = time.monotonic() + wait
        res: dict = {}
        while time.monotonic() < deadline:
            time.sleep(6)
            req = urllib.request.Request(f"https://check-host.net/check-result/{rid}",
                                         headers={"Accept": "application/json",
                                                  "Referer": "https://check-host.net/",
                                                  "User-Agent": ua})
            with opener.open(req, timeout=15) as r:
                res = json.loads(r.read())
            if res and all(v is not None for v in res.values()):
                break
        out = []
        for node, val in (res or {}).items():
            if not val:
                continue
            country = (nodes.get(node) or ["?"])[0]
            code = "?"
            try:
                # формат check-host: [[1, 0.26, "OK", "200", "<ip>"], ...]
                item = val[0]
                if isinstance(item, list) and len(item) >= 4:
                    code = str(item[3])
                elif isinstance(item, dict):
                    code = str(item.get("status_code") or item.get("status") or "?")
            except Exception:  # noqa: BLE001
                pass
            out.append((country, code))
        return out
    except Exception:  # noqa: BLE001
        return []


def check_edge(rep: Report, samples: int, timeout: int, use_check_host: bool) -> None:
    codes = edge_codes(PUBLIC_HOST, samples, timeout)
    tally = ", ".join(f"{c}×{codes.count(c)}" for c in sorted(set(codes)))
    good = sum(1 for c in codes if c == "200")
    st = OK if good == len(codes) else (WARN if good else FAIL)
    rep.add("edge", "Сквозной путь через edge", st, f"{good}/{len(codes)} ответов 200 ({tally})")

    if use_check_host and good != len(codes):
        points = check_host_points()
        if not points:
            rep.add("edge", "Внешние точки (check-host)", SKIP, "check-host.net не отдал результат (лимит/недоступен)")
        else:
            ok_pts = sum(1 for _, c in points if c == "200")
            st2 = OK if ok_pts == len(points) else (WARN if ok_pts else FAIL)
            verdict = ("консоль за ZTN смотрит в colo FRA — её вердикт смещён, верим check-host"
                       if ok_pts == len(points) else "проблема внешнего пути подтверждена извне")
            rep.add("edge", "Внешние точки (check-host)", st2,
                    f"{ok_pts}/{len(points)} точек 200 — {verdict}",
                    rows=[f"{country:<12} {code}" for country, code in sorted(points)])

    echo = edge_codes(ECHO_HOST, 1, timeout)[0]
    rep.add("edge", f"Smoke-хост {ECHO_HOST}", OK if echo == "200" else WARN,
            f"https://{ECHO_HOST}/ → {echo}" + ("" if echo == "200" else " (постоянный тестовый маршрут)"))


# ---------------------------------------------------------------- вывод


def color_enabled(args) -> bool:
    if args.no_color or args.json_out or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def render(rep: Report, brief: bool, json_out: bool, color: bool) -> None:
    if json_out:
        print(json.dumps({"worst": rep.worst(), "counts": rep.counts(), "checks": rep.sections},
                         ensure_ascii=False, indent=2))
        return
    if not rep.stream:
        print(f"demo-ai-lab · проверка обвязки · {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}")
        current = None
        for s in rep.sections:
            if brief and s["status"] == OK:
                continue
            if s["section"] != current:
                print(f"\n{SECTION_TITLES.get(s['section'], s['section'])}")
                current = s["section"]
            print(format_line(s, color))
            for row in s["rows"]:
                print(f"      {row}")
    c, worst = rep.counts(), rep.worst()
    print("\n" + paint(f"ИТОГО: {c[OK]} PASS · {c[WARN]} WARN · {c[FAIL]} FAIL · {c[SKIP]} SKIP "
                       f"→ {'OK' if worst == OK else worst}", worst, color))
    if worst == FAIL:
        print("Разбор — skill demo-ai-lab-stand: обвязка описана в architecture/external-access-spec.md §E7.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка обвязки стенда demo-ai-lab: внешняя VM-egress, Cloudflare-туннель")
    ap.add_argument("--vm", metavar="user@host", help="SSH-цель внешней VM (по умолчанию env ENV_HEALTH_VM / inventory.local.md)")
    ap.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", "~/.kube/demo-ai-lab.conf"),
                    help="kubeconfig для чтения API-токена Cloudflare")
    ap.add_argument("--no-vm", action="store_true", help="не проверять внешнюю VM")
    ap.add_argument("--no-tunnel", action="store_true", help="не проверять туннель через Cloudflare API")
    ap.add_argument("--no-edge", action="store_true", help="не проверять внешний путь через edge")
    ap.add_argument("--no-check-host", action="store_true", help="не подтверждать внешний путь через check-host.net")
    ap.add_argument("--samples", type=int, default=4, help="число запросов к edge (по умолчанию 4)")
    ap.add_argument("--timeout", type=int, default=20, help="таймаут операций, с (по умолчанию 20)")
    ap.add_argument("--brief", action="store_true", help="показывать только WARN/FAIL")
    ap.add_argument("--json", action="store_true", dest="json_out", help="машинный вывод")
    ap.add_argument("--no-color", action="store_true", help="без ANSI-цвета (по умолчанию — только в TTY)")
    args = ap.parse_args()

    color = color_enabled(args)
    stream = not args.json_out
    if stream:
        print(f"demo-ai-lab · проверка обвязки · {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}", flush=True)
    rep = Report(stream=stream, color=color, brief=args.brief)

    vm_ip = ""
    if not args.no_vm:
        rep.phase("внешняя VM: доступ, cloudflared, haproxy, hop-и")
        vm_ip = check_vm(rep, resolve_vm_target(args.vm), max(20, args.timeout))

    if not args.no_tunnel:
        rep.phase("Cloudflare API: туннель и соединения")
        check_tunnel(rep, args.kubeconfig, vm_ip)

    if not args.no_edge:
        rep.phase(f"внешний путь ({args.samples} запросов к edge)")
        check_edge(rep, args.samples, min(12, args.timeout), not args.no_check_host)

    render(rep, args.brief, args.json_out, color)
    return 0 if rep.worst() == OK else (1 if rep.worst() == FAIL else 2)


if __name__ == "__main__":
    sys.exit(main())
