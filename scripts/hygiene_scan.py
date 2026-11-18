#!/usr/bin/env python3
"""Гигиена публикации: машинный гейт для репозитория (правила — HYGIENE.md).

Что проверяет (по классам, см. HYGIENE.md §1):
  СЕКРЕТЫ      приватные ключи, токены провайдеров, присвоение значения паролю/ключу
  MAC          MAC-адреса устройств (и OUI-привязки «этот MAC = этот хост»)
  EXT_IP       внешние IPv4 (разрешены только LAN стенда, loopback и TEST-NET)
  GEO          координаты и геопривязки (широта/долгота, GPS, адрес площадки)
  PDN          телефоны, служебные документы, чужие e-mail (кроме автора репо)
  ИБ           CVE, «уязвим», PoC, пентест, noPassword, «обход allowlist»(REVIEW)
  VPN/OБХОД    VLESS/Reality/Xray/Happ, «обход блокировок», VPN-истории  (класс REVIEW)
  ФАЙЛЫ        приватный файл (*.local.md, *.local.pem, .env*) попал в git

Режимы:
  ./scripts/hygiene_scan.py              # гейт перед коммитом: только ДОБАВЛЕННЫЕ строки staged-диффа
  ./scripts/hygiene_scan.py --tree       # всё дерево (tracked + untracked), с теми же классами
  ./scripts/hygiene_scan.py --history    # история: добавленные строки всех коммитов (медленно)

Коды возврата: 0 — чисто, 1 — есть STOP-хиты, 2 — сканер не отработал (usage/git) — вердикт недействителен.

Приватные файлы (`*.local.md`, `.env*`) в режиме --tree не сканируются на MAC/ПДн — им это можно;
проверяется только то, что они не попали в git.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

# Сам документ правил и сам сканер содержат шаблоны проверок — на них не срабатываем.
EXEMPT_PATHS = {"HYGIENE.md", "scripts/hygiene_scan.py"}

SKIP_DIRS = {".git", ".render-cache", "node_modules", "__pycache__", "old", "beellama-rtx5060", ".hermes"}
PRIVATE_FILE = re.compile(r"(\.local\.md|\.local\.pem|(^|/)\.env)")
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".zst",
              ".tar", ".deb", ".rpm", ".woff", ".woff2", ".ttf", ".mp4", ".mov", ".excalidraw.png"}

ALLOWED_NETS = [
    ipaddress.ip_network(n) for n in (
        "10.0.0.0/8", "127.0.0.0/8", "192.168.10.0/24", "172.16.0.0/12",
        "0.0.0.0/32", "255.255.255.255/32",
        "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",  # TEST-NET для примеров
        # публичные резолверы и anycast-CDN: адреса самой инфраструктуры, а не площадки
        "1.1.1.1/32", "8.8.8.8/32", "9.9.9.9/32", "77.88.8.8/32", "62.76.76.62/32",
        "172.64.0.0/13", "104.16.0.0/13", "162.158.0.0/15", "188.114.96.0/20", "23.215.0.0/16",
        # мультикаст, link-local, CGNAT — служебные диапазоны, не адрес площадки
        "224.0.0.0/4", "239.0.0.0/8", "169.254.0.0/16", "100.64.0.0/10",
        "91.105.192.0/23", "91.108.0.0/16", "95.161.76.100/32", "149.154.160.0/20", "185.76.151.0/24",
        "1.2.3.4/32",  # плейсхолдер в примерах команд
    )
]
# e-mail автора репозитория — опубликованы в его профиле/на его сайте, разрешены осознанно
ALLOWED_EMAILS = {
    "michael@sokolov.im", "maikl.sokolov@gmail.com", "sokolovma@gnivc.ru",
    "noreply@github.com", "users.noreply.github.com", "actions@github.com",
}

STOP_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("СЕКРЕТЫ/ключ", re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP|PRIVATE)")),
    ("СЕКРЕТЫ/токен", re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                                 r"|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,})")),
    ("СЕКРЕТЫ/присвоение", re.compile(r"(?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[\"']?"
                                      r"(?!(?:[A-Z_]+\b|\$|\{\{))[A-Za-z0-9_./+-]{12,}", re.IGNORECASE)),
    ("MAC", re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b")),
    ("GEO/координаты", re.compile(r"\b-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}\b")),

    ("PDN/СНИЛС", re.compile(r"\b\d{3}-\d{3}-\d{3}[ -]\d{2}\b")),

]

REVIEW_RULES: list[tuple[str, re.Pattern[str]]] = [
    # ИБ: описание дыры/PoC/«что открыто» — только security/*.local.md (HYGIENE.md §1)
    ("ИБ/маркер", re.compile(r"CVE-\d{4}|(?i:уязвим|эксплуатир|exploit|пентест|pentest|noPassword)"
                            r"|\bPoC\b|обход\s+(?:allowlist|фильтр|правил)", re.IGNORECASE)),
    ("GEO/термин", re.compile(r"(?i)(?:адрес площадки|координаты площадки|широта|долгота|"
                              r"geolocation|gps-метк|exif)")),
    ("PDN/телефон", re.compile(r"(?<!\d)(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)")),
    ("PDN/документ", re.compile(r"(?i)\b(?:паспорт\w*|снилс|инн|полис\s+омс)\b")),
    ("VPN/обход", re.compile(r"(?i)\b(?:vless|vmess|reality|xtls|xray|happ|xkeen|"
                             r"обход\w*\s+блокиров\w*|bypass(?:ing)?\s+(?:block|censor))\b")),
    ("VPN/слово", re.compile(r"(?i)\b(?:vpn|прокси-обход)\b")),
    # логин «юзер@хост»: хост адресом или внутренним именем — это идентификатор доступа
    ("ЛОГИН/юзер@хост", re.compile(r"\b[a-zA-Z][\w.-]{1,30}@(?:(?:\d{1,3}\.){3}\d{1,3}\b|"
                                  r"[\w-]+\.(?:adp\.local|local|internal|lan|svc)\b)")),
    ("PDN/e-mail", re.compile(r"(?i)\b[\w.+-]+@(?:gmail\.com|yandex\.[a-z]+|ya\.ru|mail\.ru|"
                             r"bk\.ru|inbox\.ru|list\.ru|icloud\.com|outlook\.com|yahoo\.[a-z]+|"
                             r"proton(?:mail)?\.[a-z]+|hotmai\.?l?\.com)\b")),
]

IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def die(msg: str) -> None:
    print(f"ошибка: {msg}", file=sys.stderr)
    raise SystemExit(2)


def sh(*args: str) -> str:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode not in (0, 1):
        die(f"{' '.join(args)} → rc={r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def is_private_path(p: str) -> bool:
    return bool(PRIVATE_FILE.search(p))


def mask(line: str, secret: bool = False) -> str:
    """Строку обрезаем; значения секретов дополнительно маскируем — их в лог не печатаем."""
    s = line.strip()
    if len(s) > 100:
        s = s[:97] + "…"
    if secret:
        s = re.sub(r"([A-Za-z0-9+/=_-]{16,})", lambda m: m.group(1)[:4] + "…<скрыто>", s)
    return s


def check_line(path: str, lineno: int, line: str, stop: list, review: list) -> None:
    for name, rx in STOP_RULES:
        if name == "MAC" and is_private_path(path):
            continue
        m = rx.search(line)
        if m:
            stop.append(f"{path}:{lineno}  [{name}]  «{m.group(0)}»  {mask(line, secret=name.startswith('СЕКРЕТЫ'))}")
            return
    for name, rx in REVIEW_RULES:
        m = rx.search(line)
        if not m:
            continue
        if name == "PDN/e-mail":
            for em in rx.findall(line):
                if em.lower() in ALLOWED_EMAILS:
                    continue
                review.append(f"{path}:{lineno}  [{name}]  {mask(line)}")
                break
            continue
        review.append(f"{path}:{lineno}  [{name}]  {mask(line)}")
        return
    for tok in IPV4.findall(line):
        try:
            ip = ipaddress.ip_address(tok)
        except ValueError:
            continue
        if any(ip in n for n in ALLOWED_NETS):
            continue
        # «21.0.12.1» — версия JVM/пакета, а не адрес: .0. и однозначный последний октет
        o = tok.split(".")
        if o[1] == "0" and len(o[3]) == 1:
            continue
        stop.append(f"{path}:{lineno}  [EXT_IP]  «{tok}»  {mask(line)}")
        return


def scan_text(path: str, text: str, stop: list, review: list, only_added: bool = False) -> None:
    for i, line in enumerate(text.splitlines(), 1):
        if only_added and not line.startswith("+"):
            continue
        check_line(path, i, line[1:] if only_added else line, stop, review)


def scan_staged(stop: list, review: list) -> int:
    diff = sh("git", "diff", "--cached", "--unified=0")
    if not diff.strip():
        return 0
    files = 0
    cur = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            files += 1
            continue
        if cur and line.startswith("+") and not line.startswith("+++"):
            if cur in EXEMPT_PATHS:
                continue
            check_line(cur, 0, line[1:], stop, review)
    return files


def iter_tree() -> list[Path]:
    out = []
    for p in Path(".").rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file() or p.suffix.lower() in BINARY_EXT:
            continue
        out.append(p)
    return out


def scan_tree(stop: list, review: list) -> int:
    n = 0
    for p in iter_tree():
        rel = str(p)
        if rel in EXEMPT_PATHS or is_private_path(rel):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue  # бинарник: ключевые файлы презентаций, архивы, медиа
        text = raw.decode("utf-8", "replace")
        n += 1
        for i, line in enumerate(text.splitlines(), 1):
            check_line(rel, i, line, stop, review)
    return n


def scan_history(stop: list, review: list) -> int:
    log = sh("git", "log", "--all", "-p", "--unified=0", "--no-merges")
    cur = ""
    commits = 0
    for line in log.splitlines():
        if line.startswith("commit "):
            commits += 1
            continue
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            continue
        if cur and line.startswith("+") and not line.startswith("+++"):
            if cur in EXEMPT_PATHS:
                continue
            check_line(cur, 0, line[1:], stop, review)
    return commits


def check_private_files_tracked(stop: list) -> None:
    tracked = sh("git", "ls-files")
    for f in tracked.splitlines():
        if is_private_path(f):
            stop.append(f"{f}  [ФАЙЛЫ]  приватный файл в индексе git — убрать: git rm --cached {f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Гигиена публикации: гейт перед коммитом")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--tree", action="store_true", help="сканировать всё дерево, а не staged-дифф")
    g.add_argument("--history", action="store_true", help="сканировать историю коммитов (медленно)")
    a = ap.parse_args()

    if not Path(".git").exists():
        die("запускать из корня репозитория")
    stop: list[str] = []
    review: list[str] = []
    check_private_files_tracked(stop)

    if a.tree:
        n = scan_tree(stop, review)
        scope = f"дерево: {n} файлов"
    elif a.history:
        n = scan_history(stop, review)
        scope = f"история: {n} коммитов"
    else:
        n = scan_staged(stop, review)
        scope = f"staged: {n} файлов"
        if n == 0:
            print("staged-дифф пуст — проверять нечего (для полной проверки: --tree)")
            raise SystemExit(0)

    print(f"гигиена публикации · {scope}")
    if stop:
        print(f"\nSTOP — {len(stop)} хитов (коммитить нельзя):")
        for h in stop:
            print("  ", h)
    if review:
        print(f"\nREVIEW — {len(review)} хитов (решение человека: HYGIENE.md §1):")
        for h in review[:40]:
            print("  ", h)
        if len(review) > 40:
            print(f"   … ещё {len(review) - 40}")
    if not stop and not review:
        print("чисто: STOP 0 · REVIEW 0")
    elif not stop:
        print("\nSTOP 0 — блокирующих хитов нет (REVIEW разобрать глазами)")
    raise SystemExit(1 if stop else 0)


if __name__ == "__main__":
    main()
