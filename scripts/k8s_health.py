#!/usr/bin/env python3
"""k8s_health.py — быстрая проверка состояния и здоровья кластера демо-стенда demo-ai-lab.

Один проход по чек-листу приёмки: API/VIP -> ноды+pressure -> health-gate подов -> etcd ->
control-plane/kube-vip -> Argo/Longhorn/Higress -> живой SSH-замер нод -> origin в LAN.

Обвязку (локальный реестр, внешняя VM-egress, Cloudflare-туннель и внешний путь через edge)
проверяет отдельный скрипт scripts/env_health.py — здесь только кластер.

Зависимости: только стандартная библиотека Python 3.9+ (kubectl, ssh, curl, openssl — из PATH).

Примеры:
    python3 scripts/k8s_health.py                     # полный аудит, человекочитаемо
    python3 scripts/k8s_health.py --brief             # только «не-зелёное» + сводка
    python3 scripts/k8s_health.py --json              # машинный вывод (для cron/дашборда)
    python3 scripts/k8s_health.py --no-origin --no-ssh

Коды выхода: 0 — всё зелёное, 2 — есть WARN, 1 — есть FAIL.

Приватность: в скрипте нет логинов, MAC и паролей. SSH-цели берутся из (
1) --ssh user@host, (2) env K8S_HEALTH_SSH="u1@h1,u2@h2", (3) ansible/hosts.cluster.yml
(IP оттуда + логин из env K8S0X_USER), (4) inventory.local.md (локальный, gitignored).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
SEVERITY = {OK: 0, SKIP: 0, WARN: 1, FAIL: 2}

# Оформление: цвет по критичности (только в TTY, см. color_enabled).
COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[90m"}
RESET = "\033[0m"
ICONS = {OK: "✔", WARN: "▲", FAIL: "✘", SKIP: "·"}
SECTION_TITLES = {
    "api": "Доступ к API", "nodes": "Ноды", "pods": "Поды", "etcd": "etcd",
    "cp": "Control plane", "vip": "VIP", "argo": "GitOps", "longhorn": "Хранилище",
    "higress": "Ingress", "ssh": "Железо по SSH", "ext": "Origin (LAN)",
    "warn": "Диагностика",
}

# Константы стенда (публичные, см. network-map-detail.md / ARCHITECTURE.md).
API_VIP = "192.168.10.240"
INGRESS_VIP = "192.168.10.230"
PUBLIC_HOST = "demo-ai-lab.ru"
CP_LOCK = "plndr-cp-lock"
SVC_LOCK = "plndr-svcs-lock"
EXPECTED_NODES = 4
EXPECTED_ETCD = 3


def paint(text: str, status: str, enabled: bool) -> str:
    """Цвет по критичности. Ничего не решает — только оформление строки."""
    return f"{COLORS[status]}{text}{RESET}" if enabled else text


def format_line(entry: dict, color: bool, elapsed: float | None = None) -> str:
    head = paint(f"{ICONS[entry['status']]} {entry['title']}", entry["status"], color)
    tail = f"  ({elapsed:.1f} c)" if elapsed is not None else ""
    return f"  {head}: {entry['detail']}{tail}"


def format_node_rows(entry: dict) -> list[str]:
    """Расшифровка SSH-замера: по строке на ноду."""
    out = []
    for r in entry.get("data") or []:
        if r.get("error"):
            out.append(f"      {r['node']:<7} {r.get('ip', ''):<15} — {r['error']}")
        else:
            out.append(
                f"      {r['node']:<7} {r.get('ip', ''):<15} boot {r.get('boot_msk', '?')}  "
                f"load {r.get('load', '?')}  RAM {r.get('mem_avail', '?')}/{r.get('mem_total', '?')}M "
                f"({r.get('mem_avail_pct', '?')}%)  root {r.get('disk_used', '?')}  "
                f"cloudflared={r.get('cloudflared', '?')}  VIP={r.get('vip') or '—'}"
            )
    return out


class Report:
    """Секции проверок + сводка.

    При stream=True каждая проверка печатается сразу по готовности (stdout), а её ход
    отмечается строкой «… шаг» в stderr — видно, на чём скрипт стоит прямо сейчас.
    """

    def __init__(self, stream: bool = False, color: bool = False, brief: bool = False) -> None:
        self.sections: list[dict] = []
        self.stream = stream
        self.color = color
        self.brief = brief
        self._section: str | None = None
        self._t0 = 0.0
        self._elapsed_shown = False

    def phase(self, label: str) -> None:
        """Текущий шаг: печатается в stderr, чтобы не засорять парсируемый stdout."""
        self._t0, self._elapsed_shown = time.monotonic(), False
        if self.stream:
            print(paint(f"… {label}", SKIP, self.color), file=sys.stderr, flush=True)

    def add(self, section: str, title: str, status: str, detail: str = "", data=None) -> None:
        entry = {"section": section, "title": title, "status": status, "detail": detail, "data": data}
        self.sections.append(entry)
        if not self.stream:
            return
        if self.brief and status == OK:
            return  # в --brief заголовок секции тоже не нужен, если в ней нечего показать
        if section != self._section:
            self._section = section
            print(f"\n{SECTION_TITLES.get(section, section)}", flush=True)
        elapsed = None
        if self._t0 and not self._elapsed_shown:
            elapsed, self._elapsed_shown = time.monotonic() - self._t0, True
        print(format_line(entry, self.color, elapsed), flush=True)
        if section == "ssh" and data:
            for row in format_node_rows(entry):
                print(row, flush=True)

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


def run(cmd: list[str] | str, timeout: int = 25, stdin: str | None = None) -> tuple[int, str, str]:
    """Запуск внешней команды. Никогда не бросает: возвращает (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd if isinstance(cmd, list) else shlex.split(cmd),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout {timeout}s"
    except FileNotFoundError as e:
        return 127, "", f"not found: {e}"
    except Exception as e:  # noqa: BLE001 — диагностический скрипт не должен падать
        return 1, "", str(e)


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def msk(ts: dt.datetime) -> str:
    """UTC -> Europe/Moscow (стенд живёт в UTC, консоль — MSK)."""
    try:
        from zoneinfo import ZoneInfo

        return ts.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M MSK")
    except Exception:  # noqa: BLE001
        return (ts + dt.timedelta(hours=3)).strftime("%d.%m %H:%M MSK")


class Kube:
    """Обёртка над kubectl: контекст из kubeconfig, опционально с override сервера."""

    def __init__(self, kubeconfig: str, context: str | None, timeout: int = 25) -> None:
        self.kubeconfig = os.path.expanduser(kubeconfig)
        self.context = context
        self.timeout = timeout
        self.server_override: str | None = None
        self.insecure = False

    def _base(self) -> list[str]:
        cmd = ["kubectl", f"--kubeconfig={self.kubeconfig}"]
        if self.context and not self.server_override:
            cmd.append(f"--context={self.context}")
        if self.server_override:
            cmd.append(f"--server={self.server_override}")
        if self.insecure:
            cmd.append("--insecure-skip-tls-verify=true")
        return cmd

    def raw(self, *args: str, timeout: int | None = None) -> tuple[int, str]:
        rc, out, err = run(self._base() + list(args), timeout=timeout or self.timeout)
        return rc, out if rc == 0 else (err.strip() or out.strip())

    def json(self, *args: str, timeout: int | None = None):
        rc, out = self.raw(*args, "-o", "json", timeout=timeout)
        if rc != 0:
            return None, out
        try:
            return json.loads(out), ""
        except json.JSONDecodeError as e:
            return None, f"bad json: {e}"

    def alive(self, timeout: int = 8) -> bool:
        rc, _ = self.raw("get", "--raw", "/readyz", timeout=timeout)
        return rc == 0


# ---------------------------------------------------------------- инвентарь SSH


def resolve_ssh_targets(cli: list[str]) -> tuple[dict[str, str], str]:
    """user@host -> {ip: user}. Источники по приоритету, без секретов в репозитории."""
    pairs: list[str] = []
    source = ""
    if cli:
        pairs, source = cli, "--ssh"
    elif os.environ.get("K8S_HEALTH_SSH"):
        pairs, source = os.environ["K8S_HEALTH_SSH"].split(","), "env K8S_HEALTH_SSH"
    else:
        hosts_file = REPO_ROOT / "ansible" / "hosts.cluster.yml"
        if hosts_file.exists():
            text = hosts_file.read_text(encoding="utf-8", errors="replace")
            blocks = re.finditer(
                r"(k8s-0\d):\s*\n\s*ansible_host:\s*([\d.]+)\s*\n\s*ansible_user:\s*\"\{\{\s*lookup\('env',\s*'(\w+)'\)\s*\}\}\"",
                text,
            )
            for m in blocks:
                user = os.environ.get(m.group(3), "")
                if user:
                    pairs.append(f"{user}@{m.group(2)}")
            if pairs:
                source = "ansible/hosts.cluster.yml + env K8S0X_USER"
        if not pairs:
            inv = REPO_ROOT / "inventory.local.md"
            if inv.exists():
                text = inv.read_text(encoding="utf-8", errors="replace")
                pairs = sorted(set(re.findall(r"\b([a-z][a-z0-9_]{2,})@(192\.168\.10\.\d{1,3})\b", text)))
                pairs = [f"{u}@{ip}" for u, ip in pairs]
                if pairs:
                    source = "inventory.local.md"
    targets: dict[str, str] = {}
    for p in pairs:
        p = p.strip()
        if "@" in p:
            user, ip = p.rsplit("@", 1)
            targets[ip] = user
    return targets, source


def ssh_exec(user: str, host: str, script: str, timeout: int = 12) -> tuple[int, str, str]:
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "bash -s",
    ]
    return run(cmd, timeout=timeout, stdin=script)


