#!/usr/bin/env python3
"""Pre-commit sanity checks for the notebooks.

Run: python scripts/check_notebooks.py [notebook ...]

Checks that every notebook is valid, starts with the shared bootstrap cell, has
no credential-shaped string, cluster hostname or .env secret anywhere in it, and that any stored outputs
came from a `make ship` run of the current sources. Notebook outputs are
committed on purpose -- GitHub renders them, and that rendering is how most
people read these -- which makes a leaked key a real risk.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cbnb.inventory import read_lab  # noqa: E402 - needs ROOT on sys.path
from cbnb.nbstamp import is_ephemeral, verify  # noqa: E402

SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "OpenAI-style API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key"),
    (re.compile(r"gsk_[A-Za-z0-9]{20,}"), "Groq API key"),
    (re.compile(r"couchbases?://[^\s\"']*:[^\s\"'@]+@"), "credentials in a connection string"),
    (re.compile(r"(?i)\b(password|passwd|secret)\s*[:=]\s*[\"'][^\"']{6,}"), "inline password"),
]

BOOTSTRAP_MARKERS = ["import cbnb", "cbnb.bootstrap("]

# A Capella hostname identifies a specific cluster. Placeholders used in the
# docs (cb.xxxxxxxx..., cb.abc123...) and masked output (cb.***...) are fine.
CAPELLA_HOST = re.compile(r"\b[a-z0-9-]+\.([a-z0-9]+)\.cloud\.couchbase\.com", re.IGNORECASE)
PLACEHOLDER_CLUSTER_IDS = {"abc123", "xxxxxxxx"}


def local_secret_values() -> list[tuple[str, str]]:
    """Values from this checkout's .env that must never appear in a notebook.

    Catches leaks no pattern would: an unusual key format, a cluster that
    isn't on Capella. Only works where .env exists -- locally, not in CI.
    """
    env_path = ROOT / ".env"
    if not env_path.exists():
        return []
    values = []
    for line in env_path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if not sep or key.startswith("#") or len(value) < 8:
            continue
        if key.endswith(("PASSWORD", "API_KEY", "SECRET", "TOKEN")):
            values.append((key, value))
        elif key == "CB_CONNECTION_STRING":
            host = value.split("//")[-1].split("?")[0].split(",")[0].split(":")[0]
            values.append((key + " host", host))
    return values


def _unknown_capabilities(names: tuple[str, ...]) -> list[str]:
    """Names that no probe in cbnb.readiness knows how to check."""
    from cbnb.readiness import CAPABILITIES

    return [name for name in names if name not in CAPABILITIES]


def check(path: Path) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for one notebook."""
    problems: list[str] = []
    warnings: list[str] = []
    try:
        nb = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]

    cells = nb.get("cells", [])
    secrets = local_secret_values()
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    if not code_cells:
        problems.append("no code cells")
    else:
        first = "".join(code_cells[0].get("source", []))
        for marker in BOOTSTRAP_MARKERS:
            if marker not in first:
                problems.append(f"first code cell is missing {marker!r} (see docs/adding-a-notebook.md)")
        # Its output names the runner's environment, cluster and model -- never the lesson.
        if not is_ephemeral(code_cells[0]):
            problems.append(
                "setup cell is not tagged cbnb-ephemeral (its output describes whoever ran it; "
                "see CLAUDE.md)"
            )

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
            for match in CAPELLA_HOST.finditer(text):
                cluster_id = match.group(1).lower()
                if cluster_id not in PLACEHOLDER_CLUSTER_IDS and set(cluster_id) != {"x"}:
                    problems.append(f"cell {i}: Capella cluster hostname (mask it; see cbnb.config.mask_host)")
            for key, value in secrets:
                if value in text:
                    problems.append(f"cell {i}: contains the value of {key} from .env")

    status, message = verify(nb)
    if status in {"stale", "unstamped", "uncleared"}:
        problems.append(f"{message}. Run `make ship`, or `git restore {path.relative_to(ROOT)}`")
    elif status == "unshipped":
        warnings.append(message)

    # Requirements are declared twice, for a reader and for the runtime. They
    # are only useful to 00_check_setup while they agree.
    lab = read_lab(path)
    if lab is None:
        problems.append("could not be read as a notebook")
    elif lab.drifted:
        problems.append(
            f"declared requirements disagree: setup cell says "
            f"{', '.join(lab.bootstrap_requires) or 'nothing'}, the **Requires.** line says "
            f"{', '.join(lab.header_requires) or 'nothing'}"
        )
    elif not lab.declared_in:
        warnings.append(
            "declares no requirements — add bootstrap(requires=[...]) and a **Requires.** "
            "line, or 00_check_setup cannot tell readers whether they can run it"
        )
    elif lab.declared_in == "header":
        warnings.append(
            "requirements are only in the **Requires.** line; add "
            f"bootstrap(requires={list(lab.header_requires)}) at the next `make ship`"
        )
    else:
        unknown = _unknown_capabilities(lab.requires)
        if unknown:
            problems.append(f"unknown capability {unknown[0]!r} in bootstrap(requires=...)")

    if "OWNER/REPO" in path.read_text():
        warnings.append(
            "placeholder OWNER/REPO in REPO_URL and/or the Colab badge — "
            "replace before publishing, or Colab cannot clone the repo"
        )

    return problems, warnings


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv[1:]] or [
        p for p in sorted(ROOT.glob("notebooks/**/*.ipynb"))
        if ".ipynb_checkpoints" not in p.parts
    ]
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
