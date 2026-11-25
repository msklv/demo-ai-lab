#!/usr/bin/env python3
"""Синтез речи с клоном голоса через шлюз стенда (кейс 08).

Отправляет текст в OpenAI-совместимый /v1/audio/speech вместе с референсом (wav → base64)
и печатает время ответа, длительность и частоту полученного файла. Ключ — только из окружения
или из приватного файла; значение в вывод не попадает.

    export GPUSTACK_API_KEY=<ключ tts-demo>
    export GPUSTACK_API_BASE=https://api.demo-ai-lab.ru   # необязательно, это значение по умолчанию
    python3 scripts/tts_demo.py --text-file /tmp/text.txt \
        --ref-audio architecture/specs/tts-voice-clone-ref-01.wav --out /tmp/qwen.wav

    # второй ход: CosyVoice3 требует транскрипт референса
    python3 scripts/tts_demo.py --model CosyVoice3-0.5B --ref-text "транскрипт референса" …

    # вместо export — строка `tts-demo (…): <ключ>` приватного файла
    python3 scripts/tts_demo.py --key-file gpustack-admin.local.md …

Коды выхода: 0 — 200 и непустой wav, 1 — ошибка/пустой ответ, 2 — нет ключа/файла.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave

DEFAULT_BASE = "https://api.demo-ai-lab.ru"
QWEN = "Qwen3-TTS-1.7B-Base"
COSY = "CosyVoice3-0.5B"


def read_key(args):
    key = os.environ.get("GPUSTACK_API_KEY", "").strip()
    if key:
        return key, "env"
    if args.key_file:
        try:
            for line in open(args.key_file, encoding="utf-8"):
                if line.startswith("tts-demo"):
                    m = re.search(r":\s*(\S+)\s*$", line)
                    if m:
                        return m.group(1), args.key_file
        except OSError as e:
            print(f"нет файла ключа: {e}", file=sys.stderr)
    return "", ""


def build_payload(args, ref_b64):
    payload = {"model": args.model, "input": args.text, "language": args.language,
               "response_format": "wav", "ref_audio": "data:audio/wav;base64," + ref_b64}
    if args.ref_text:
        payload["ref_text"] = args.ref_text
    else:
        payload["x_vector_only_mode"] = True
    return payload


def main():
    ap = argparse.ArgumentParser(description="TTS с клоном голоса через api.demo-ai-lab.ru (кейс 08)")
    ap.add_argument("--model", default=QWEN, choices=[QWEN, COSY], help="модель (по умолчанию %(default)s)")
    ap.add_argument("--text", help="текст для синтеза")
    ap.add_argument("--text-file", help="файл с текстом (альтернатива --text)")
    ap.add_argument("--ref-audio", required=True, help="референс: wav 8–10 с, mono")
    ap.add_argument("--ref-text", help="транскрипт референса; обязателен для CosyVoice3-0.5B")
    ap.add_argument("--language", default="Russian", help="язык синтеза (по умолчанию %(default)s)")
    ap.add_argument("--out", default="tts-out.wav", help="куда писать wav (по умолчанию %(default)s)")
    ap.add_argument("--base", default=os.environ.get("GPUSTACK_API_BASE", DEFAULT_BASE))
    ap.add_argument("--key-file", help="приватный файл со строкой `tts-demo …: <ключ>`")
    args = ap.parse_args()

    if args.text_file:
        try:
            args.text = open(args.text_file, encoding="utf-8").read().strip()
        except OSError as e:
            print(f"нет файла текста: {e}", file=sys.stderr)
            return 2
    if not args.text:
        print("нужен --text или --text-file", file=sys.stderr)
        return 2
    if args.model == COSY and not args.ref_text:
        print("CosyVoice3-0.5B требует --ref-text (транскрипт референса)", file=sys.stderr)
        return 2

    key, key_src = read_key(args)
    if not key:
        print("нет ключа: export GPUSTACK_API_KEY=… или --key-file", file=sys.stderr)
        return 2
    try:
        ref_b64 = base64.b64encode(open(args.ref_audio, "rb").read()).decode()
    except OSError as e:
        print(f"нет референса: {e}", file=sys.stderr)
        return 2

    body = json.dumps(build_payload(args, ref_b64)).encode()
    req = urllib.request.Request(
        args.base.rstrip("/") + "/v1/audio/speech", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    print(f"POST {args.base.rstrip('/')}/v1/audio/speech · {args.model} · {len(args.text)} знаков "
          f"· ключ из {key_src}")
    t0 = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=600)
        data = resp.read()
        status = resp.status
    except urllib.error.HTTPError as e:
        print(f"{e.code}: {e.read().decode(errors='replace')[:400]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"сеть: {e}", file=sys.stderr)
        return 1
    dt = time.time() - t0
    if status != 200 or not data.startswith(b"RIFF"):
        print(f"не wav: status={status} bytes={len(data)}", file=sys.stderr)
        return 1
    open(args.out, "wb").write(data)
    with wave.open(args.out) as w:
        dur = w.getnframes() / w.getframerate()
        rate, ch = w.getframerate(), w.getnchannels()
    print(f"200 · ответ {dt:.1f} с · звук {dur:.2f} с ({rate} Гц, {ch} кан.) · "
          f"{dt / dur:.2f}× реального времени · {len(data)} Б → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
