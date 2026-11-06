#!/usr/bin/env python3
"""env_health.py — проверка «обвязки» стенда demo-ai-lab (всё, что вне кластера).

Схема на 2026-11-05: Cloudflare из внешнего пути выведен (ADR-0004, ревизия 2026-11-05).
Внешний вход — напрямую адрес внешней VM, haproxy `mode tcp` с SNI-роутингом в два SSH-hop'а
до ingress-VIP; DNS-зона живёт на reg.ru. Скрипт проверяет четыре слоя:

  1) DNS — делегирование в реестре .ru, ответы публичных резолверов, TXT верификации
     MCP-реестра, отсутствие AAAA и TTL (сутки на записи = сутки на любую правку);
  2) внешняя VM — SSH-доступ, ресурсы, haproxy на :443 (свободен ли порт от traefik/kuma),
     аптайм бэкендов hop'ов, туннельный вход 127.0.0.1:19443 как резерв, а также вход :80 —
     он нужен только для ACME HTTP-01: валидатор Let's Encrypt идёт на :80, получает 301 на https
     и по редиректу попадает на тот же 443-путь (серты `hm.` выпускаются именно так);
  3) публичный путь — ответы сервисов через VM:443 с проверкой цепочки сертификата, ACME-редирект
     :80 → 301 (от него зависит продление сертов) и `hm.` (/api/status панели агента),
     негативные проверки (чужой SNI, заход по IP), SNI-денилст служебных UI и служебные пути
     `auth.` (не-зелёный здесь = периметр не завершён; подробности и план — локальный отчёт ИБ
     в `security/*.local.md`, вне репозитория);
  4) снаружи — check-host.net, чтобы отличить «стенд закрыт security group» от «путь сломан».

Кластер проверяет scripts/k8s_health.py — здесь только обвязка.

Зависимости: только стандартная библиотека Python 3.9+; из PATH — ssh, curl, dig.

Примеры:
    python3 scripts/env_health.py                    # полный прогон
    python3 scripts/env_health.py --brief            # только «не-зелёное»
    python3 scripts/env_health.py --json             # машинный вывод
    python3 scripts/env_health.py --no-vm            # только DNS и публичный путь
    python3 scripts/env_health.py --expect-open-world # мир должен видеть стенд (после открытия SG)

Коды выхода: 0 — всё зелёное, 2 — есть WARN, 1 — есть FAIL.

Приватность: в скрипте нет логинов, адресов VM, MAC и токенов. Цель SSH берётся из
(1) --vm user@host, (2) env ENV_HEALTH_VM, (3) inventory.local.md (gitignored). Адрес входа
для проверок не хардкодится — он берётся из публичного DNS (если DNS соврал, это и есть
предмет проверки). Cloudflare API больше не вызывается: туннель выведен из пути.
"""
from __future__ import annotations

import argparse
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
    "dns": "DNS (зона на reg.ru)",
    "vm": "Внешняя VM — точка входа",
    "path": "Публичный путь через VM",
    "world": "Снаружи (check-host.net)",
}

# Публичные константы стенда (см. architecture/specs/external-access-spec.md, ADR-0004).
PUBLIC_HOST = "demo-ai-lab.ru"
ECHO_HOST = "echo.demo-ai-lab.ru"
HM_HOST = "hm.demo-ai-lab.ru"      # Hermes Agent: /api/status отдаётся без входа → удобная сквозная проба
PUBLIC_PORT = 443
HAPROXY_PORT = 19443          # вход туннеля на loopback VM (резерв, не основной путь)
ACME_PORT = 80                # только для HTTP-01: haproxy редиректит на https
ACME_PATH = "/.well-known/acme-challenge/env-health-probe"
HOP_PORTS = (18443, 18444)
SERVICE_UI_HOSTS = ("argo", "hgc", "lng", "mon")   # снаружи должны рваться (SNI-денилст haproxy)
PARENT_NS_RU = "a.dns.ripn.net"
DNS_RESOLVERS = ("1.1.1.1", "8.8.8.8", "9.9.9.9", "77.88.8.8", "62.76.76.62")
MCP_TXT_MARK = "v=MCPv1"
TTL_WARN_ABOVE = 600


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


