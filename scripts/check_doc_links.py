#!/usr/bin/env python3
"""check_doc_links.py — проверка относительных ссылок между документами репозитория.

Ищет в *.md два вида ссылок на другие документы:
  [текст](путь.md)  и  `путь.md` (в бэктиках).
Путь считается валидным, если файл есть относительно каталога документа или корня репозитория
(в доках стенда встречаются оба стиля). Внешние URL, якоря, шаблоны и плановые документы
(ALLOW_MISSING) пропускаются.

Использование:
    python3 scripts/check_doc_links.py             # весь репозиторий
    python3 scripts/check_doc_links.py README.md   # только указанные файлы

Коды выхода: 0 — битых ссылок нет, 1 — есть.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Каталоги вне обслуживания: архив и справочники, которые по AGENTS.md не читаем/не правим,
# и служебные каталоги инструментов.
EXCLUDE_DIRS = {".git", ".render-cache", ".deepeval", "node_modules", "old", "beellama-rtx5060"}

# Документы, на которые ссылаются осознанно, хотя файла ещё/уже нет.
ALLOW_MISSING = {
    "architecture/specs/guardrail-spec.md",  # спека не написана (ADR-0006, gpustack R-G12)
}

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
CODE_LINK = re.compile(r"`([^`\n]+?\.md(?:#[^`\s]*)?)`")
SKIP_PREFIX = ("http://", "https://", "mailto:", "tel:", "#", "/")
SKIP_CHARS = set("*…<>{}| ")


def md_files(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) if Path(a).is_absolute() else REPO_ROOT / a for a in argv]
    out = []
    for p in REPO_ROOT.rglob("*.md"):
        if p.name.endswith(".local.md"):
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(REPO_ROOT).parts):
            continue
        out.append(p)
    return sorted(out)


def targets(line: str) -> list[str]:
    found = [m.group(1) for m in MD_LINK.finditer(line)]
    found += [m.group(1) for m in CODE_LINK.finditer(line)]
    return found


def valid(path: Path, target: str) -> bool:
    target = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not target or target.startswith(SKIP_PREFIX) or any(c in SKIP_CHARS for c in target):
        return True
    if target.endswith("/"):
        return True
    if target in ALLOW_MISSING:
        return True
    candidates = [path.parent / target, REPO_ROOT / target]
    return any(c.exists() for c in candidates)


def main() -> int:
    files = md_files(sys.argv[1:])
    bad = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            print(f"{path}: не прочитать ({e})", file=sys.stderr)
            bad += 1
            continue
        rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
        for no, line in enumerate(lines, 1):
            for target in targets(line):
                if not valid(path, target):
                    print(f"{rel}:{no}: нет файла: {target}")
                    bad += 1
    print(f"проверено файлов: {len(files)}, битых ссылок: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
