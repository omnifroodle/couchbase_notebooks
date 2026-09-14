#!/usr/bin/env python3
"""Pre-commit sanity checks for the notebooks.

Run: python scripts/check_notebooks.py [notebook ...]

Checks that every notebook is valid, starts with the shared bootstrap cell, and
has no credential-shaped string in a stored output. Notebook outputs are
committed on purpose -- GitHub renders them, and that rendering is how most
people read these -- which makes a leaked key a real risk.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "OpenAI-style API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "Groq API key"),
    (re.compile(r"couchbases?://[^\s\"']*:[^\s\"'@]+@"), "credentials in a connection string"),
    (re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*[\"'][^\"']{6,}"), "inline password"),
]

BOOTSTRAP_MARKERS = ["import cbnb", "cbnb.bootstrap("]


def check(path: Path) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for one notebook."""
    problems: list[str] = []
    warnings: list[str] = []
    try:
        nb = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    cells = nb.get("cells", [])
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    if not code_cells:
        problems.append("no code cells")
    else:
        first = "".join(code_cells[0].get("source", []))
        for marker in BOOTSTRAP_MARKERS:
            if marker not in first:
                problems.append(f"first code cell is missing {marker!r} (see docs/adding-a-notebook.md)")

    for i, cell in enumerate(cells):
        haystacks = ["".join(cell.get("source", []))]
        for output in cell.get("outputs", []):
            haystacks.append("".join(output.get("text", [])))
            for value in (output.get("data") or {}).values():
                haystacks.append("".join(value) if isinstance(value, list) else str(value))
        for text in haystacks:
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(text):
                    problems.append(f"cell {i}: possible {label}")

    if "OWNER/REPO" in path.read_text():
        warnings.append(
            "placeholder OWNER/REPO in REPO_URL and/or the Colab badge — "
            "replace before publishing, or Colab cannot clone the repo"
        )

    return problems, warnings


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv[1:]] or sorted((ROOT / "notebooks").glob("*.ipynb"))
    if not paths:
        print("No notebooks found.")
        return 0

    failed = 0
    for path in paths:
        problems, warnings = check(path)
        status = "FAIL" if problems else "ok  "
        failed += bool(problems)
        print(f"{status} {path.relative_to(ROOT)}")
        for problem in problems:
            print(f"     ! {problem}")
        for warning in warnings:
            print(f"     ~ {warning}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