NODE_PROBE_SCRIPT = r"""
set -u
echo "HOSTNAME=$(hostname)"
echo "UPTIME_S=$(uptime -s 2>/dev/null || echo '')"
echo "EPOCH=$(date -u +%s)"
echo "LOAD=$(cut -d' ' -f1-3 /proc/loadavg)"
echo "NPROC=$(nproc 2>/dev/null || echo 0)"
free -m | awk '/Mem:/{print "MEM_TOTAL="$2; print "MEM_AVAIL="$7}'
df -P / | awk 'NR==2{print "DISK_TOTAL="$2; print "DISK_USED="$5}'
echo "CLOUDFLARED=$(systemctl is-active cloudflared 2>/dev/null || echo n/a)"
echo "KUBELET=$(systemctl is-active kubelet 2>/dev/null || echo n/a)"
echo "CONTAINERD=$(systemctl is-active containerd 2>/dev/null || echo n/a)"
echo "VIP=$(ip -4 -br addr show 2>/dev/null | grep -oE '192\.168\.10\.(230|240)' | sort -u | tr '\n' ',' )"
echo "BOOTS=$(journalctl --list-boots 2>/dev/null | wc -l)"
"""


# ---------------------------------------------------------------- проверки


def check_api(k: Kube, ssh_targets: dict[str, str], rep: Report) -> bool:
    """API через VIP. Если нет — ищем, живёт ли control plane на нодах (дедлок VIP)."""
    if k.alive():
        rc, out = k.raw("version", "-o", "json", timeout=10)
        ver = ""
        try:
            ver = json.loads(out)["serverVersion"]["gitVersion"]
        except Exception:  # noqa: BLE001
            ver = "?"
        rep.add("api", "API через VIP", OK, f"https://{API_VIP}:6443 доступен, сервер {ver}")
        return True

    rep.add(
        "api",
        "API через VIP",
        FAIL,
        f"https://{API_VIP}:6443 недоступен (kubeconfig: {k.kubeconfig})",
    )

    # Ищем живой apiserver по нодовым адресам.
    candidates = [ip for ip in ssh_targets if tcp_open(ip, 6443)] or []
    if not candidates:
        hint = (
            "порт 6443 закрыт на всех известных нодах — control plane не поднялся "
            "(питание/etcd/VIP, см. references/status-audit.md §10)"
            if ssh_targets
            else "нечем проверять ноды: передай --ssh user@host или настрой инвентарь"
        )
        rep.add("api", "API напрямую на control-plane", FAIL, hint)
        return False

    rep.add(
        "api",
        "API напрямую на control-plane",
        WARN,
        f"6443 отвечает на {', '.join(candidates)} — apiserver живёт, но VIP {API_VIP} не держится",
    )

    for ip in candidates:
        k.server_override = f"https://{ip}:6443"
        k.insecure = True
        if k.alive():
            rep.add(
                "api",
                "Диагностика через нодовый apiserver",
                WARN,
                f"состояние прочитано через {ip}; вероятная причина — дедлок kube-vip "
                f"(admin.conf смотрит в VIP {API_VIP}, а VIP держит только избранный лидер). "
                f"Лечение: `sudo ip addr add {API_VIP}/32 dev eno1` на одном CP, дождаться лидера "
                f"lease {CP_LOCK}, затем `sudo ip addr del ...`",
            )
            return True
    rep.add("api", "Диагностика через нодовый apiserver", FAIL, "apiserver отвечает по TCP, но не отдаёт API")
    return False


