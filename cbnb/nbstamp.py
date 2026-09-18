"""Tie a notebook's stored outputs to the source that produced them.

``make ship`` executes a notebook and records a hash of its cell sources in the
notebook metadata. The notebook checker recomputes the hash: if the sources
changed since the last ship, the stored outputs are stale -- or the notebook
was edited by accident while someone was testing it. Either way it should not
be committed as-is.

Standard library only, so the checker runs without the notebook dependencies.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

STAMP_KEY = "cbnb"

#: Notebook-level metadata worth keeping. Anything else is editor state (VS Code
#: interpreter paths, widget state, Colab view settings) that churns diffs.
KEEP_METADATA = {"kernelspec", "language_info", STAMP_KEY}


def _source(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _without_header(source: str) -> str:
    """A cell's source minus its leading comment lines (and blank lines among them)."""
    lines = source.splitlines(keepends=True)
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    return "".join(lines[start:])


def source_hash(nb: dict[str, Any]) -> str:
    """Hash of the code cells' sources, in order.

    Only code produces outputs, so only code can make them stale. Markdown is
    left out on purpose: fixing prose to match a run should not demand a new
    run. So is each cell's leading comment -- the plain-English line saying what
    the cell does -- for the same reason. Comments further down are hashed:
    telling one apart from a line inside a string needs a parser.
    """
    payload = [
        _without_header(_source(cell))
        for cell in nb.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


def has_outputs(nb: dict[str, Any]) -> bool:
    return any(cell.get("outputs") for cell in nb.get("cells", []) if cell.get("cell_type") == "code")


#: Cells tagged this way are executed on a ship run and then emptied. For output
#: that is worth seeing live and wrong to publish -- an agent's commentary on the
#: results, which is unreviewed, changes every run, and is not one of the
#: notebook's claims. A whole-notebook flag cannot express this: notebooks that
#: commit their outputs may still hold a cell that must not be committed.
EPHEMERAL_TAG = "cbnb-ephemeral"


def is_ephemeral(cell: dict[str, Any]) -> bool:
    return EPHEMERAL_TAG in (cell.get("metadata", {}).get("tags") or [])


def clear_ephemeral(nb: dict[str, Any]) -> list[int]:
    """Empty the outputs of tagged cells. Returns the cell indices cleared."""
    cleared = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") == "code" and is_ephemeral(cell) and cell.get("outputs"):
            cell["outputs"] = []
            cell["execution_count"] = None
            cleared.append(i)
    return cleared


def ephemeral_with_outputs(nb: dict[str, Any]) -> list[int]:
    return [
        i for i, cell in enumerate(nb.get("cells", []))
        if cell.get("cell_type") == "code" and is_ephemeral(cell) and cell.get("outputs")
    ]


def declares_cleared(nb: dict[str, Any]) -> bool:
    """True when this notebook's outputs should never be committed.

    Most notebooks commit their outputs: the output *is* the argument, and
    GitHub's rendering of it is how most people read them. A few produce nothing
    generalisable -- a setup check describes the machine that ran it, down to its
    cluster address and its RAM -- and for those a stored output is noise at
    best, and someone else's configuration leaking into the repo at worst.
    """
    return (nb.get("metadata", {}).get(STAMP_KEY) or {}).get("outputs") == "cleared"


def clear_outputs(nb: dict[str, Any]) -> None:
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None


def stamp(nb: dict[str, Any], version: str = "") -> None:
    """Record that ``nb``'s outputs were produced from its current sources.

    Also strips editor metadata and per-cell execution timestamps, so a ship
    run produces the smallest diff that still captures what changed.
    """
    cleared = declares_cleared(nb)  # read before the stamp below overwrites it
    metadata = nb.setdefault("metadata", {})
    for key in list(metadata):
        if key not in KEEP_METADATA:
            del metadata[key]
    language = metadata.get("language_info")
    if isinstance(language, dict):
        metadata["language_info"] = {"name": language.get("name", "python")}

    for cell in nb.get("cells", []):
        cell_meta = cell.get("metadata", {})
        cell_meta.pop("execution", None)
        cell_meta.pop("ExecuteTime", None)

    # Before anything else: these ran, and now they go. Independent of whether
    # the notebook as a whole commits its outputs.
    clear_ephemeral(nb)

    shipped_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if cleared:
        # Nothing is stored, so nothing can go stale: no source hash to record.
        clear_outputs(nb)
        metadata[STAMP_KEY] = {"outputs": "cleared", "checked_at": shipped_at}
        return

    metadata[STAMP_KEY] = {
        "source_hash": source_hash(nb),
        "shipped_at": shipped_at,
        **({"cbnb_version": version} if version else {}),
    }


def verify(nb: dict[str, Any]) -> tuple[str, str]:
    """Classify a notebook's ship state.

    Returns ``(status, message)`` where status is one of:

    * ``"shipped"``   -- outputs match the sources.
    * ``"cleared"``   -- outputs cleared on purpose; see :func:`declares_cleared`.
    * ``"unshipped"`` -- no outputs and no stamp; fine while a notebook is in progress.
    * ``"stale"``     -- code changed since the last ship.
    * ``"unstamped"`` -- outputs exist but did not come from a ship run.
    * ``"uncleared"`` -- outputs stored in a notebook that says it stores none.
    """
    stragglers = ephemeral_with_outputs(nb)
    if stragglers:
        listed = ", ".join(str(i) for i in stragglers)
        return "uncleared", (
            f"cell {listed} is tagged {EPHEMERAL_TAG} but has stored outputs "
            "(unreviewed, run-specific output must not be committed)"
        )

    if declares_cleared(nb):
        if has_outputs(nb):
            return "uncleared", (
                "stores outputs, but its metadata says they are cleared on purpose "
                "(they describe whoever ran it last, not the technique)"
            )
        return "cleared", "outputs cleared by design"

    recorded = (nb.get("metadata", {}).get(STAMP_KEY) or {}).get("source_hash")
    if recorded:
        if recorded == source_hash(nb):
            return "shipped", "outputs match the sources"
        return "stale", "code cells changed since the last `make ship` -- outputs are stale"
    if has_outputs(nb):
        return "unstamped", "has outputs that did not come from `make ship` (interactive run saved?)"
    return "unshipped", "not shipped yet -- no stored outputs"
