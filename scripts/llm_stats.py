#!/usr/bin/env python3
"""Статистика и события маршрута `llm.` / `llm-svc.` по access-логам Higress.

Читает логи ВСЕХ подов шлюза (у `deploy/...` kubectl берёт одну реплику и цифры получаются
половинчатыми) и печатает таблицу по запросам + сводку.

Что откуда берётся (в одной строке лога лежит и то, и другое):
  ai_log (Wasm-плагин статистики): consumer, model, input/output/total_token, reasoning- и
    cached-токены, llm_service_duration (мс, только провайдер), chat_round, response_type;
  поля Envoy: duration (мс, весь запрос), response_code, response_code_details, route_name,
    upstream_cluster, start_time.

ГЛАВНОЕ про «действия» защит. Действие видно в `response_code_details`:
  `via_wasm::higress-system.llm-qwen-guard`  — ответил страж (403, блокировка);
  `via_wasm::higress-system.llm-data-masking` — ответил DLP (денлист `deny_words`);
  `via_wasm::higress-system.llm-token-ratelimit` — квота (429);
  `via_upstream`                              — запрос дошёл до провайдера (то есть страж и DLP пропустили).
У заблокированных запросов `ai_log` пустой («-») — токенов нет, потому что до провайдера дело не дошло.
Поэтому такие строки тоже попадают в таблицу (с нулями), иначе блокировки «исчезают» из статистики.

Маскирование DLP (`replace_roles` + `restore`) логируется ТОЛЬКО отрицательно: в логе нет ни
плейсхолдеров, ни признака подмены — оно видно по `response_code_details` лишь тогда, когда сработал
`deny_words`. Факт маскирования доказывается поведенчески (модель не видит ПДн) или мок-эндпоинтом,
а не логом.

Использование:
    scripts/llm_stats.py                      # последние 2000 строк со всех подов, оба хоста
    scripts/llm_stats.py --tail 20000 --since 30m
    scripts/llm_stats.py --host llm-svc.demo-ai-lab.ru --json /tmp/stats.json
    scripts/llm_stats.py --events-only          # только то, что ответили плагины (403/429/...)
    kubectl -n higress-system logs -l app=higress-gateway --tail=500 | scripts/llm_stats.py --stdin

Замечание: у JWT-маршрута `llm.` потребитель = claim `azp` (например `llm-agent`), у статического
ключа — имя консьюмера из плагина `key-auth` (`llm-svc`).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime

ALL_HOSTS = ("llm.demo-ai-lab.ru", "llm-svc.demo-ai-lab.ru")
PLUGIN_RE = re.compile(r"via_wasm::[^.\s]+\.(\S+)")


def read_logs(tail: int, since: str | None, namespace: str, selector: str, use_stdin: bool) -> list[str]:
    if use_stdin:
        return sys.stdin.read().splitlines()
    cmd = [
        "kubectl", "-n", namespace, "logs", "-l", selector,
        "--tail", str(tail), "--prefix=true", "--max-log-requests", "10",
    ]
    if since:
        cmd.append(f"--since={since}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"kubectl logs: {res.stderr.strip()[:300]}")
    return res.stdout.splitlines()


def parse_line(line: str) -> dict | None:
    """kubectl --prefix=true печатает `[pod/name] {json}` — берём от первой фигурной скобки."""
    i = line.find("{")
    if i < 0:
        return None
    try:
        raw = json.loads(line[i:])
    except json.JSONDecodeError:
        return None
    ai: dict = {}
    ai_raw = raw.get("ai_log")
    if ai_raw and ai_raw != "-":
        try:
            ai = json.loads(ai_raw) or {}
        except json.JSONDecodeError:
            ai = {}
    return {"envoy": raw, "ai": ai}


def responder(envoy: dict) -> str:
    """Кто сформировал ответ: имя Wasm-плагина, `upstream` или сырой код деталей."""
    details = str(envoy.get("response_code_details") or "")
    m = PLUGIN_RE.search(details)
    if m:
        return m.group(1)
    if details.startswith("via_upstream"):
        return "upstream"
    return details or "-"


def hhmmss(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except Exception:
        return (ts or "")[11:19]


def ms(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Статистика запросов к llm./llm-svc. по логам Higress")
    ap.add_argument("--tail", type=int, default=2000, help="сколько последних строк читать (по умолчанию 2000)")
    ap.add_argument("--since", help="окно, как у kubectl: 10m, 1h, 2d")
    ap.add_argument("--host", action="append", help="хост (можно несколько раз); по умолчанию llm. и llm-svc.")
    ap.add_argument("--namespace", default="higress-system")
    ap.add_argument("--selector", default="app=higress-gateway")
    ap.add_argument("--stdin", action="store_true", help="читать лог из stdin вместо kubectl")
    ap.add_argument("--json", help="сохранить разобранные записи в JSON-файл")
    ap.add_argument("--last", type=int, default=20, help="сколько последних запросов показать в таблице")
    ap.add_argument("--events-only", action="store_true", help="показать только ответы плагинов (страж/DLP/квоты)")
    args = ap.parse_args()

    hosts = set(args.host or ALL_HOSTS)
    rows = []
    for line in read_logs(args.tail, args.since, args.namespace, args.selector, args.stdin):
        item = parse_line(line)
        if not item:
            continue
        if item["envoy"].get("authority") not in hosts:
            continue
        item["who"] = responder(item["envoy"])
        if args.events_only and item["who"] == "upstream":
            continue
        rows.append(item)

    if not rows:
        sys.exit("Записей по указанным хостам не найдено (маршрут не вызывали или окно пустое?)")

    rows.sort(key=lambda r: r["envoy"].get("start_time", ""))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print(f"JSON: {args.json} ({len(rows)} записей)\n")

    head = (
        f"{'время':8} {'consumer':10} {'model':16} {'код':>3} {'мс':>6} {'in':>5} {'out':>5} "
        f"{'reason':>6} {'кэш':>5} {'провайдер_мс':>11}  кто ответил"
    )
    print(head)
    print("-" * len(head))
    for r in rows[-args.last:]:
        e, a = r["envoy"], r["ai"]
        print(
            f"{hhmmss(e.get('start_time', '')):8} "
            f"{str(a.get('consumer', '-'))[:10]:10} "
            f"{str(a.get('model', '-'))[:16]:16} "
            f"{str(e.get('response_code', '-')):>3} "
            f"{ms(e.get('duration')):>6} "
            f"{a.get('input_token', 0):>5} "
            f"{a.get('output_token', 0):>5} "
            f"{((a.get('output_token_details') or {}).get('reasoning_tokens', 0)):>6} "
            f"{((a.get('input_token_details') or {}).get('cached_tokens', 0)):>5} "
            f"{a.get('llm_service_duration', 0):>11}  "
            f"{r['who']}"
        )

    total_in = sum(r["ai"].get("input_token", 0) or 0 for r in rows)
    total_out = sum(r["ai"].get("output_token", 0) or 0 for r in rows)
    codes: dict[str, int] = {}
    who_count: dict[str, int] = {}
    consumers: dict[str, list[int]] = {}
    for r in rows:
        code = str(r["envoy"].get("response_code"))
        codes[code] = codes.get(code, 0) + 1
        who_count[r["who"]] = who_count.get(r["who"], 0) + 1
        c = consumers.setdefault(str(r["ai"].get("consumer", "-")), [0, 0, 0])
        c[0] += 1
        c[1] += r["ai"].get("input_token", 0) or 0
        c[2] += r["ai"].get("output_token", 0) or 0

    ok_durs = sorted(ms(r["envoy"].get("duration")) for r in rows if r["who"] == "upstream")
    p95 = ok_durs[min(len(ok_durs) - 1, int(len(ok_durs) * 0.95))] if ok_durs else 0
    overhead = [
        ms(r["envoy"].get("duration")) - int(r["ai"].get("llm_service_duration") or 0)
        for r in rows
        if r["ai"].get("llm_service_duration")
    ]
    print()
    print(f"всего запросов: {len(rows)} | in={total_in} out={total_out} токенов")
    print("коды ответов: " + ", ".join(f"{k}×{v}" for k, v in sorted(codes.items())))
    print("кто ответил: " + ", ".join(f"{k}×{v}" for k, v in sorted(who_count.items(), key=lambda kv: -kv[1])))
    if ok_durs:
        print(f"длительность успешных: средняя {sum(ok_durs) // len(ok_durs)} мс, p95 {p95} мс")
    if overhead:
        print(f"цена защиты (весь запрос − провайдер): средняя {sum(overhead) // len(overhead)} мс (DLP + страж + шлюз)")
    for who, (n, i, o) in sorted(consumers.items(), key=lambda kv: -kv[1][0]):
        print(f"  {who}: {n} запросов, in={i}, out={o}")


if __name__ == "__main__":
    main()