def check_nodes(k: Kube, rep: Report) -> list[dict]:
    data, err = k.json("get", "nodes")
    if not data:
        rep.add("nodes", "Ноды", FAIL, f"не удалось получить список нод: {err}")
        return []
    nodes = []
    problems = []
    for it in data.get("items", []):
        name = it["metadata"]["name"]
        conds = {c["type"]: c["status"] for c in it["status"].get("conditions", [])}
        roles = [r.split("/")[-1] for r in it["metadata"].get("labels", {}) if r.startswith("node-role.kubernetes.io/")]
        addr = next((a["address"] for a in it["status"].get("addresses", []) if a["type"] == "InternalIP"), "")
        node = {
            "name": name,
            "ready": conds.get("Ready"),
            "roles": roles or ["worker"],
            "ip": addr,
            "version": it["status"].get("nodeInfo", {}).get("kubeletVersion", ""),
            "pressure": {c: conds.get(c) for c in ("MemoryPressure", "DiskPressure", "PIDPressure")},
        }
        nodes.append(node)
        if node["ready"] != "True":
            problems.append(f"{name} NotReady")
        for c, v in node["pressure"].items():
            if v == "True":
                problems.append(f"{name} {c}")
    status = OK if not problems else FAIL
    detail = "; ".join(problems) if problems else f"{len(nodes)}/{EXPECTED_NODES} Ready, давление не выставлено"
    rep.add("nodes", "Ноды и pressure", status, detail, data=nodes)
    if len(nodes) != EXPECTED_NODES:
        rep.add("nodes", "Состав кластера", WARN, f"нод {len(nodes)}, ожидалось {EXPECTED_NODES}")
    return nodes


