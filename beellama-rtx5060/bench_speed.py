#!/usr/bin/env python3
"""Микро-бенчмарк скорости BeeLlama llama-server (Qwen3.8-27B IQ3_S-mtp, alias Qwen3.8-27B-UD).

Мерит на 3 размерах контекста (последний — максимальный для запуска = n_ctx сервера минус
бюджет генерации), parallelism = 1 (последовательные запросы, без конкуренции):

  * TTFT        — время до первого токена (streaming SSE, первый non-null delta
                  content/reasoning_content); включает prefill;
  * prefill t/s — prompt_tokens / TTFT;
  * decode t/s  — (completion_tokens - 1) / время генерации (первый→последний токен),
                  включает reasoning-токены (сервер запущен с --reasoning on, effort xhigh);
  * E2E         — полное время запроса.

Филлер — детерминированная кириллица, seed = run_salt + i (по умолчанию run_salt случайный,
фиксируется через --seed). Уникальный контент на каждый прогон исключает попадание в
prompt-cache (иначе prefill/TTFT замеряется по кэшу, а не холодным). Калибровка
«символы/токен» выполняется одним запросом перед замерами, поэтому фактические
prompt_tokens ложатся вплотную к целевым.

Запуск: python3 bench_speed.py [--host 192.168.10.252] [--port 8081]
        [--sizes 4096,32768,127000] [--max-tokens 512] [--seed N] [--json bench-results.json]
"""

import argparse
import json
import random
import sys
import time
import urllib.request

WORDS = ["терраса", "спутник", "кабель", "матрица", "гранит", "фонарь", "коридор",
         "ротор", "пластина", "сектор", "контур", "барьер", "шлейф", "домен", "азимут",
         "кессон", "статор", "балка", "растр", "жгут", "портал", "дроссель", "тигель"]

INSTRUCTION = ("\n\nИтог: напиши ровно двадцать коротких предложений о содержании текста "
               "выше, каждое с новой строки, без рассуждений.")

MODEL = "Qwen3.8-27B-UD"


def gen_filler(target_chars, seed):
    """Детерминированный текст ровно из target_chars символов кириллицы (~3 симв/токен)."""
    rnd = random.Random(seed)
    parts, total = [], 0
    i = 0
    while total < target_chars:
        i += 1
        # zero-pad счётчика: длина строки (и соотношение симв/токен) одинакова на любой
        # длине филлера, иначе «Абзац 9» → «Абзац 2400» дрейфует ratio на ~2% к масштабу 127K
        line = f"Абзац {i:05d}. " + " ".join(rnd.choice(WORDS) for _ in range(45)) + "."
        parts.append(line)
        total += len(line) + 1
    return ("\n".join(parts))[:target_chars]


class Client:
    def __init__(self, base):
        self.base = base

    def _post(self, payload, timeout=3600):
        req = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    def prompt_tokens(self, content, max_tokens=1):
        """НЕ-streaming запрос только ради usage.prompt_tokens (для калибровки)."""
        with self._post({"model": MODEL, "max_tokens": max_tokens,
                         "messages": [{"role": "user", "content": content}]}) as r:
            obj = json.load(r)
        return obj["usage"]["prompt_tokens"]

    def bench(self, content, max_tokens):
        """Streaming-замер: возвращает словарь метрик + фактический usage."""
        t_send = time.perf_counter()
        first = last = None
        usage = {}
        timings = {}
        buf = b""
        with self._post({"model": MODEL, "max_tokens": max_tokens, "stream": True,
                         "stream_options": {"include_usage": True},
                         "messages": [{"role": "user", "content": content}]}) as r:
            for chunk in r:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.decode(errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("usage"):
                        usage = obj["usage"]
                    if obj.get("timings"):
                        timings = obj["timings"]
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    c = delta.get("content") or ""
                    rc = delta.get("reasoning_content") or ""
                    if c or rc:
                        now = time.perf_counter()
                        if first is None:
                            first = now
                        last = now
        t_end = time.perf_counter()

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        ctd = usage.get("completion_tokens_details") or {}
        ptd = usage.get("prompt_tokens_details") or {}
        reasoning_tokens = ctd.get("reasoning_tokens")
        visible_tokens = ctd.get("visible_tokens")
        cached_tokens = ptd.get("cached_tokens", 0)

        ttft = (first - t_send) if first else None
        gen_time = (last - first) if (first and last) else 0.0
        total = t_end - t_send

        draft_n = timings.get("draft_n", 0)
        draft_acc = timings.get("draft_n_accepted", 0)
        acceptance = draft_acc / draft_n if draft_n else None

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "visible_tokens": visible_tokens,
            "cached_tokens": cached_tokens,
            "cache_source": timings.get("cache_source"),
            "cache_reason": timings.get("cache_reason"),
            "ttft_s": ttft,
            # клиентские (end-to-end, включают сеть)
            "prefill_tps": prompt_tokens / ttft if ttft else None,
            "decode_tps": (completion_tokens - 1) / gen_time
                          if (gen_time > 0 and completion_tokens > 1) else None,
            "total_s": total,
            # серверные (timings из финального чанка — чистый GPU, без сети)
            "prompt_ms": timings.get("prompt_ms"),
            "prompt_per_second": timings.get("prompt_per_second"),
            "predicted_per_second": timings.get("predicted_per_second"),
            "draft_n": draft_n,
            "draft_accepted": draft_acc,
            "acceptance": acceptance,
        }


def fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


def main():
    ap = argparse.ArgumentParser(description="Микро-бенчмарк скорости BeeLlama llama-server")
    ap.add_argument("--host", default="192.168.10.252")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--sizes", default="4096,32768,max",
                    help="целевые prompt_tokens; 'max' = n_ctx - max_tokens - 256 (последний — максимальный)")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--json", default=None, help="сохранить результаты в JSON")
    ap.add_argument("--seed", type=int, default=None,
                    help="salt филлера (по умолчанию — случайный; фиксируй для воспроизводимости)")
    a = ap.parse_args()

    raw_sizes = [x.strip() for x in a.sizes.split(",") if x.strip()]
    if len(raw_sizes) != 3:
        sys.exit("--sizes должен задавать ровно 3 целевых размера контекста")

    base = f"http://{a.host}:{a.port}"
    cli = Client(base)

    # n_ctx сервера (потолок) — из /v1/models
    with urllib.request.urlopen(base + "/v1/models", timeout=30) as r:
        n_ctx = json.load(r)["data"][0]["meta"]["n_ctx"]

    # "max" → n_ctx минус бюджет генерации и запас, чтобы completion не урезался
    def resolve(x):
        if x == "max":
            return n_ctx - a.max_tokens - 256
        return int(x)
    sizes = [resolve(x) for x in raw_sizes]

    # 0) warmup (первый запрос после idle — всегда медленный)
    cli.prompt_tokens("Разогрев. Ответь: ок.", max_tokens=8)

    # 1) калибровка симв/токен: base = шаблон+инструкция, ratio = филлер (по ФАКТИЧЕСКОЙ длине)
    base_tokens = cli.prompt_tokens(INSTRUCTION, max_tokens=1)
    sample_chars = 6000
    sample = gen_filler(sample_chars, seed=777)
    sample_tokens = cli.prompt_tokens(sample + INSTRUCTION, max_tokens=1)
    ratio = len(sample) / (sample_tokens - base_tokens)
    run_salt = a.seed if a.seed is not None else random.SystemRandom().randint(0, 2**31 - 1)
    print(f"n_ctx={n_ctx}  base_tokens={base_tokens}  ratio={ratio:.3f} симв/токен  "
          f"run_salt={run_salt}")

    results = []
    print("prefill/decode tok/s: client — по TTFT клиента (вкл. сеть), server — timings сервера (чистый GPU)")
    print(f"\n{'context':>8} {'TTFT,ms':>8}  {'prefill tok/s':>16}  "
          f"{'decode tok/s':>16}  {'compl':>5} {'MTP,%':>5} {'E2E,s':>7}")
    print(f"{'':>8} {'':>8}  {'client':>7} {'server':>8}  "
          f"{'client':>7} {'server':>8}")
    print("-" * 82)
    for i, target in enumerate(sizes):
        filler_tokens = target - base_tokens
        chars = int(filler_tokens * ratio)
        # уникальный seed на каждый размер → никакого prompt-cache между замерами
        content = gen_filler(chars, seed=run_salt + i) + INSTRUCTION
        m = cli.bench(content, a.max_tokens)
        m["target_tokens"] = target
        m["filler_chars"] = chars
        results.append(m)
        mtp = f"{m['acceptance']*100:.0f}" if m['acceptance'] is not None else "—"
        print(f"{m['prompt_tokens']:>8} {fmt(m['ttft_s']*1000, 0):>8}  "
              f"{fmt(m['prefill_tps'], 0):>7} {fmt(m['prompt_per_second'], 0):>8}  "
              f"{fmt(m['decode_tps'], 1):>7} {fmt(m['predicted_per_second'], 1):>8}  "
              f"{m['completion_tokens']:>5} {mtp:>5} {fmt(m['total_s'], 1):>7}",
              flush=True)
        warn = "  *** WARM CACHE — prefill замерен по кэшу, НЕ холодный! ***" if m["cached_tokens"] else ""
        sys.stderr.write(f"[{i+1}/3] context={m['prompt_tokens']} wall={m['total_s']:.1f}s "
                         f"reasoning={m['reasoning_tokens']} visible={m['visible_tokens']} "
                         f"cached={m['cached_tokens']} cache={m['cache_source']}{warn}\n")

    if a.json:
        with open(a.json, "w") as f:
            json.dump({"server": base, "model": MODEL, "n_ctx": n_ctx,
                       "max_tokens": a.max_tokens, "parallelism": 1,
                       "run_salt": run_salt, "results": results},
                      f, ensure_ascii=False, indent=2)
        print(f"\nJSON сохранён: {a.json}")


if __name__ == "__main__":
    main()
