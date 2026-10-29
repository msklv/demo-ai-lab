#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Рендер диаграмм стенда в JPEG: все *.excalidraw и *.html в каталоге.

Рядом с каждым источником появляется одноимённый .jpg (единственный формат вывода):
    architecture/architecture-c2.excalidraw         -> architecture/architecture-c2.jpg
    architecture/demo-ai-lab-architecture.html      -> architecture/demo-ai-lab-architecture.jpg

Использование:
    python3 scripts/render_diagrams.py                        # architecture/, всё
    python3 scripts/render_diagrams.py --changed              # только изменённые источники
    python3 scripts/render_diagrams.py --scale 2              # выше разрешение (по умолчанию 1)
    python3 scripts/render_diagrams.py --jpeg-quality 95      # качество JPEG, 1–100 (по умолчанию 90)
    python3 scripts/render_diagrams.py --file architecture-c2.excalidraw
    python3 scripts/render_diagrams.py --html-width 1600      # ширина вьюпорта для HTML
    python3 scripts/render_diagrams.py <другой_каталог> [--changed]

Движок:
  * .excalidraw — @excalidraw/utils (`exportScene`) в headless Chromium: тот же экспортёр,
    что у excalidraw.com, без загрузки файла на сайт; сцена кладётся на белый canvas и
    кодируется в JPEG прямо в браузере — промежуточных файлов нет.
  * .html — полноэкранный снимок (`fullPage`, `type: 'jpeg'`), анимации/переходы отключены
    для воспроизводимости, шрифты дожидаемся через document.fonts.ready.

Требования: node >= 18 + npm; Chromium (кэш Playwright или системный Chrome,
переопределяется CHROME_PATH). Первый запуск ставит @excalidraw/utils, puppeteer-core и
esbuild в `<repo>/.render-cache` (в .gitignore) и собирает бандл экспортёра.

Выход: 0 — все файлы отрендерены, 1 — есть ошибки или рендерить нечего.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO / "architecture"

SRC_JS = 'import { exportScene } from "@excalidraw/utils";\nwindow.__exportScene = exportScene;\n'

RENDER_MJS = r"""
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';
import puppeteer from 'puppeteer-core';

const files = process.argv.slice(2);
const CHROME = process.env.CHROME_PATH;
const scale = Number(process.env.RENDER_SCALE || '1');
const quality = Number(process.env.JPEG_QUALITY || '90');
const htmlWidth = Number(process.env.HTML_WIDTH || '1400');
const dir = path.dirname(new URL(import.meta.url).pathname);

let bundle = null;
const getBundle = () => {
  if (bundle === null) bundle = fs.readFileSync(path.join(dir, 'bundle.js'), 'utf8');
  return bundle;
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none', '--allow-file-access-from-files'],
});

const report = (out, extra) => {
  const size = fs.existsSync(out) ? fs.statSync(out).size : 0;
  console.log('ok\t' + out + '\t' + size + (extra ? '\t' + extra : ''));
};

let failed = 0;
for (const f of files) {
  try {
    const out = f.replace(/\.(excalidraw|html)$/, '.jpg');
    if (/\.html$/.test(f)) {
      const page = await browser.newPage();
      await page.setViewport({ width: htmlWidth, height: 1200, deviceScaleFactor: scale });
      const url = pathToFileURL(path.resolve(f)).href;
      await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 }).catch(async () => {
        await page.goto(url, { waitUntil: 'load', timeout: 45000 });  // офлайн: внешние шрифты не пришли
      });
      await page.evaluate(async () => {
        if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (e) {} }
      });
      // стабильный снимок: гасим анимации/переходы (pulse-точки и т.п.)
      await page.addStyleTag({ content: '*,*::before,*::after{animation:none !important;transition:none !important;caret-color:transparent !important}' });
      await new Promise(r => setTimeout(r, 400));
      await page.screenshot({ path: out, type: 'jpeg', quality, fullPage: true, captureBeyondViewport: true });
      const dims = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]);
      report(out, dims.join('x'));
      await page.close();
    } else {
      const scene = JSON.parse(fs.readFileSync(f, 'utf8'));
      const page = await browser.newPage();
      await page.setViewport({ width: 1600, height: 1200 });
      await page.setContent('<html><body style="margin:0"><script>' + getBundle() + '</script></body></html>', { waitUntil: 'load' });
      await new Promise(r => setTimeout(r, 800));  // сцена грузится; меньше = обрезанный холст
      const b64 = await page.evaluate(async (scene, scale, quality) => {
        const appState = { ...(scene.appState || {}), exportBackground: true, viewBackgroundColor: '#ffffff', exportWithDarkMode: false };
        const blob = await window.__exportScene({
          data: { elements: scene.elements, appState, files: scene.files || {} },
          type: 'png',   // растровый рендер сцены; в файл уходит только JPEG
          config: { canvasBackgroundColor: '#ffffff', padding: 20, scale },
        });
        // JPEG без альфы: сцену кладём на белый canvas и кодируем в браузере
        const bmp = await createImageBitmap(blob);
        const canvas = document.createElement('canvas');
        canvas.width = bmp.width;
        canvas.height = bmp.height;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bmp, 0, 0);
        return canvas.toDataURL('image/jpeg', quality / 100).split(',')[1];
      }, scene, scale, quality);
      fs.writeFileSync(out, Buffer.from(b64, 'base64'));
      report(out, scene.elements.length + ' elements');
      await page.close();
    }
  } catch (e) {
    failed += 1;
    console.error('fail\t' + f + '\t' + (e && e.message ? e.message : e));
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
"""