def check_pods(k: Kube, rep: Report) -> None:
    data, err = k.json("get", "pods", "-A")
    if not data:
        rep.add("pods", "Health-gate подов", FAIL, f"не удалось получить список подов: {err}")
        return
    items = data.get("items", [])
    bad, per_node, restarts = [], {}, []
    for p in items:
        ns, name = p["metadata"]["namespace"], p["metadata"]["name"]
        phase = p["status"].get("phase", "?")
        node = p["spec"].get("nodeName", "-")
        per_node[node] = per_node.get(node, 0) + 1
        statuses = p["status"].get("containerStatuses") or []
        ready = sum(1 for c in statuses if c.get("ready"))
        total = len(p["spec"].get("containers") or []) or 1
        rest = sum(c.get("restartCount", 0) for c in statuses)
        restarts.append((rest, ns, name, node))
        terminating = p["metadata"].get("deletionTimestamp")
        ok = phase in ("Running", "Succeeded") and ready == total and not terminating
        if not ok:
            reason = "Terminating" if terminating else (
                "Pending" if phase == "Pending" else f"{ready}/{total} ready"
            )
            bad.append(f"{ns}/{name} ({reason} на {node})")

    rep.add(
        "pods",
        "Health-gate подов",
        FAIL if bad else OK,
        "; ".join(bad[:8]) + (f" … ещё {len(bad) - 8}" if len(bad) > 8 else "")
        if bad
        else f"{len(items)} подов Running/Ready",
        data={"total": len(items), "bad": bad, "per_node": per_node},
    )
    rep.add(
        "pods",
        "Поды по нодам",
        OK if sum(per_node.values()) == len(items) else WARN,
        ", ".join(f"{n}: {c}" for n, c in sorted(per_node.items(), key=lambda x: -x[1])),
    )
    top = sorted(restarts, reverse=True)[:5]
    hot = [t for t in top if t[0] >= 5]
    rep.add(
        "pods",
        "Рестарты контейнеров",
        WARN if hot else OK,
        "; ".join(f"{ns}/{name} ({n}, {node})" for n, ns, name, node in top) or "нет данных",
    )


