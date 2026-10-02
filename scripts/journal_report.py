#!/usr/bin/env python3
"""Show every journaled run of a notebook: which claims held, and how far measures moved.

Run: python scripts/journal_report.py [notebook ...]    (no argument: every journaled notebook)

Read before rewriting prose after a re-ship. A claim that held in every run is
the notebook's to make; one marked FLAPPING is not, whatever the latest run says.
See ``cbnb/journal.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from run_notebook import resolve_notebook  # noqa: E402

from cbnb import journal  # noqa: E402 - needs ROOT on sys.path


def main(argv: list[str]) -> int:
    names = [journal.name_of(resolve_notebook(a)) for a in argv[1:]] or journal.journaled()
    if not names:
        print("Nothing journaled yet. Entries come from `make ship` and `make trial`.")
    for name in names:
        print(journal.summary(name))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
