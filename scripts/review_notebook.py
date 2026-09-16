#!/usr/bin/env python3
"""Ask a model which of a notebook's claims its stored outputs no longer support.

Run: python scripts/review_notebook.py 01

Advisory. It reports to you, never to the reader, never edits the notebook, and
exits 0 whatever it finds -- including when no model is configured. See
``cbnb/review.py`` for why it is deliberately toothless.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A batch tool: report a missing credential, never stop and ask for one.
os.environ.setdefault("CBNB_NONINTERACTIVE", "1")

from cbnb.review import check_claims  # noqa: E402 - needs ROOT on sys.path


def resolve(name: str) -> Path | None:
    """Accept a notebook prefix ("01"), a stem, or a path."""
    candidate = Path(name)
    if candidate.exists():
        return candidate
    matches = sorted(ROOT.glob(f"notebooks/**/{name}*.ipynb"))
    if len(matches) > 1:
        listed = ", ".join(str(m.relative_to(ROOT / "notebooks")) for m in matches)
        print(f"{name!r} matches more than one notebook: {listed}")
        return None
    return matches[0] if matches else None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 0
    for name in argv[1:]:
        path = resolve(name)
        if path is None:
            print(f"No notebook matching {name!r}")
            continue
        try:
            label = path.resolve().relative_to(ROOT)
        except ValueError:
            label = path  # a notebook from outside the repo, e.g. a test fixture
        print(f"--- {label} ---")
        print(check_claims(path))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