def check_etcd(k: Kube, rep: Report) -> None:
    pods, err = k.json("get", "pods", "-n", "kube-system", "-l", "component=etcd")
    if not pods or not pods.get("items"):
        rep.add("etcd", "etcd", FAIL, f"статик-поды etcd не найдены: {err}")
        return
    names = [p["metadata"]["name"] for p in pods["items"]]
    ready = [
        p["metadata"]["name"]
        for p in pods["items"]
        if all(c.get("ready") for c in (p["status"].get("containerStatuses") or []))
    ]
    # Образ etcd — distroless: shell нет, etcdctl вызывается напрямую аргументами.
    etcdctl = [
        "etcdctl",
        "--endpoints=https://127.0.0.1:2379",
        "--cacert=/etc/kubernetes/pki/etcd/ca.crt",
        "--cert=/etc/kubernetes/pki/etcd/server.crt",
        "--key=/etc/kubernetes/pki/etcd/server.key",
    ]
    members, used = [], ""
    for pod in ready or names:
        rc, out = k.raw("exec", "-n", "kube-system", pod, "--", *etcdctl, "member", "list")
        if rc == 0 and "started" in out:
            used = pod
            for line in out.strip().splitlines():
                f = [x.strip() for x in line.split(",")]
                if len(f) >= 5 and f[1] in ("started", "unstarted"):
                    members.append({"name": f[2], "status": f[1]})
            break
    if not members:
        rep.add(
            "etcd",
            "Кворум etcd",
            FAIL,
            f"member list недоступен (поды: {', '.join(names)}; ready: {', '.join(ready) or '—'})",
        )
        return
    started = sum(1 for m in members if m["status"] == "started")
    quorum = len(members) // 2 + 1
    status = OK if started >= quorum and started == EXPECTED_ETCD else WARN if started >= quorum else FAIL
    rep.add(
        "etcd",
        "Кворум etcd",
        status,
        f"{started}/{len(members)} членов started (кворум {quorum}); опрос через {used}",
        data=members,
    )


def check_control_plane(k: Kube, rep: Report) -> None:
    data, err = k.json("get", "pods", "-n", "kube-system")
    if not data:
        rep.add("cp", "Control-plane поды", FAIL, f"не удалось прочитать kube-system: {err}")
        return
    groups: dict[str, list[str]] = {}
    for p in data.get("items", []):
        name = p["metadata"]["name"]
        for kind in ("kube-apiserver", "kube-controller-manager", "kube-scheduler", "kube-vip-lb", "kube-vip"):
            if name.startswith(kind):
                ready = all(c.get("ready") for c in (p["status"].get("containerStatuses") or []))
                groups.setdefault(kind, []).append(("+" if ready else "-") + name.split("-", 1)[-1])
                break
    expect = {
        "kube-apiserver": 3,
        "kube-controller-manager": 3,
        "kube-scheduler": 3,
        "kube-vip": 3,
        "kube-vip-lb": 2,
    }
    detail_bits, status = [], OK
    for kind, want in expect.items():
        got = groups.get(kind, [])
        ready = [g for g in got if g.startswith("+")]
        if len(ready) < want:
            status = FAIL
        detail_bits.append(f"{kind}: {len(ready)}/{want}")
    rep.add("cp", "Control-plane / kube-vip поды", status, ", ".join(detail_bits))


def check_vips(k: Kube, nodes: list[dict], ssh_targets: dict[str, str], rep: Report) -> None:
    data, err = k.json("get", "lease", "-n", "kube-system", CP_LOCK, SVC_LOCK)
    holders: dict[str, str] = {}
    if data:
        for it in data.get("items", []):
            holders[it["metadata"]["name"]] = (it.get("spec", {}).get("holderIdentity") or "").split("_")[0]
    else:
        rep.add("vip", "Лизы VIP", WARN, f"lease недоступны: {err}")
        return
    cp_holder = holders.get(CP_LOCK, "?")
    svc_holder = holders.get(SVC_LOCK, "?")
    expected = {API_VIP: cp_holder, INGRESS_VIP: svc_holder}

    # Реальные держатели адресов по SSH (если есть доступ).
    actual: dict[str, list[str]] = {API_VIP: [], INGRESS_VIP: []}
    for node in nodes:
        ip, user = node["ip"], ssh_targets.get(node["ip"])
        if not user:
            continue
        rc, out, _ = ssh_exec(user, ip, f"ip -4 -br addr show | grep -oE '{API_VIP}|{INGRESS_VIP}' | sort -u")
        if rc == 0:
            for v in out.split():
                if v in actual:
                    actual[v].append(node["name"])

    def lease_name(ip: str) -> str:
        return cp_holder if ip == API_VIP else svc_holder

    for ip in (API_VIP, INGRESS_VIP):
        lease_h = expected[ip]
        holders_list = actual.get(ip) or []
        if len(holders_list) > 1:
            rep.add("vip", f"VIP {ip}", FAIL, f"адрес на нескольких нодах: {', '.join(holders_list)} (ARP-конфликт)")
        elif ssh_targets and not holders_list and not any(n["ip"] in ssh_targets for n in nodes):
            rep.add("vip", f"VIP {ip}", SKIP, f"lease-держатель {lease_h}, проверка адреса по SSH пропущена")
        elif ssh_targets and not holders_list:
            rep.add("vip", f"VIP {ip}", FAIL, f"lease-держатель {lease_h}, но адреса нет ни на одной ноде")
        else:
            rep.add(
                "vip",
                f"VIP {ip}",
                OK,
                f"держатель {lease_h}" + (f", адрес подтверждён на {holders_list[0]}" if holders_list else ""),
            )


