#!/usr/bin/env python3
"""warm_images.py — проверка и прогрев образов раннеров GPUStack на нодах стенда demo-ai-lab.

Зачем: kubelet's image GC выселяет образы остановленных моделей, и тогда `Start` в GPUStack
начинается с pull'а на 9–11 ГБ (замер 2026-11-06: VoxBox-раннер — 13 мин, vLLM 0.25.1 — ~10 мин).
На сцене это пауза в программе, поэтому образы всех кейсов проверяются и прогреваются заранее.

Что делает:
  1) читает `kubectl get node -o json` (status.images) и показывает, какие образы уже в сторе ноды;
  2) отсутствующие «прогревает» — поднимает на нужной ноде короткоживущий под с этим образом
     (imagePullPolicy: IfNotPresent), ждёт Running, удаляет под. Образ остаётся в сторе containerd.

Зависимости: только стандартная библиотека Python 3.9+ и `kubectl` в PATH. sudo не нужен.

Примеры:
    python3 scripts/warm_images.py                  # проверить и прогреть недостающие
    python3 scripts/warm_images.py --check-only     # только проверка (ничего не создаёт)
    python3 scripts/warm_images.py --dry-run        # показать план, ничего не делать
    python3 scripts/warm_images.py --json
    python3 scripts/warm_images.py --image docker.io/gpustack/runner:cuda13.0-vllm0.25.1 --node k8s-04

Коды выхода: 0 — все образы на месте; 2 — часть прогрета (были не на месте); 1 — прогреть не удалось.

Приватность: логинов, MAC и паролей нет; адреса нод — документированные LAN-адреса стенда.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

# Образы раннеров по моделям GPUStack (источник: GET /v2/models, /v2/inference-backends;
# замер 2026-11-06). Ключ — нода, где образ нужен.
REQUIRED: dict[str, list[tuple[str, float, str]]] = {
    "k8s-04": [
        ("docker.io/gpustack/runner:cuda13.0-vllm0.25.1", 9.5,
         "страж Qwen3Guard-Gen-4B/0.6B, gemma-4-12B (vLLM 0.25.1)"),
        ("docker.io/gpustack/runner:cuda13.0-vllm0.22.1", 9.9,
         "Z-Image-Turbo, vLLM-Omni (кейс 07)"),
        ("docker.io/gpustack/runner:cuda12.8-voxbox0.0.21", 10.8,
         "whisper-turbo, VoxBox (кейс 03)"),
        ("nvidia/cuda:13.3.0-runtime-ubuntu24.04", 1.5,
         "custom backend beellama-custom: Qwen3.8-27B-UD (кейс 01)"),
    ],
    "k8s-01": [
        ("docker.io/gpustack/runner:rocm7.2-vllm0.25.1", 11.8,
         "bge-m3 + bge-reranker-v2-m3 на 780M (кейс 05)"),
    ],
}
# Объёмы — распакованный размер в сторе containerd (kubectl get node, status.images, замер 2026-11-06),
# кроме `vllm0.22.1` — он снят image GC и взят из замера 2026-11-04.
TOTAL_GB = sum(size for items in REQUIRED.values() for _, size, _ in items)

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}
ICONS = {OK: "✔", WARN: "▲", FAIL: "✘"}
RESET = "\033[0m"


def color_enabled(no_color: bool) -> bool:
    return (not no_color) and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, status: str, use_color: bool) -> str:
    return f"{COLORS[status]}{ICONS[status]} {text}{RESET}" if use_color else f"{ICONS[status]} {text}"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def kubectl(ctx: list[str], *args: str, stdin: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
    cmd = ["kubectl", *ctx, *args]
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise SystemExit("kubectl не найден в PATH")
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout {timeout}s: {' '.join(args)}"
    return p.returncode, p.stdout, p.stderr


def node_images(ctx: list[str], node: str) -> tuple[dict[str, float], str]:
    """Образы из status.images ноды: имя → размер в ГБ (kubelet обновляет с задержкой до ~5 мин)."""
    rc, out, err = kubectl(ctx, "get", "node", node, "-o", "json")
    if rc != 0:
        return {}, err.strip() or f"kubectl get node {node} → rc={rc}"
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        return {}, f"не разобрал JSON ноды: {e}"
    images: dict[str, float] = {}
    for img in data.get("status", {}).get("images") or []:
        for n in img.get("names") or []:
            images[normalize(n)] = round(img.get("sizeBytes", 0) / 1e9, 1)
    return images, ""


def normalize(ref: str) -> str:
    """docker.io/library/x == x, снятие @sha256 и прочих украшений для сравнения."""
    ref = ref.split("@", 1)[0]
    for prefix in ("docker.io/library/", "docker.io/", "index.docker.io/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
            break
    return ref


def ensure_namespace(ctx: list[str], ns: str) -> None:
    rc, _, err = kubectl(ctx, "get", "namespace", ns, "-o", "name")
    if rc != 0:
        log(f"… создаю namespace {ns}")
        rc, _, err = kubectl(ctx, "create", "namespace", ns)
        if rc != 0:
            raise SystemExit(f"не смог создать namespace {ns}: {err.strip()}")


def warm_one(ctx: list[str], ns: str, node: str, image: str, timeout: int) -> tuple[bool, str]:
    """Поднимает под с образом на ноде и ждёт, пока образ реально скачается (под стал Running)."""
    name = f"warm-{uuid.uuid4().hex[:8]}"
    manifest = f"""apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {ns}
  labels:
    app: img-warm
    demo-ai-lab/role: image-warmup