def dig(args: list[str], timeout: int = 12) -> tuple[int, str]:
    rc, out, err = run(["dig", "+time=3", "+tries=1", *args], timeout=timeout)
    return rc, out if rc == 0 else (err or out)


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


# ---------------------------------------------------------------- 1. DNS


def check_dns(rep: Report) -> str:
    """Проверяет зону и возвращает адрес входа, который видят публичные резолверы ('' если нет)."""
    rc, out = dig(["+norecurse", "+noall", "+authority", "NS", PUBLIC_HOST, f"@{PARENT_NS_RU}"])
    parent = re.findall(r"IN\s+NS\s+(\S+?)\.?\s*$", out, re.M)
    parent_ttl = ""
    m = re.search(r"^\S+\.\s+(\d+)\s+IN\s+NS", out, re.M)
    if m:
        parent_ttl = m.group(1)
    if parent:
        rep.add("dns", "Делегирование в реестре .ru", OK,
                f"{', '.join(sorted(parent))}" + (f", TTL {parent_ttl} (цена смены NS)" if parent_ttl else ""))
    else:
        rep.add("dns", "Делегирование в реестре .ru", WARN,
                f"реестр не отдал NS ({PARENT_NS_RU}): {out.strip().splitlines()[-1] if out.strip() else 'пусто'}")

    # Резолверы публичные и иногда молчат: `dig` тогда отдаёт текст ошибки
    # («connection timed out…»), который без валидации превращался в «NS» и давал
    # ложный FAIL. Берём первый резолвер из DNS_RESOLVERS, ответивший именами.
    zone_ns, ns_err, ns_resolver = [], "", ""
    for r in DNS_RESOLVERS:
        rc, out = dig(["+short", "NS", PUBLIC_HOST, f"@{r}"])
        toks = [t.rstrip(".").lower() for t in out.split()
                if re.fullmatch(r"(?:[a-z0-9_-]+\.)+[a-z0-9_-]+\.?", t.lower())]
        if toks:
            zone_ns, ns_resolver = sorted(toks), r
            break
        ns_err = (out.strip().splitlines() or [f"rc={rc}"])[-1][:120]
    if not zone_ns:
        rep.add("dns", "NS зоны", WARN,
                f"публичные резолверы не ответили ({', '.join(DNS_RESOLVERS)}): {ns_err or 'пусто'}")
    elif parent and set(zone_ns) != set(x.rstrip(".").lower() for x in parent):
        rep.add("dns", "NS зоны", FAIL,
                f"зона отдаёт {', '.join(zone_ns)}, реестр — {', '.join(sorted(parent))}")
    else:
        rep.add("dns", "NS зоны", OK, f"{', '.join(zone_ns)} (через {ns_resolver})")

    answers: dict[str, tuple[str, str]] = {}
    missing = []
    for r in DNS_RESOLVERS:
        rc, out = dig(["+noall", "+answer", "+ttlid", "A", PUBLIC_HOST, f"@{r}"])
        row = next((ln for ln in out.splitlines() if "IN" in ln and "A" in ln), "")
        parts = row.split()
        if len(parts) >= 5:
            answers[r] = (parts[4], parts[1])
        else:
            missing.append(r)
    if not answers:
        rep.add("dns", f"A {PUBLIC_HOST}", FAIL, "ни один резолвер не ответил — проверить DNS и сеть")
        return ""
    ips = {ip for ip, _ in answers.values()}
    ttl_max = max(int(t) if t.isdigit() else 0 for _, t in answers.values())
    entry_ip = next(iter(ips)) if len(ips) == 1 else ""
    detail = ", ".join(f"{r}={ip}({t})" for r, (ip, t) in sorted(answers.items()))
    if len(ips) == 1:
        rep.add("dns", f"A {PUBLIC_HOST}", OK, f"{entry_ip} у всех {len(answers)} резолверов", rows=[detail])
    else:
        rep.add("dns", f"A {PUBLIC_HOST}", FAIL,
                f"резолверы расходятся ({len(ips)} разных ответов)", rows=[detail])
    if missing:
        rep.add("dns", "Резолверы без ответа", WARN,
                f"{', '.join(missing)} — молчат (rate-limit/фильтр), на вердикт не влияет")

    rc, out = dig(["+short", "TXT", PUBLIC_HOST, "@1.1.1.1"])
    rep.add("dns", "TXT верификации MCP-реестра",
            OK if MCP_TXT_MARK in out else FAIL,
            "v=MCPv1 на месте" if MCP_TXT_MARK in out
            else "TXT `v=MCPv1; k=ed25519; p=…` отсутствует — реестр потеряет домен")

    rc, out = dig(["+short", "AAAA", PUBLIC_HOST, "@1.1.1.1"])
    rep.add("dns", "AAAA", OK if not out.strip() else WARN,
            "нет (v6-only клиенты стенд не видят — у входа нет IPv6)" if not out.strip()
            else f"есть {out.split()[0]}, но у входа нет IPv6 — расхождение")

    if ttl_max:
        rep.add("dns", "TTL записей", OK if ttl_max <= TTL_WARN_ABOVE else WARN,
                f"{ttl_max} с" + ("" if ttl_max <= TTL_WARN_ABOVE
                                 else " — сутки на любую правку/откат, держать 300–600"))
    return entry_ip