def check_workloads(k: Kube, rep: Report) -> None:
    apps, err = k.json("get", "applications", "-n", "argocd")
    if apps is not None:
        bad = []
        total = 0
        for a in apps.get("items", []):
            total += 1
            sync = a.get("status", {}).get("sync", {}).get("status")
            health = a.get("status", {}).get("health", {}).get("status")
            if sync != "Synced" or health != "Healthy":
                bad.append(f"{a['metadata']['name']}={sync}/{health}")
        rep.add(
            "argo",
            "Argo CD",
            FAIL if bad else OK,
            "; ".join(bad) if bad else f"{total} приложений Synced/Healthy",
        )
    else:
        rep.add("argo", "Argo CD", SKIP, "namespace argocd недоступен")

    lh, err = k.json("get", "nodes.longhorn.io", "-n", "longhorn-system")
    if lh is not None:
        not_ready = []
        for n in lh.get("items", []):
            conds = {c["type"]: c["status"] for c in n.get("status", {}).get("conditions", [])}
            if conds.get("Ready") != "True":
                not_ready.append(n["metadata"]["name"])
        vols, _ = k.json("get", "volumes.longhorn.io", "-n", "longhorn-system")
        nvol = len(vols.get("items", [])) if vols else 0
        rep.add(
            "longhorn",
            "Longhorn",
            FAIL if not_ready else OK,
            (f"NotReady: {', '.join(not_ready)}" if not_ready else f"все ноды Ready, томов {nvol}"),
        )
    else:
        rep.add("longhorn", "Longhorn", SKIP, "CRD nodes.longhorn.io недоступен")

    dep, err = k.json("get", "deploy", "higress-gateway", "-n", "higress-system")
    if dep:
        want = dep.get("spec", {}).get("replicas", 0)
        ready = dep.get("status", {}).get("readyReplicas", 0)
        pods, _ = k.json("get", "pods", "-n", "higress-system", "-l", "app=higress-gateway")
        names = [p["spec"].get("nodeName") for p in (pods or {}).get("items", [])]
        on_nodes = sorted({n for n in names if n})
        unplaced = sum(1 for n in names if not n)
        spread_ok = unplaced == 0
        rep.add(
            "higress",
            "Ingress (Higress gateway)",
            OK if ready >= want and want > 0 and spread_ok else FAIL,
            f"готово {ready}/{want}, ноды: {', '.join(on_nodes) or '—'}"
            + (f", без ноды (Pending) {unplaced}" if unplaced else ""),
        )
    else:
        rep.add("higress", "Ingress (Higress gateway)", SKIP, "namespace higress-system недоступен")


