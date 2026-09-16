"""What does each notebook in this repo ask for?

Reads the notebooks as *files* -- never imports them, never executes them. A
notebook declares its requirements in two places, for two audiences:

* ``cbnb.bootstrap(requires=[...])`` in the setup cell, which is what actually
  runs and what stops the notebook early when something is missing;
* a ``**Requires.**`` line in the title cell, which is what a reader sees on
  GitHub without running anything.

``scripts/check_notebooks.py`` holds them to agreeing. This module prefers the
executable declaration and falls back to the header, so a notebook that has only
been given the header line still shows up correctly.

This module knows nothing about what any capability *means* -- that is
:mod:`cbnb.readiness`, which in turn knows nothing about notebooks. The two meet
in ``00_check_setup`` and nowhere else.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Lab", "labs", "read_lab"]

_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TAGLINE = re.compile(r"^\*(.+?)\*\s*$", re.MULTILINE | re.DOTALL)
_REQUIRES_LINE = re.compile(r"^\*\*Requires\.\*\*\s*(.+?)\s*$", re.MULTILINE)
_SEPARATORS = re.compile(r"[·,]")


@dataclass(frozen=True)
class Lab:
    """One notebook, as described by its own contents."""

    path: Path
    title: str
    tagline: str
    requires: tuple[str, ...]
    #: "bootstrap", "header", or "" when the notebook declares nothing.
    declared_in: str
    #: Set only when both declarations exist and disagree.
    header_requires: tuple[str, ...] = ()
    bootstrap_requires: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """Filename without the extension, e.g. ``01_hypothetical_classification``."""
        return self.path.stem

    @property
    def track(self) -> str:
        """Directory under ``notebooks/``, or "" for an unfiled notebook."""
        parent = self.path.parent.name
        return "" if parent == "notebooks" else parent

    @property
    def drifted(self) -> bool:
        """True when both declarations exist and list different things."""
        return bool(
            self.header_requires
            and self.bootstrap_requires
            and set(self.header_requires) != set(self.bootstrap_requires)
        )


def _split(text: str) -> tuple[str, ...]:
    parts = (p.strip().strip("`") for p in _SEPARATORS.split(text))
    return tuple(p for p in parts if p and p.lower() != "nothing")


def _bootstrap_requires(source: str) -> tuple[str, ...] | None:
    """The ``requires=[...]`` argument of the bootstrap call, if there is one.

    Returns None when there is no such argument to read -- no bootstrap call, no
    ``requires`` keyword, or a cell that will not parse. That is different from
    an explicit ``requires=[]``, which is a notebook declaring that it needs
    nothing and comes back as an empty tuple.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        named = getattr(func, "attr", None) or getattr(func, "id", None)
        if named != "bootstrap":
            continue
        for keyword in node.keywords:
            if keyword.arg == "requires":
                try:
                    value = ast.literal_eval(keyword.value)
                except ValueError:
                    return None
                return tuple(str(v) for v in value)
        return None
    return None


def read_lab(path: Path) -> Lab | None:
    """Describe one notebook. Returns None if it is not readable as one."""
    try:
        nb = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    cells = nb.get("cells", [])

    title, tagline, header = "", "", ()
    for cell in cells:
        if cell.get("cell_type") != "markdown":
            continue
        text = "".join(cell.get("source", []))
        if not title:
            match = _TITLE.search(text)
            if match:
                title = match.group(1)
                tag = _TAGLINE.search(text)
                tagline = " ".join(tag.group(1).split()) if tag else ""
        match = _REQUIRES_LINE.search(text)
        if match:
            header = _split(match.group(1))
            break

    from_bootstrap = None
    for cell in cells:
        if cell.get("cell_type") == "code":
            from_bootstrap = _bootstrap_requires("".join(cell.get("source", [])))
            break

    if from_bootstrap is not None:
        requires, declared_in = from_bootstrap, "bootstrap"
    elif header:
        requires, declared_in = header, "header"
    else:
        requires, declared_in = (), ""

    return Lab(
        path=Path(path),
        title=title or Path(path).stem,
        tagline=tagline,
        requires=requires,
        declared_in=declared_in,
        header_requires=header,
        bootstrap_requires=from_bootstrap or (),
    )


def labs(root: Path | None = None) -> list[Lab]:
    """Every notebook in the repo, sorted by path.

    Searches ``notebooks/`` recursively, so notebooks filed under a track
    directory are found without this module knowing the track names.
    """
    if root is None:
        from cbnb.bootstrap import repo_root

        root = repo_root()
    if root is None:
        return []
    found = []
    for path in sorted(Path(root).glob("notebooks/**/*.ipynb")):
        if ".ipynb_checkpoints" in path.parts:
            continue
        lab = read_lab(path)
        if lab is not None:
            found.append(lab)
    return found