def run(cmd, cwd=None, env=None):
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, check=True)


def find_chrome() -> str:
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    patterns = [
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-mac*/headless_shell",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ]
    for pat in patterns:
        for h in reversed(sorted(glob.glob(str(Path(pat).expanduser())))):
            if os.access(h, os.X_OK):
                return h
    sys.exit("no Chromium found: set CHROME_PATH or install Google Chrome / Playwright Chromium")


def ensure_engine(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "src.js").write_text(SRC_JS, encoding="utf-8")
    (cache / "render.mjs").write_text(RENDER_MJS, encoding="utf-8")
    pkg = cache / "package.json"
    if not pkg.exists():
        pkg.write_text(json.dumps({"name": "diagrams-render", "private": True, "type": "module"}, indent=2) + "\n", encoding="utf-8")
    if not (cache / "node_modules" / "@excalidraw" / "utils").exists():
        print("[render] npm install (первый запуск, ~15 с)...", file=sys.stderr)
        run(["npm", "i", "--no-audit", "--no-fund", "@excalidraw/utils", "puppeteer-core", "esbuild"], cwd=cache)
    bundle = cache / "bundle.js"
    if not bundle.exists() or bundle.stat().st_mtime < (cache / "src.js").stat().st_mtime:
        esbuild = cache / "node_modules" / ".bin" / "esbuild"
        cmd = [str(esbuild)] if esbuild.exists() else ["npx", "esbuild"]
        run(cmd + ["src.js", "--bundle", "--format=iife", "--minify", "--log-level=warning", "--outfile=bundle.js"], cwd=cache)
        print(f"[render] бандл экспортёра: {bundle.stat().st_size / 1024 / 1024:.1f} MB", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description="Рендер *.excalidraw и *.html в JPEG рядом с источником")
    ap.add_argument("dir", nargs="?", default=str(DEFAULT_DIR), help=f"каталог с диаграммами (по умолчанию {DEFAULT_DIR})")
    ap.add_argument("--changed", action="store_true", help="только источники новее своего .jpg")
    ap.add_argument("--scale", type=float, default=1.0, help="масштаб экспорта (по умолчанию 1)")
    ap.add_argument("--file", action="append", default=[], help="ограничить конкретными файлами (имя внутри каталога)")
    ap.add_argument("--html-width", type=int, default=1400, help="ширина вьюпорта для HTML (по умолчанию 1400)")
    ap.add_argument("--jpeg-quality", type=int, default=90, help="качество JPEG, 1–100 (по умолчанию 90)")
    ap.add_argument("--no-html", action="store_true", help="не рендерить *.html")
    args = ap.parse_args()

    if not 1 <= args.jpeg_quality <= 100:
        sys.exit("--jpeg-quality: ожидается 1–100")

    here = Path(args.dir).resolve()
    if not here.is_dir():
        sys.exit(f"not a directory: {here}")

    if args.file:
        sources = [here / f for f in args.file]
    else:
        sources = sorted(Path(p) for p in glob.glob(str(here / "*.excalidraw")))
        if not args.no_html:
            sources += sorted(Path(p) for p in glob.glob(str(here / "*.html")))

    missing = [p for p in sources if not p.exists()]
    if missing:
        sys.exit("missing: " + ", ".join(map(str, missing)))
    if not sources:
        print(f"no .excalidraw/.html in {here}", file=sys.stderr)
        return 1

    if args.changed:
        todo = [
            p
            for p in sources
            if not p.with_suffix(".jpg").exists() or p.stat().st_mtime > p.with_suffix(".jpg").stat().st_mtime
        ]
        if not todo:
            print(f"[render] {len(sources)} источник(ов): JPEG актуальны")
            return 0
    else:
        todo = sources

    cache = REPO / ".render-cache"
    ensure_engine(cache)
    chrome = find_chrome()
    env = dict(
        os.environ,
        CHROME_PATH=chrome,
        RENDER_SCALE=str(args.scale),
        HTML_WIDTH=str(args.html_width),
        JPEG_QUALITY=str(args.jpeg_quality),
    )
    print(f"[render] {len(todo)}/{len(sources)} файл(ов), scale={args.scale:g}, q={args.jpeg_quality}, chrome={Path(chrome).name}", file=sys.stderr)
    try:
        run(["node", str(cache / "render.mjs"), *map(str, todo)], cwd=cache, env=env)
    except subprocess.CalledProcessError:
        return 1

    for p in todo:
        jpg = p.with_suffix(".jpg")
        if jpg.exists():
            print(f"[render] {jpg.name}: {jpg.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