spec:
  nodeName: {node}
  restartPolicy: Never
  terminationGracePeriodSeconds: 0
  tolerations:
    - operator: Exists
  containers:
    - name: warm
      image: {image}
      imagePullPolicy: IfNotPresent
      command: ["sleep", "60"]
"""
    rc, _, err = kubectl(ctx, "apply", "-f", "-", stdin=manifest)
    if rc != 0:
        return False, f"apply: {err.strip()}"

    started = time.time()
    last_note = 0
    try:
        while time.time() - started < timeout:
            rc, out, err = kubectl(ctx, "get", "pod", name, "-n", ns, "-o", "json")
            if rc != 0:
                return False, f"get pod: {err.strip()}"
            pod = json.loads(out)
            phase = pod.get("status", {}).get("phase", "")
            cs = (pod.get("status", {}).get("containerStatuses") or [{}])[0]
            state = cs.get("state") or {}
            elapsed = int(time.time() - started)
            if phase in ("Running", "Succeeded"):
                return True, f"прогрет за {elapsed} с"
            if phase == "Failed" or state.get("terminated"):
                reason = (state.get("terminated") or {}).get("reason", "")
                return False, f"под завершился ({reason or phase}) — образ мог скачаться, проверь status.images"
            if state.get("waiting", {}).get("reason") == "ImagePullBackOff":
                return False, f"ImagePullBackOff: {state['waiting'].get('message', '')[:160]}"
            if elapsed - last_note >= 60:
                waiting = state.get("waiting", {}).get("reason", "ContainerCreating")
                log(f"    … {elapsed} с: {waiting}")
                last_note = elapsed
            time.sleep(5)
        return False, f"не дождался за {timeout} с (образ всё ещё тянется)"
    finally:
        kubectl(ctx, "delete", "pod", name, "-n", ns, "--wait=false", "--grace-period=0", timeout=60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка и прогрев образов раннеров GPUStack")
    ap.add_argument("--kubeconfig", default=os.environ.get("KUBECONFIG", str(os.path.expanduser("~/.kube/demo-ai-lab.conf"))))
    ap.add_argument("--context", default="demo-ai-lab")
    ap.add_argument("--check-only", action="store_true", help="только проверить, ничего не создавать")
    ap.add_argument("--dry-run", action="store_true", help="показать план прогрева")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--timeout", type=int, default=1200, help="ожидание одного образа, с (по умолчанию 1200)")
    ap.add_argument("--namespace", default="img-warm", help="ns для временных подов прогрева")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--node", action="append", default=[], help="ограничить нодой (повторяемо)")
    ap.add_argument("--image", action="append", default=[], help="ограничить образом (повторяемо)")
    args = ap.parse_args()

    use_color = color_enabled(args.no_color)
    ctx = ["--kubeconfig", args.kubeconfig] if args.kubeconfig else []
    if args.context:
        ctx += ["--context", args.context]

    plan: list[tuple[str, str, float, str]] = []
    for node, items in REQUIRED.items():
        if args.node and node not in args.node:
            continue
        for image, size, why in items:
            if args.image and image not in args.image:
                continue
            plan.append((node, image, size, why))

    if not plan:
        log("нечего проверять: фильтры --node/--image не совпали с таблицей образов")
        return 1

    results: list[dict] = []
    missing = 0

    if not args.json:
        print(f"Образы раннеров GPUStack по нодам (суммарно ≈{TOTAL_GB:.1f} ГБ на 2 ноды)\n")

    for node, image, size, why in plan:
        present, err = node_images(ctx, node)
        if err:
            results.append({"node": node, "image": image, "size_gb": size, "why": why, "status": FAIL, "detail": err})
            if not args.json:
                print(paint(f"{node}  {size:.1f} ГБ  {image}\n      {why}\n      ошибка: {err}", FAIL, use_color))
            continue

        actual = present.get(normalize(image))
        if actual is not None:
            results.append({"node": node, "image": image, "size_gb": actual, "why": why,
                            "status": OK, "detail": "уже в сторе ноды"})
            if not args.json:
                print(paint(f"{node}  {actual:.1f} ГБ  {image} — уже в сторе", OK, use_color))
            continue

        missing += 1
        if args.check_only:
            results.append({"node": node, "image": image, "size_gb": size, "why": why, "status": WARN,
                            "detail": "нет в сторе ноды (Start потянет на сцене)"})
            if not args.json:
                print(paint(f"{node}  {size:.1f} ГБ  {image} — НЕТ в сторе ({why})", WARN, use_color))
            continue

        if args.dry_run:
            results.append({"node": node, "image": image, "size_gb": size, "why": why,
                            "status": WARN, "detail": "план: прогреть"})
            if not args.json:
                print(paint(f"{node}  {size:.1f} ГБ  {image} — прогреть (dry-run)", WARN, use_color))
            continue

        if not args.json:
            print(f"▲ {node}  {size:.1f} ГБ  {image} — нет в сторе, тяну ({why})")
        ensure_namespace(ctx, args.namespace)
        ok, detail = warm_one(ctx, args.namespace, node, image, args.timeout)
        status = OK if ok else FAIL
        results.append({"node": node, "image": image, "size_gb": size, "why": why,
                        "status": status, "detail": detail})
        if not args.json:
            print(paint(f"{node}  {size:.1f} ГБ  {image} — {detail}", status, use_color))

    if args.json:
        print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    else:
        ok_n = sum(1 for r in results if r["status"] == OK)
        warn_n = sum(1 for r in results if r["status"] == WARN)
        fail_n = sum(1 for r in results if r["status"] == FAIL)
        print(f"\nИТОГО: {ok_n} в сторе · {warn_n} отсутствует · {fail_n} ошибок (проверено {len(results)})")
        if warn_n and args.check_only:
            print("Прогрев: python3 scripts/warm_images.py (без --check-only)")
        print("Замечание: kubelet обновляет status.images с задержкой до ~5 мин, а image GC может\n"
              "выселить непрогретые образы снова — перед показом греть непосредственно перед сценой\n"
              "и держать диск с запасом (порог выселения 15 %).")

    if any(r["status"] == FAIL for r in results):
        return 1
    if missing:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
