#!/usr/bin/env python3
"""Приёмка GLM-OCR через шлюз стенда (кейс 04).

Отправляет картинку в OpenAI-совместимый /v1/chat/completions и печатает распознанный текст,
время ответа и usage. Значения ключа/адреса — только из окружения, в коде секретов нет.

    export GPUSTACK_API_KEY=<ключ стенда>
    export GPUSTACK_API_BASE=https://api.demo-ai-lab.ru   # необязательно, это значение по умолчанию
    export RESOLVE_IP=192.168.10.230                      # необязательно: ходить в стенд по LAN
    python3 scripts/glm_ocr_smoke.py --image /tmp/ocr-test2.png

Коды выхода: 0 — 200 и непустой текст, 1 — ошибка/пустой ответ, 2 — нет ключа или файла.
"""

import argparse
import base64
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://api.demo-ai-lab.ru"
DEFAULT_PROMPT = "Text Recognition:"


def build_opener(resolve_ip):
    ctx = ssl.create_default_context()
    if resolve_ip:
        # самоподписанный/корпоративный корень: проверку имени оставляем, цепочку — нет
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    class Resolver(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_pinned_connection(resolve_ip, ctx), req, context=ctx)

    return urllib.request.build_opener(Resolver)


def _pinned_connection(resolve_ip, ctx):
    import http.client

    class HTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, host, **kwargs):
            kwargs.pop("context", None)  # контекст берём из замыкания
            super().__init__(host, context=ctx, **kwargs)

        def connect(self):
            sock = socket.create_connection((resolve_ip or self.host, self.port or 443), self.timeout)
            self.sock = ctx.wrap_socket(sock, server_hostname=self.host.split(":")[0])

    return HTTPSConnection


def main():
    ap = argparse.ArgumentParser(description="Smoke-тест GLM-OCR через /v1/chat/completions")
    ap.add_argument("--image", required=True, help="файл картинки (png/jpg)")
    ap.add_argument("--model", default="GLM-OCR")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="по умолчанию 'Text Recognition:'")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--base", default=os.environ.get("GPUSTACK_API_BASE", DEFAULT_BASE))
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--json", action="store_true", help="печатать JSON вместо текста")
    args = ap.parse_args()

    key = os.environ.get("GPUSTACK_API_KEY", "").strip()
    if not key:
        print("нет GPUSTACK_API_KEY в окружении (значение — из приватного хранилища)", file=sys.stderr)
        return 2
    if not os.path.exists(args.image):
        print(f"нет файла: {args.image}", file=sys.stderr)
        return 2

    with open(args.image, "rb") as fh:
        raw = fh.read()
    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    data_url = f"data:{mime};base64," + base64.b64encode(raw).decode()

    payload = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": args.prompt},
            ],
        }],
    }

    url = args.base.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    opener = build_opener(os.environ.get("RESOLVE_IP", "").strip())

    started = time.time()
    try:
        with opener.open(req, timeout=args.timeout) as resp:
            status, body = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:400]}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
        print(f"запрос не прошёл: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - started

    doc = json.loads(body)
    text = (doc.get("choices") or [{}])[0].get("message", {}).get("content") or ""

    if args.json:
        print(json.dumps({"http": status, "elapsed_s": round(elapsed, 2), "text": text,
                          "usage": doc.get("usage")}, ensure_ascii=False, indent=1))
    else:
        print(f"http {status} · {elapsed:.2f}s · {args.model} · {urllib.parse.urlsplit(url).netloc}")
        print(f"usage: {doc.get('usage')}")
        print("-" * 60)
        print(text)

    if not text.strip():
        print("пустой ответ модели", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
