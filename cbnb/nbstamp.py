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


def source_hash(nb: dict[str, Any]) -> str:
    """Hash of every cell's type and source. Outputs and metadata are ignored."""
    payload = [(cell.get("cell_type"), _source(cell)) for cell in nb.get("cells", [])]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


def has_outputs(nb: dict[str, Any]) -> bool:
    return any(cell.get("outputs") for cell in nb.get("cells", []) if cell.get("cell_type") == "code")


def stamp(nb: dict[str, Any], version: str = "") -> None:
    """Record that ``nb``'s outputs were produced from its current sources.

    Also strips editor metadata and per-cell execution timestamps, so a ship
    run produces the smallest diff that still captures what changed.
    """
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

    metadata[STAMP_KEY] = {
        "source_hash": source_hash(nb),
        "shipped_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        **({"cbnb_version": version} if version else {}),
    }


def verify(nb: dict[str, Any]) -> tuple[str, str]:
    """Classify a notebook's ship state.

    Returns ``(status, message)`` where status is one of:

    * ``"shipped"``   -- outputs match the sources.
    * ``"unshipped"`` -- no outputs and no stamp; fine while a notebook is in progress.
    * ``"stale"``     -- sources changed since the last ship.
    * ``"unstamped"`` -- outputs exist but did not come from a ship run.
    """
    recorded = (nb.get("metadata", {}).get(STAMP_KEY) or {}).get("source_hash")
    if recorded:
        if recorded == source_hash(nb):
            return "shipped", "outputs match the sources"
        return "stale", "cell sources changed since the last `make ship` -- outputs are stale"
    if has_outputs(nb):
        return "unstamped", "has outputs that did not come from `make ship` (interactive run saved?)"
    return "unshipped", "not shipped yet -- no stored outputs"
