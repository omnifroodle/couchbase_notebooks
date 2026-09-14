#!/usr/bin/env python3
"""Execute a notebook top to bottom, headless, the way a reader would.

    python scripts/run_notebook.py notebooks/01_hypothetical_classification.ipynb
    python scripts/run_notebook.py 01 --stop-before "from cbnb.llm import"
    python scripts/run_notebook.py 01 --inplace      # store outputs for GitHub

By default the executed copy goes to ``build/`` (gitignored) so a test run never
touches the committed notebook. ``--inplace`` is the "ship it" run: outputs are
written back into the notebook so GitHub renders them, and the notebook is
stamped with a hash of its sources (see ``cbnb/nbstamp.py``). A failed
``--inplace`` run never writes to the notebook.

Runs from ``.env``, never prompts, and stops at the first failing cell with its
source and traceback.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def resolve_notebook(arg: str) -> Path:
    """Accept a path, or just a prefix like ``01``."""
    path = Path(arg)
    if path.exists():
        return path.resolve()
    matches = sorted((ROOT / "notebooks").glob(f"{arg}*.ipynb"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"No notebook matches {arg!r}")
    sys.exit(f"{arg!r} is ambiguous: " + ", ".join(m.name for m in matches))


def preflight() -> list[str]:
    """Settings a notebook will need, checked before spending minutes running it."""
    from cbnb.config import load_settings
    from cbnb.llm import PROVIDERS

    cfg = load_settings()
    missing = [
        name
        for name, value in [
            ("CB_CONNECTION_STRING", cfg.cb_connection_string),
            ("CB_USERNAME", cfg.cb_username),
            ("CB_PASSWORD", cfg.cb_password),
        ]
        if not value
    ]
    provider = PROVIDERS[cfg.llm_provider]
    if provider.key_env and provider.key_required and not cfg.llm_api_key:
        missing.append(provider.key_env)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notebook", help="path, or a prefix such as 01")
    parser.add_argument("--inplace", action="store_true", help="write outputs back into the notebook")
    parser.add_argument("--stop-before", metavar="REGEX",
                        help="run only the cells before the first code cell matching REGEX")
    parser.add_argument("--timeout", type=int, default=900, help="per-cell timeout in seconds")
    parser.add_argument("--no-cache", action="store_true", help="disable the LLM response cache")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args()

    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    path = resolve_notebook(args.notebook)
    nb = nbformat.read(path, as_version=4)

    if args.stop_before:
        pattern = re.compile(args.stop_before)
        cut = next((i for i, c in enumerate(nb.cells)
                    if c.cell_type == "code" and pattern.search(c.source)), None)
        if cut is None:
            sys.exit(f"No code cell matches {args.stop_before!r}")
        nb.cells = nb.cells[:cut]
        if args.inplace:
            sys.exit("--inplace with --stop-before would delete cells from the notebook")

    if not args.skip_preflight and not args.stop_before:
        missing = preflight()
        if missing:
            print("Missing settings (add them to .env):", ", ".join(missing))
            print("Use --stop-before to run just the part that does not need them.")
            return 2

    os.environ["CBNB_NONINTERACTIVE"] = "1"
    os.environ.setdefault("TQDM_DISABLE", "1")  # progress bars render badly on GitHub
    if args.no_cache:
        os.environ["CBNB_LLM_CACHE"] = "0"

    build_copy = ROOT / "build" / path.name
    build_copy.parent.mkdir(exist_ok=True)
    out = path if args.inplace else build_copy

    n_code = sum(c.cell_type == "code" for c in nb.cells)
    print(f"Running {path.relative_to(ROOT)} ({n_code} code cells) -> {out.relative_to(ROOT)}")

    client = NotebookClient(
        nb,
        timeout=args.timeout,
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    )

    started = time.perf_counter()
    code_index = 0

    def on_cell_executed(cell, cell_index, execute_reply, **_):
        nonlocal code_index
        if cell.cell_type != "code":
            return
        code_index += 1
        first = next((ln for ln in cell.source.splitlines() if ln.strip() and not ln.startswith("#")), "")
        status = execute_reply["content"]["status"]
        mark = "ok " if status == "ok" else "ERR"
        print(f"  [{mark}] {code_index:2d}/{n_code}  {time.perf_counter() - started:6.1f}s  {first[:70]}")

    client.on_cell_executed = on_cell_executed

    try:
        client.execute()
    except CellExecutionError as exc:
        # Always to build/, even with --inplace: a half-run notebook is exactly
        # the accidental edit we do not want in the committed file.
        nbformat.write(nb, build_copy)
        print(f"\nFailed. Partial output saved to {build_copy.relative_to(ROOT)}"
              f"{' (the notebook itself was not modified)' if args.inplace else ''}\n")
        message = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))  # IPython colours the traceback
        lines = [ln for ln in message.splitlines() if ln.strip()]
        print("\n".join(lines[-25:]))
        return 1

    if args.inplace:
        import cbnb
        from cbnb.nbstamp import stamp

        stamp(nb, version=cbnb.__version__)
    nbformat.write(nb, out)
    print(f"\nDone in {time.perf_counter() - started:.0f}s -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