# ---------------------------------------------------------------- 2. внешняя VM

VM_SCRIPT = r"""
echo "HOST=$(hostname -s 2>/dev/null)"
echo "UPTIME=$(uptime -s 2>/dev/null)"
echo "LOAD=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
echo "MEM=$(free -m 2>/dev/null | awk '/Mem:/ {print $3"/"$2}')"
echo "DISK=$(df -P / 2>/dev/null | awk 'NR==2 {print $5}')"
echo "HPACT=$(systemctl is-active haproxy 2>/dev/null)"
echo "CFACT=$(systemctl is-active cloudflared 2>/dev/null)"
echo "LISTEN=$(ss -tln 2>/dev/null | awk '{print $4}' | grep -oE '[0-9]+$' | grep -E '^(80|443|19443|18443|18444)$' | sort -u | paste -sd, -)"
echo "OWNER443=$(sudo -n ss -tlnp 2>/dev/null | grep ':443 ' | grep -oE 'users:\(\("[^\"]+' | head -1 | sed 's/.*"//')"
echo "OWNER80=$(sudo -n ss -tlnp 2>/dev/null | grep ':80 ' | grep -oE 'users:\(\("[^\"]+' | head -1 | sed 's/.*"//')"
echo "ACME=$(curl -s -o /dev/null -w '%{http_code}|%{redirect_url}' --max-time 6 -H 'Host: demo-ai-lab.ru' http://127.0.0.1/.well-known/acme-challenge/env-health-probe 2>/dev/null)"
echo "DOCKER=$(sudo -n docker ps --format '{{.Names}}' 2>/dev/null | paste -sd, -)"
echo "HAPSTAT=$(sudo -n python3 - <<'PY' 2>/dev/null
import socket
try:
    s = socket.socket(socket.AF_UNIX); s.connect('/run/haproxy/admin.sock'); s.sendall(b'show stat\n')
    d = b''
    while True:
        c = s.recv(65536)
        if not c: break
        d += c
except Exception:
    raise SystemExit
out = []
for line in d.decode().splitlines():
    f = line.split(',')
    if len(f) > 17 and f[0] == 'demo_origin' and f[1] in ('k8s02', 'k8s03'):
        out.append(f[1] + ',' + f[17])
print(' '.join(out))
PY
)"
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
    """Возвращает IP внешней VM или ''."""
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

    hp_act = d.get("HPACT", "?")
    rep.add("vm", "haproxy", OK if hp_act == "active" else FAIL, f"systemctl: {hp_act}")

    listen = {int(p) for p in (d.get("LISTEN") or "").split(",") if p.strip().isdigit()}
    owner = (d.get("OWNER443") or "").strip()
    if PUBLIC_PORT in listen:
        rep.add("vm", f"Порт {PUBLIC_PORT} (публичный вход)", OK if owner == "haproxy" else WARN,
                f"слушает {owner or 'неизвестный процесс'}" +
                ("" if owner == "haproxy" else " — ожидался haproxy (traefik/kuma выведены)"))
    else:
        rep.add("vm", f"Порт {PUBLIC_PORT} (публичный вход)", FAIL, "никто не слушает — внешний вход мёртв")

    # Порт 80 — только для ACME HTTP-01: без него Let's Encrypt не продлит серты
    # (`hm-demo-tls` выпускается именно так), а остальные проверки останутся зелёными.
    owner80 = (d.get("OWNER80") or "").strip()
    if ACME_PORT in listen:
        rep.add("vm", f"Порт {ACME_PORT} (ACME HTTP-01)", OK if owner80 == "haproxy" else WARN,
                f"слушает {owner80 or 'неизвестный процесс'}" +
                ("" if owner80 == "haproxy" else " — ожидался haproxy (frontend public_http)"))
    else:
        rep.add("vm", f"Порт {ACME_PORT} (ACME HTTP-01)", FAIL,
                "никто не слушает — продление сертификатов по HTTP-01 не пройдёт")

    acme = d.get("ACME", "")
    acme_code, _, acme_loc = acme.partition("|")
    ok_rdr = acme_code == "301" and acme_loc.startswith("https://") and ACME_PATH in acme_loc
    rep.add("vm", f"Редирект {ACME_PORT} → https (ACME)", OK if ok_rdr else FAIL,
            f"{acme_code or '000'} → {acme_loc or '—'}" +
            ("" if ok_rdr else f" — ожидался 301 на https с сохранением пути {ACME_PATH}"))

    hop_listen = {p for p in HOP_PORTS if p in listen}
    st = OK if len(hop_listen) == len(HOP_PORTS) else (WARN if hop_listen else FAIL)
    rep.add("vm", "Слушатели hop'ов", st,
            f"{sorted(hop_listen)} из {list(HOP_PORTS)}" +
            ("" if st == OK else " — SSH -R с k8s-02/03 не поднят"))
    rep.add("vm", f"Туннельный вход {HAPROXY_PORT} (резерв)", OK if HAPROXY_PORT in listen else WARN,
            "на месте" if HAPROXY_PORT in listen else "нет — откат на Cloudflare-туннель недоступен")

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

    origin = d.get("ORIGIN", "000")
    rep.add("vm", "Origin через hop", OK if origin == "200" else FAIL,
            f"https://{PUBLIC_HOST} через 127.0.0.1:{HAPROXY_PORT} → {origin}")

    docker = [x for x in (d.get("DOCKER") or "").split(",") if x]
    leftovers = [x for x in docker if x in ("traefik", "uptime-kuma")]
    rep.add("vm", "Посторонние контейнеры на VM", OK if not leftovers else WARN,
            "нет" if not leftovers else f"запущены: {', '.join(leftovers)} — делят :443 с haproxy")
    return vm_ip


# ---------------------------------------------------------------- 3. публичный путь


def curl_probe(host: str, entry_ip: str, path: str = "/", timeout: int = 10) -> tuple[str, str, str]:
    """(код, ssl_verify_result, remote_ip). '000' — соединение не установилось/сброшено."""
    rc, out, _ = run([
        "curl", "-s", "-o", "/dev/null", "--max-time", str(timeout),
        "--resolve", f"{host}:{PUBLIC_PORT}:{entry_ip}",
        "-w", "%{http_code}|%{ssl_verify_result}|%{remote_ip}",
        f"https://{host}:{PUBLIC_PORT}{path}",
    ], timeout=timeout + 4)
    if rc != 0 and not out.strip():
        return "000", "", ""
    code, _, rest = (out.strip() + "||").partition("|")
    verify, _, remote = rest.partition("|")
    return code or "000", verify, remote


def curl_probe_http(host: str, entry_ip: str, path: str, timeout: int = 10) -> tuple[str, str]:
    """(код, Location) для запроса по HTTP на ACME_PORT. '000' — соединение не установилось."""
    rc, out, _ = run([
        "curl", "-s", "-o", "/dev/null", "--max-time", str(timeout),
        "--resolve", f"{host}:{ACME_PORT}:{entry_ip}",
        "-w", "%{http_code}|%{redirect_url}",
        f"http://{host}:{ACME_PORT}{path}",
    ], timeout=timeout + 4)
    code, _, loc = (out.strip() + "|").partition("|")
    return (code or "000"), loc.rstrip("|")


def check_path(rep: Report, entry_ip: str, samples: int, timeout: int) -> None:
    if not entry_ip:
        rep.add("path", "Публичный путь", SKIP, "адрес входа не определён (DNS выше не дал единого ответа)")
        return

    codes = []
    verify = ""
    for _ in range(max(1, samples)):
        code, ver, _ = curl_probe(PUBLIC_HOST, entry_ip, timeout=timeout)
        codes.append(code)
        verify = verify or ver
    good = sum(1 for c in codes if c == "200")
    tally = ", ".join(f"{c}×{codes.count(c)}" for c in sorted(set(codes)))
    rep.add("path", f"Сквозной путь https://{PUBLIC_HOST}", OK if good == len(codes) else (WARN if good else FAIL),
            f"{good}/{len(codes)} ответов 200 ({tally}) через {entry_ip}:{PUBLIC_PORT}")
    rep.add("path", "Цепочка сертификата", OK if verify == "0" else FAIL,
            "публичный LE, проверка пройдена" if verify == "0" else f"ssl_verify_result={verify or '?'}")

    acme_code, acme_loc = curl_probe_http(PUBLIC_HOST, entry_ip, ACME_PATH, timeout=timeout)
    ok_rdr = acme_code == "301" and acme_loc.startswith("https://") and ACME_PATH in acme_loc
    rep.add("path", f"ACME HTTP-01 ({ACME_PORT} → 301)", OK if ok_rdr else FAIL,
            f"{acme_code} → {acme_loc or '—'}" +
            ("" if ok_rdr else " — валидатор LE не сможет дойти до токена, серты перестанут продлеваться"))

    # Hermes Agent (агентский рантайм): /api/status публичен, поэтому проверяется как сервис,
    # а не как «страница входа». Заодно ловим рассинхрон серта: свой LE-серт живёт в Ingress'е.
    hm_code, hm_verify, _ = curl_probe(HM_HOST, entry_ip, path="/api/status", timeout=timeout)
    hm_ok = hm_code == "200" and hm_verify == "0"
    rep.add("path", f"Сервис {HM_HOST} (/api/status)", OK if hm_ok else FAIL,
            f"→ {hm_code}, цепочка {'ok' if hm_verify == '0' else (hm_verify or '?')}" +
            ("" if hm_ok else " — панель агента не отвечает через внешний путь"))

    echo, _, _ = curl_probe(ECHO_HOST, entry_ip, timeout=timeout)
    rep.add("path", f"Smoke-хост {ECHO_HOST}", OK if echo == "200" else WARN,
            f"→ {echo}" + ("" if echo == "200" else " (постоянный тестовый маршрут)"))

    code, _, _ = curl_probe(PUBLIC_HOST, entry_ip, timeout=timeout)
    rc, out, _ = run(["curl", "-s", "-o", "/dev/null", "--max-time", str(timeout), "-k", f"https://{entry_ip}/"],
                     timeout=timeout + 4)
    rep.add("path", "Заход по IP без SNI", OK if rc != 0 else WARN,
            "рвётся (deny_all)" if rc != 0 else "отвечает — SNI-роутинг пропускает запросы без имени")

    bad = []
    for h in SERVICE_UI_HOSTS:
        code, _, _ = curl_probe(f"{h}.{PUBLIC_HOST}", entry_ip, timeout=timeout)
        if code != "000":
            bad.append(f"{h}={code}")
    rep.add("path", "Служебные UI снаружи", OK if not bad else FAIL,
            "все рвутся SNI-денилстом (argo/hgc/lng/mon)" if not bad else f"доступны: {', '.join(bad)}")

    admin = []
    for path in ("/admin/", "/realms/master/.well-known/openid-configuration"):
        code, _, _ = curl_probe(f"auth.{PUBLIC_HOST}", entry_ip, path=path, timeout=timeout)
        admin.append(f"{path}={code}")
    open_admin = [x for x in admin if x.rsplit("=", 1)[-1] not in ("000", "403")]
    rep.add("path", "Служебные пути auth. снаружи", OK if not open_admin else FAIL,
            "закрыты на входе" if not open_admin else
            f"не закрыты ({', '.join(open_admin)}) — периметр не завершён, "
            f"внешний вход в мир не открывать (детали: локальный отчёт ИБ, security/*.local.md)",
            rows=[", ".join(admin)])


# ---------------------------------------------------------------- 4. снаружи


def check_world(rep: Report, expect_open: bool) -> None:
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) env-health/2.0"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    points: list[tuple[str, str]] = []
    try:
        url = (f"https://check-host.net/check-http?host={urllib.parse.quote(f'https://{PUBLIC_HOST}/', safe='')}"
               f"&max_nodes=5")
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": ua})
        with opener.open(req, timeout=15) as r:
            start = json.loads(r.read())
        rid, nodes = start.get("request_id"), start.get("nodes") or {}
        if not rid:
            rep.add("world", "Внешние точки", SKIP, "check-host не выдал request_id")
            return
        res: dict = {}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(6)
            req = urllib.request.Request(f"https://check-host.net/check-result/{rid}",
                                         headers={"Accept": "application/json", "Referer": "https://check-host.net/",
                                                  "User-Agent": ua})
            with opener.open(req, timeout=15) as r:
                res = json.loads(r.read())
            if res and all(v is not None for v in res.values()):
                break
        for node, val in (res or {}).items():
            if not val:
                continue
            country = (nodes.get(node) or ["?"])[0]
            code = "?"
            item = val[0] if isinstance(val, list) and val else None
            if item is None:
                code = "нет ответа"
            elif isinstance(item, list) and len(item) >= 4:
                code = str(item[3]) if item[3] is not None else "нет ответа"
            elif isinstance(item, dict):
                code = str(item.get("status_code") or item.get("status") or "нет ответа")
            points.append((country, code))
    except Exception as e:  # noqa: BLE001
        rep.add("world", "Внешние точки", SKIP, f"check-host недоступен: {e}")
        return

    if not points:
        rep.add("world", "Внешние точки", SKIP, "check-host не отдал результат (лимит/недоступен)")
        return
    ok_pts = sum(1 for _, c in points if c == "200")
    if ok_pts == len(points):
        rep.add("world", "Внешние точки", OK, f"{ok_pts}/{len(points)} точек 200 — стенд виден из интернета")
    elif expect_open:
        rep.add("world", "Внешние точки", FAIL,
                f"{ok_pts}/{len(points)} точек 200 — мир должен видеть стенд, но не видит "
                f"(security group / haproxy)",
                rows=[f"{c:<12} {code}" for c, code in sorted(points)])
    else:
        rep.add("world", "Внешние точки", WARN,
                f"{ok_pts}/{len(points)} точек 200 — ожидаемо: security group держит 443 закрытым "
                f"до починки админ-путей (см. ADR-0004, п. 7)",
                rows=[f"{c:<12} {code}" for c, code in sorted(points)])


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
        print("Разбор — skill demo-ai-lab-stand → references/external-path-regru.md; "
              "спека — architecture/specs/external-access-spec.md, решение — ADR-0004 (ред. 2026-11-05).")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Проверка обвязки стенда demo-ai-lab: DNS (reg.ru), внешняя VM, публичный путь через VM")
    ap.add_argument("--vm", metavar="user@host",
                    help="SSH-цель внешней VM (по умолчанию env ENV_HEALTH_VM / inventory.local.md)")
    ap.add_argument("--no-dns", action="store_true", help="не проверять DNS")
    ap.add_argument("--no-vm", action="store_true", help="не проверять внешнюю VM")
    ap.add_argument("--no-path", action="store_true", help="не проверять публичный путь")
    ap.add_argument("--no-check-host", action="store_true", help="не подтверждать доступность извне")
    ap.add_argument("--expect-open-world", action="store_true",
                    help="мир должен видеть стенд (после открытия security group): провал внешних точек = FAIL")
    ap.add_argument("--samples", type=int, default=3, help="число запросов к публичному входу (по умолчанию 3)")
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

    entry_ip = ""
    if not args.no_dns:
        rep.phase("DNS: делегирование, ответы резолверов, TXT, TTL")
        entry_ip = check_dns(rep)

    if not args.no_vm:
        rep.phase("внешняя VM: haproxy на :443, hop-и, туннельный резерв")
        check_vm(rep, resolve_vm_target(args.vm), max(20, args.timeout))

    if not args.no_path:
        rep.phase(f"публичный путь через VM ({args.samples} запросов)")
        check_path(rep, entry_ip, args.samples, min(12, args.timeout))

    if not args.no_check_host:
        rep.phase("внешние точки: check-host.net")
        check_world(rep, args.expect_open_world)

    render(rep, args.brief, args.json_out, color)
    return 0 if rep.worst() == OK else (1 if rep.worst() == FAIL else 2)


if __name__ == "__main__":
    sys.exit(main())
