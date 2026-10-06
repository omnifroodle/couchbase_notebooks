#!/usr/bin/env python3
"""Execute a notebook top to bottom, headless, the way a reader would.

    python scripts/run_notebook.py notebooks/enrich/01_hypothetical_classification.ipynb
    python scripts/run_notebook.py 01 --stop-before "from cbnb.llm import"
    python scripts/run_notebook.py 01 --inplace      # store outputs for GitHub

By default the executed copy goes to ``build/`` (gitignored) so a test run never
touches the committed notebook. ``--inplace`` is the "ship it" run: outputs are
written back into the notebook so GitHub renders them, and the notebook is
stamped with a hash of its sources (see ``cbnb/nbstamp.py``). A failed
``--inplace`` run never writes to the notebook.

Every full run without the LLM cache -- a ship, or a trial (``make trial``) --
also leaves an entry in ``journal/`` (see ``cbnb/journal.py``): the models that
answered, and what the notebook declared worth measuring. One run is not a
result; the journal is how the next one is compared with it.

Runs from ``.env``, never prompts, and stops at the first failing cell with its
source and traceback.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def resolve_notebook(arg: str) -> Path:
    """Accept a path, or just a prefix like ``01``."""
    path = Path(arg)
    if path.exists():
        return path.resolve()
    matches = sorted(ROOT.glob(f"notebooks/**/{arg}*.ipynb"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"No notebook matches {arg!r}")
    listed = "\n  ".join(str(m.relative_to(ROOT / "notebooks")).removesuffix(".ipynb")
                         for m in matches)
    sys.exit(f"{arg!r} matches more than one notebook. Use one of:\n  {listed}")


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


def git_state() -> dict[str, object]:
    """The commit a run came from, and whether the tree had uncommitted changes."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    dirty = [ln for ln in git("status", "--porcelain").splitlines() if not ln[3:].startswith("journal/")]
    return {"commit": git("rev-parse", "--short", "HEAD"), "dirty": bool(dirty)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("notebook", help="path, or a prefix such as 01")
    parser.add_argument("--inplace", action="store_true", help="write outputs back into the notebook")
    parser.add_argument("--stop-before", metavar="REGEX",
                        help="run only the cells before the first code cell matching REGEX")
    parser.add_argument("--timeout", type=int, default=None,
                        help="per-cell timeout in seconds (default: the notebook's "
                             "metadata.cbnb.cell_timeout, else 900)")
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

    # Cached answers repeat an earlier run, so only an uncached full run is a
    # new sample worth journaling. A notebook that stores no outputs measures
    # nothing.
    from cbnb import journal
    from cbnb.nbstamp import declares_cleared, source_hash

    journaling = args.no_cache and not args.stop_before and not declares_cleared(nb)
    entry: dict[str, object] = {}
    if journaling:
        measures, claims = journal.declared(nb)
        entry = {"run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "kind": "ship" if args.inplace else "trial", **git_state(),
                 "source_hash": source_hash(nb)}
        nb.cells.append(nbformat.v4.new_code_cell(journal.probe_source(measures, claims)))
    print(f"Running {path.relative_to(ROOT)} ({n_code} code cells) -> {out.relative_to(ROOT)}")

    client = NotebookClient(
        nb,
        timeout=args.timeout or (nb.metadata.get("cbnb", {}).get("cell_timeout") or 900),
        kernel_name="python3",
        resources={"metadata": {"path": str(path.parent)}},
    )

    started = time.perf_counter()
    code_index = 0
    failed_cell = None

    def on_cell_executed(cell, cell_index, execute_reply, **_):
        nonlocal code_index, failed_cell
        if cell.cell_type != "code" or code_index == n_code:  # the journal's probe
            return
        code_index += 1
        if execute_reply["content"]["status"] != "ok":
            failed_cell = code_index
        first = next((ln for ln in cell.source.splitlines() if ln.strip() and not ln.startswith("#")), "")
        status = execute_reply["content"]["status"]
        mark = "ok " if status == "ok" else "ERR"
        print(f"  [{mark}] {code_index:2d}/{n_code}  {time.perf_counter() - started:6.1f}s  {first[:70]}")

    client.on_cell_executed = on_cell_executed

    def finish_journal(status: str) -> None:
        """Take the probe back out of the notebook, and keep what it found."""
        if not journaling:
            return
        probe = nb.cells.pop()
        import cbnb

        entry.update(status=status, seconds=round(time.perf_counter() - started),
                     cbnb_version=cbnb.__version__)
        if status == "ok":
            found = journal.parse_probe(probe.get("outputs", []))
            entry.update(found or {"errors": {"journal": "the probe cell printed nothing"}})
        else:
            entry["failed_cell"] = failed_cell
        written = journal.write(path, entry)
        print(f"Journal: {written.relative_to(ROOT)}")
        for name, error in (entry.get("errors") or {}).items():
            print(f"  could not evaluate {name!r}: {error}")

    try:
        client.execute()
    except CellExecutionError as exc:
        finish_journal("failed")
        # Always to build/, even with --inplace: a half-run notebook is exactly
        # the accidental edit we do not want in the committed file.
        nbformat.write(nb, build_copy)
        print(f"\nFailed. Partial output saved to {build_copy.relative_to(ROOT)}"
              f"{' (the notebook itself was not modified)' if args.inplace else ''}\n")
        message = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))  # IPython colours the traceback
        lines = [ln for ln in message.splitlines() if ln.strip()]
        print("\n".join(lines[-25:]))
        return 1

    finish_journal("ok")
    if args.inplace:
        import cbnb
        from cbnb.nbstamp import stamp

        changes = stamp(nb, version=cbnb.__version__)
    else:
        changes = []
    nbformat.write(nb, out)
    print(f"\nDone in {time.perf_counter() - started:.0f}s -> {out.relative_to(ROOT)}")
    if changes:
        # Advisory, never a failure: re-shipping on a new model is legitimate.
        print("\nWarning: the models behind these results changed since the last ship.")
        print("\n".join(f"  {line}" for line in changes))
        print("  Prose citing specific results may no longer hold. Run `make review NB=...`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