def check_ssh(nodes: list[dict], ssh_targets: dict[str, str], rep: Report) -> None:
    if not ssh_targets:
        rep.add(
            "ssh",
            "Живой замер нод",
            SKIP,
            "SSH-цели не заданы: --ssh user@host, env K8S_HEALTH_SSH, ansible/hosts.cluster.yml "
            "(логины из env K8S0X_USER) или inventory.local.md",
        )
        return
    rows = []
    problems = []
    for node in nodes or [{"name": ip, "ip": ip} for ip in ssh_targets]:
        ip = node["ip"]
        user = ssh_targets.get(ip)
        if not user:
            rows.append({"node": node["name"], "ip": ip, "error": "нет SSH-логина в инвентаре"})
            continue
        rc, out, _ = ssh_exec(user, ip, NODE_PROBE_SCRIPT)
        if rc != 0:
            problems.append(f"{node['name']}: SSH недоступен")
            rows.append({"node": node["name"], "ip": ip, "error": "ssh failed"})
            continue
        kv = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
        row = {"node": node["name"], "ip": ip}
        for key in ("HOSTNAME", "UPTIME_S", "LOAD", "NPROC", "MEM_TOTAL", "MEM_AVAIL", "DISK_USED", "CLOUDFLARED", "VIP", "BOOTS"):
            row[key.lower()] = kv.get(key, "")
        if row.get("uptime_s"):
            try:
                up = dt.datetime.strptime(row["uptime_s"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
                row["boot_msk"] = msk(up)
            except ValueError:
                row["boot_msk"] = row["uptime_s"]
        try:
            row["mem_avail_pct"] = round(int(row["mem_avail"]) * 100 / int(row["mem_total"]))
        except (KeyError, ValueError, ZeroDivisionError):
            row["mem_avail_pct"] = None
        rows.append(row)
        if row.get("mem_avail_pct") is not None and (row["mem_avail_pct"] or 100) < 10:
            problems.append(f"{row['node']}: свободной RAM {row['mem_avail_pct']}%")
        # Зависший kernel-thread / CPU-контеншн при простое: load1 против числа ядер.
        try:
            load1 = float(str(row.get("load", "")).split()[0])
            nproc = int(row.get("nproc") or 0)
            if nproc and load1 > nproc * 0.75:
                problems.append(f"{row['node']}: load {load1} при {nproc} ядрах")
        except (ValueError, IndexError):
            pass

    rep.add(
        "ssh",
        "Живой замер нод",
        WARN if problems else OK,
        "; ".join(problems) if problems else f"{len(rows)} нод опрошено по SSH",
        data=rows,
    )


def check_origin(rep: Report, timeout: int) -> None:
    """Origin в LAN: сам ingress-VIP и его сертификат. Внешний путь — scripts/env_health.py."""

    rc, out, _ = run(
        ["curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout),
         "--resolve", f"{PUBLIC_HOST}:443:{INGRESS_VIP}", f"https://{PUBLIC_HOST}/"],
        timeout=timeout + 4,
    )
    lan = out.strip() if rc == 0 else "000"
    rep.add(
        "ext",
        f"Внутренний origin ({INGRESS_VIP})",
        OK if lan == "200" else FAIL,
        f"https с SNI {PUBLIC_HOST} => {lan}",
    )

    rc, out, _ = run(
        ["bash", "-c",
         f"echo | openssl s_client -connect {INGRESS_VIP}:443 -servername {PUBLIC_HOST} 2>/dev/null | "
         "openssl x509 -noout -issuer -enddate"],
        timeout=timeout + 4,
    )
    if rc == 0 and out.strip():
        issuer = re.search(r"issuer=.*CN\s*=\s*([^,\n]+)", out)
        end = re.search(r"notAfter=(.+)", out)
        days = None
        if end:
            try:
                exp = dt.datetime.strptime(end.group(1).strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
                days = (exp - dt.datetime.now(dt.timezone.utc)).days
            except ValueError:
                pass
        st = OK if (days is None or days > 21) else WARN
        rep.add(
            "ext",
            "Сертификат origin",
            st,
            f"issuer={issuer.group(1).strip() if issuer else '?'}, осталось {days} дн." if days is not None
            else f"issuer={issuer.group(1).strip() if issuer else '?'}",
        )
    else:
        rep.add("ext", "Сертификат origin", SKIP, "не удалось прочитать сертификат")


# ---------------------------------------------------------------- вывод


def color_enabled(args) -> bool:
    """Цвет только для человека в TTY; --no-color / NO_COLOR / --json его выключают."""
    if args.no_color or args.json_out or os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def render(rep: Report, brief: bool, json_out: bool, color: bool = False) -> None:
    """Сводка (и полный отчёт, если строки не печатались потоком)."""
    if json_out:
        print(json.dumps(
            {"worst": rep.worst(), "counts": rep.counts(), "checks": rep.sections},
            ensure_ascii=False, indent=2,
        ))
        return

    if not rep.stream:
        print(f"demo-ai-lab · проверка кластера · {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}")
        current = None
        for s in rep.sections:
            if brief and s["status"] == OK:
                continue
            if s["section"] != current:
                print(f"\n{SECTION_TITLES.get(s['section'], s['section'])}")
                current = s["section"]
            print(format_line(s, color))
            if s["section"] == "ssh" and s.get("data") and not brief:
                for row in format_node_rows(s):
                    print(row)

    c = rep.counts()
    worst = rep.worst()
    summary = (f"ИТОГО: {c[OK]} PASS · {c[WARN]} WARN · {c[FAIL]} FAIL · {c[SKIP]} SKIP "
               f"→ {'OK' if worst == OK else worst}")
    print("\n" + paint(summary, worst, color))
    if worst == FAIL:
        print("См. skill demo-ai-lab-stand → references/status-audit.md (особенно §10: восстановление после power-cycle).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Быстрая проверка здоровья k8s-кластера demo-ai-lab")
    ap.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", "~/.kube/demo-ai-lab.conf"))
    ap.add_argument("--context", default=os.environ.get("K8S_HEALTH_CONTEXT", "demo-ai-lab"))
    ap.add_argument("--ssh", action="append", default=[], metavar="user@host", help="SSH-цель (повторяемо)")
    ap.add_argument("--no-ssh", action="store_true", help="не опрашивать ноды по SSH")
    ap.add_argument("--no-origin", "--no-external", dest="no_origin", action="store_true",
                    help="не проверять origin в LAN (алиас: --no-external)")
    ap.add_argument("--timeout", type=int, default=25, help="таймаут kubectl, с (по умолчанию 25)")
    ap.add_argument("--brief", action="store_true", help="показывать только WARN/FAIL")
    ap.add_argument("--json", action="store_true", dest="json_out", help="машинный вывод")
    ap.add_argument("--no-color", action="store_true", help="без ANSI-цвета (по умолчанию — только в TTY)")
    args = ap.parse_args()

    if run(["kubectl", "version", "--client=true"], timeout=10)[0] == 127:
        print("kubectl не найден в PATH", file=sys.stderr)
        return 1

    kube = Kube(args.kubeconfig, args.context, timeout=args.timeout)
    color = color_enabled(args)
    stream = not args.json_out
    if stream:
        print(f"demo-ai-lab · проверка кластера · {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}",
              flush=True)
    rep = Report(stream=stream, color=color, brief=args.brief)

    ssh_targets, ssh_source = ({}, "") if args.no_ssh else resolve_ssh_targets(args.ssh)
    rep.phase("доступ к API и VIP")
    api_ok = check_api(kube, ssh_targets, rep)
    nodes = []
    if api_ok:
        rep.phase("ноды и pressure")
        nodes = check_nodes(kube, rep)
        if nodes and ssh_targets:
            # отбрасываем цели, которых нет в кластере (например, роутер из inventory)
            known = {n["ip"] for n in nodes}
            ssh_targets = {ip: u for ip, u in ssh_targets.items() if ip in known}
        rep.phase("поды: health-gate и распределение")
        check_pods(kube, rep)
        rep.phase("кворум etcd")
        check_etcd(kube, rep)
        rep.phase("control-plane и kube-vip")
        check_control_plane(kube, rep)
        rep.phase("VIP и лизы")
        check_vips(kube, nodes, ssh_targets, rep)
        rep.phase("Argo CD / Longhorn / Higress")
        check_workloads(kube, rep)
    if not args.no_ssh:
        if ssh_targets:
            rep.phase(f"живой замер нод по SSH ({len(ssh_targets)} шт)")
            check_ssh(nodes, ssh_targets, rep)
        else:
            rep.add(
                "ssh",
                "Живой замер нод",
                SKIP,
                "инвентарь SSH не найден: --ssh user@host, env K8S_HEALTH_SSH, "
                "ansible/hosts.cluster.yml (+env K8S0X_USER) или inventory.local.md",
            )
    if not args.no_origin:
        rep.phase("origin в LAN (.230) и его сертификат")
        check_origin(rep, min(10, args.timeout))

    render(rep, args.brief, args.json_out, color=color)
    return 0 if rep.worst() == OK else (1 if rep.worst() == FAIL else 2)


if __name__ == "__main__":
    sys.exit(main())
