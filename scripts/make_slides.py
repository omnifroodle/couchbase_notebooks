#!/usr/bin/env python3
"""Turn a notebook into a Marp slide deck that walks through it.

    python scripts/make_slides.py retrieval/03
    make slides NB=retrieval/03
    make slides NB=all          # every notebook, plus the index page

Writes ``build/slides/<track>/<name>.md`` (and any charts beside it). Open it in
VS Code with the Marp extension, or ``npx @marp-team/marp-cli`` it to HTML/PDF.
``all`` builds every notebook and an ``index.html`` linking the rendered decks,
which is what ``.github/workflows/slides.yml`` publishes to GitHub Pages.

Standard library only, so CI can build the decks from the committed notebooks
without installing this package, reaching a cluster, or holding a credential.

**What goes on a slide is decided by a plan**, ``slides/<track>/<name>.yml``,
written by ``make review-slides`` and then edited and committed by a person. Per
section it says whether the section is setup (dropped), its main idea, which of
its paragraphs reach the slide, which code is shown and which is summarised to
its one-line comment, and which output is the evidence. The deck it produces:

* **Title slide** -- the header's title, subtitle, Claim, Result and badges.
* **Summary slide** -- the plan's overview of the deck, for an audience who has
  not read the notebook.
* **One slide per section** -- heading, main idea, the chosen paragraphs, and
  either the chosen code beside them or a line per code cell saying what it does.
  Code too long for one slide continues on slides of its own, split where a new
  top-level statement starts, rather than being cut.
* **A result slide** -- the section's evidence, its caption, and the bold
  lead-ins of the prose underneath it.
* **"Where to take this"** -- the bullets' bold lead-ins.

Without a plan the deck is built by rule alone: first paragraph, a line per code
cell, the last table or chart in the section. That keeps a new notebook
presentable the day it lands, and the warning says how to do better.

The rest of each section's prose goes into speaker notes. Setup and clean-up
cells are left out. Stored outputs are used as they are; nothing is re-run. No
model writes anything here: a slide's words come from the notebook, or from a
plan a person has read and committed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_notebook import resolve_notebook  # noqa: E402

#: Reading order on the index page, matching the README. Anything else sorts after.
TRACK_ORDER = ["", "retrieval", "flows", "enrich", "data-model", "experiments"]

#: Committed, hand-editable, one per notebook. See ``scripts/review_slides.py``.
PLAN_DIR = ROOT / "slides"

#: A code cell shown on a slide has to fit beside the prose. Long lines wrap, and
#: too many of them continue on the next slide: cutting code would put something
#: on a slide that does not do what it says. Counted in wrapped lines, since a
#: 90-character line takes two of them in a half-width column.
MAX_CODE_LINES = 14
CODE_COLS = 52

#: A section slide holds about this much prose before it runs off the bottom --
#: roughly half that when code takes the other column.
MAX_SLIDE_WORDS = 110
MAX_COLUMN_WORDS = 55

#: Past this much on one slide, the slide is set in smaller type.
DENSE_WORDS = 85

MAX_TABLE_ROWS = 8
MAX_LEAD_WORDS = 55
MAX_CELL_CHARS = 60

FRONT_MATTER = """---
marp: true
theme: default
paginate: true
size: 16:9
footer: "{footer}"
style: |
  section {{ font-size: 26px; }}
  section.lead h1 {{ font-size: 52px; }}
  table {{ font-size: 18px; }}
  th, td {{ padding: 4px 10px !important; }}
  section.dense {{ font-size: 22px; }}
  section.dense table {{ font-size: 14px; }}
  section.dense pre {{ font-size: 12px; line-height: 1.3; }}
  section.dense th, section.dense td {{ padding: 2px 8px !important; }}
  blockquote {{ font-size: 22px; }}
  .steps {{ font-size: 20px; color: #555; }}
  .more {{ font-size: 16px; color: #888; }}
  .badges img {{ height: 28px; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; align-items: start; }}
  .cols pre {{ font-size: 13px; line-height: 1.35; }}
  .cols pre code {{ white-space: pre-wrap; }}
  .cols p {{ margin-top: 0; }}
  footer {{ font-size: 13px; color: #999; }}
  footer a {{ color: #999; }}
  section.lead footer {{ display: none; }}
---
"""

INDEX_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Couchbase demo notebooks — slides</title>
<style>
  :root {{ color-scheme: light dark; --fg: #111; --dim: #666; --bg: #fff; --line: #e2e2e2; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg: #eee; --dim: #aaa; --bg: #16181c; --line: #333; }}
  }}
  body {{ background: var(--bg); color: var(--fg); margin: 0 auto; max-width: 46rem;
         padding: 3rem 1rem 5rem; line-height: 1.5;
         font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif; }}
  h1 {{ margin-bottom: .2rem; }}
  h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: .08em; color: var(--dim);
       border-bottom: 1px solid var(--line); padding-bottom: .4rem; margin-top: 2.5rem; }}
  h3 {{ margin: 1.6rem 0 .2rem; font-size: 1.15rem; }}
  a {{ color: inherit; }}
  a.pdf {{ font-size: .7rem; letter-spacing: .05em; color: var(--dim); text-decoration: none;
          border: 1px solid var(--line); border-radius: 3px; padding: .1rem .35rem;
          vertical-align: middle; }}
  p {{ margin: .2rem 0; }}
  .sub {{ color: var(--dim); font-style: italic; }}
  .result {{ font-size: .92rem; }}
  .lede {{ color: var(--dim); }}
</style></head>
<body>
<h1>Couchbase demo notebooks</h1>
<p class="lede">One deck per notebook, built from the notebook's own prose and its stored
outputs. Press <kbd>p</kbd> in a deck for the presenter view with speaker notes,
<kbd>o</kbd> for an overview of the slides.
<a href="https://github.com/omnifroodle/couchbase_notebooks">The notebooks themselves are on
GitHub</a>, where they can be read or run.</p>
{sections}
</body></html>
"""


# --- reading the notebook ----------------------------------------------------

def _source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _comment(cell: dict) -> str:
    """A code cell's opening plain-English comment, without the '# '."""
    first = next((line for line in _source(cell).splitlines() if line.strip()), "")
    return first.lstrip("# ").strip() if first.lstrip().startswith("#") else ""


def _is_setup_or_cleanup(cell: dict) -> bool:
    comment = _comment(cell).lower()
    return comment.startswith(("setup:", "optional clean-up"))


def _sections(cells: list[dict]) -> tuple[dict, list[dict]]:
    """Split the notebook at each '## ' heading, including one partway through a cell.

    Returns (header cell, sections).
    """
    header, sections, current = cells[0], [], None
    for index, cell in enumerate(cells):
        if index == 0:
            continue
        cell = {**cell, "index": index}
        if cell["cell_type"] == "code":
            if current is not None and not _is_setup_or_cleanup(cell):
                current["cells"].append(cell)
            continue
        for i, chunk in enumerate(re.split(r"^(?=## )", _source(cell), flags=re.M)):
            match = re.match(r"## (.+)", chunk)
            if match and (i > 0 or chunk.startswith("## ")):
                current = {"title": match.group(1).strip(), "cells": []}
                sections.append(current)
                chunk = chunk[match.end():]
            if chunk.strip() and current is not None:
                current["cells"].append({**cell, "source": chunk.strip()})
    return header, sections


def section_paragraphs(section: dict) -> list[str]:
    """The section's prose paragraphs, numbered as a plan refers to them.

    The whole section, not just the part before its evidence: a plan is written
    before the generator knows where that split falls.
    """
    prose = "\n\n".join(_source(c) for c in section["cells"] if c["cell_type"] == "markdown")
    return _paragraphs(prose)


def section_hash(section: dict) -> str:
    """Identifies what a plan entry was written against, so a later review can
    tell which sections changed and leave the author's edits to the rest alone."""
    payload = [section["title"], *(_source(c) for c in section["cells"])]
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()[:12]


def load_plan(path: Path) -> tuple[dict, str]:
    """(plan, warning) for one notebook. An absent or unreadable plan is not fatal."""
    plan_path = plan_path_for(path)
    if not plan_path.exists():
        return {}, (f"no plan at {plan_path.relative_to(ROOT)} -- built by rule; "
                    f"`make review-slides NB={path.stem}` writes one")
    try:
        import yaml
    except ImportError:
        return {}, "PyYAML is not installed, so the plan was ignored (pip install pyyaml)"
    try:
        return yaml.safe_load(plan_path.read_text()) or {}, ""
    except Exception as exc:  # noqa: BLE001 - a broken plan must not stop a deck
        return {}, f"{plan_path.relative_to(ROOT)} could not be read ({exc}); built by rule"


def plan_path_for(notebook: Path) -> Path:
    return PLAN_DIR / notebook.parent.relative_to(ROOT / "notebooks") / f"{notebook.stem}.yml"


# --- prose -------------------------------------------------------------------

def _paragraphs(text: str) -> list[str]:
    """Prose paragraphs, skipping tables, code fences and sub-headings."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith(("|", "#", "<")):
            continue
        out.append(block)
    return out


def _sentences(text: str, max_words: int) -> str:
    """Whole sentences from the start of ``text``, up to about ``max_words``."""
    flat = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z*`(\"'_])", flat)
    kept, words = [], 0
    for part in parts:
        n = len(part.split())
        if kept and words + n > max_words:
            break
        kept.append(part)
        words += n
    return " ".join(kept)


def _lead(paragraphs: list[str]) -> str:
    """The opening of a section. A lead-in ending in ':' brings what it introduces."""
    if not paragraphs:
        return ""
    lead = _sentences(paragraphs[0], MAX_LEAD_WORDS)
    if lead.endswith(":") and len(paragraphs) > 1:
        follow = paragraphs[1]
        items = re.findall(r"^[-*] \*\*(.+?)\*\*", follow, re.M)
        follow = "\n".join(f"- {item}" for item in items) if items else follow
        lead = f"{lead}\n\n{follow}"
    return lead


def _fit(paragraphs: list[str], max_words: int) -> list[str]:
    """As many whole paragraphs as fit a slide, and never fewer than one."""
    kept, words = [], 0
    for paragraph in paragraphs:
        count = len(paragraph.split())
        if kept and words + count > max_words:
            break
        kept.append(paragraph)
        words += count
    return kept or paragraphs[:1]


def _code_height(text: str) -> int:
    """How many lines a code block takes once long lines have wrapped."""
    return sum(max(1, -(-len(line) // CODE_COLS)) for line in text.splitlines())


def _dense(*parts: str) -> str:
    """The directive that sets a crowded slide in smaller type, or ""."""
    text = "\n".join(parts)
    rows = sum(1 for line in text.splitlines() if line.startswith("|"))
    code = _code_height(text) if "```" in text else 0
    if len(text.split()) > DENSE_WORDS or rows > 7 or code > 12:
        return "<!-- _class: dense -->\n\n"
    return ""


def _takeaways(prose: str) -> list[str]:
    """Bold lead-ins of the paragraphs (``**Recall did not move.**``), else the opening."""
    leads = [m.group(1) for m in re.finditer(r"^\s*(?:[-*] )?\*\*(.+?)\*\*", prose, re.M)]
    if leads:
        return leads
    paragraphs = _paragraphs(prose)
    return [_sentences(paragraphs[0], 35)] if paragraphs else []


# --- outputs -----------------------------------------------------------------

class _TableParser(HTMLParser):
    """Enough of an HTML table reader for pandas and Styler output."""

    def __init__(self) -> None:
        super().__init__()
        self.caption, self.rows, self._row, self._cell, self._in = "", [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "caption":
            self._in = "caption"
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "caption":
            self._in = None
        elif tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            if len(text) > MAX_CELL_CHARS:
                text = text[:MAX_CELL_CHARS].rsplit(" ", 1)[0] + " …"
            self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in == "caption":
            self.caption += data
        elif self._cell is not None:
            self._cell.append(data)


def _html_table(markup: str) -> tuple[str, str]:
    """(markdown table, caption) from one HTML table."""
    parser = _TableParser()
    parser.feed(markup)
    rows = [r for r in parser.rows if any(c.strip() for c in r)]
    if not rows:
        return "", ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    head, body = rows[0], rows[1:]
    # pandas puts the index name on a second header row; fold it into the first.
    if body and all(not c for c in body[0][1:]) and body[0][0] and not head[0]:
        head = [body[0][0], *head[1:]]
        body = body[1:]
    more = len(body) - MAX_TABLE_ROWS
    body = body[:MAX_TABLE_ROWS]

    def row(cells):
        return "| " + " | ".join(c.replace("|", "\\|") or " " for c in cells) + " |"

    lines = [row(head), "| " + " | ".join("---" for _ in head) + " |", *map(row, body)]
    table = "\n".join(lines)
    if more > 0:
        table += f"\n\n<div class=\"more\">… {more} more rows in the notebook</div>"
    return table, " ".join(parser.caption.split())


_MD_TABLE = re.compile(r"^\|.+\|\s*\n\|[\s:|-]+\|\s*\n(?:\|.*\|\s*\n?)+", re.M)


def _authored_table(prose: str) -> str:
    """A table the author wrote in the prose. Their own condensation beats a dumped one."""
    match = _MD_TABLE.search(prose)
    return match.group(0).strip() if match else ""


def _code_panels(cell: dict) -> list[str]:
    """One code cell's source, in slide-sized panels.

    Split only where a blank line is followed by an unindented line, so a
    function, a docstring or a dict literal is never cut down the middle: half a
    def on a slide is code that does not do what it says. The opening comment
    goes -- the slide's prose already says what the cell does. A block longer
    than the cap stays whole on a slide of its own, in smaller type.
    """
    lines = _source(cell).splitlines()
    while lines and (lines[0].lstrip().startswith("#") or not lines[0].strip()):
        lines.pop(0)

    blocks, current = [], []
    for line in "\n".join(lines).strip().splitlines():
        if not line.strip():
            current.append(line)
            continue
        # A new top-level statement: the only safe place to break.
        if current and not line[:1].isspace() and not current[-1].strip():
            blocks.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    panels: list[str] = []
    for block in blocks:
        height = _code_height(block)
        if panels and _code_height(panels[-1]) + 1 + height <= MAX_CODE_LINES:
            panels[-1] += "\n\n" + block
        else:
            panels.append(block)
    return panels


def _last_output(cells: list[dict], prefer: int | None = None) -> tuple[int, dict] | None:
    """Index (within ``cells``) and payload of the section's result.

    The plan's evidence cell if it named one, else the last table or chart.
    """
    chosen = [i for i, c in enumerate(cells) if c.get("index") == prefer]
    order = chosen + [i for i in range(len(cells) - 1, -1, -1) if i not in chosen]
    for i in order:
        cell = cells[i]
        if cell["cell_type"] != "code":
            continue
        for output in reversed(cell.get("outputs", [])):
            data = output.get("data") or {}
            if "image/png" in data:
                return i, {"png": data["image/png"]}
            if "text/html" in data and "<table" in "".join(data["text/html"]):
                return i, {"html": "".join(data["text/html"])}
    return None


# --- links -------------------------------------------------------------------

def _github_base(header: str) -> str:
    """https://github.com/OWNER/REPO/blob/BRANCH/, read off the Colab badge."""
    match = re.search(r"colab\.research\.google\.com/github/([^/]+/[^/]+)/blob/([^/]+)/", header)
    return f"https://github.com/{match.group(1)}/blob/{match.group(2)}/" if match else ""


def _absolute_links(text: str, base: str, notebook_dir: str) -> str:
    """Relative links in the notebook point nowhere from build/; point them at GitHub."""
    if not base:
        return text

    def fix(match: re.Match) -> str:
        target = match.group(2)
        if re.match(r"[a-z]+:|#", target):
            return match.group(0)
        path = (Path(notebook_dir) / target).as_posix()
        parts = []
        for part in path.split("/"):
            if part == "..":
                parts.pop()
            elif part != ".":
                parts.append(part)
        return f"{match.group(1)}({base}{'/'.join(parts)})"

    return re.sub(r"(\[[^\]]*\])\(([^)\s]+)\)", fix, text)


# --- the deck ------------------------------------------------------------------

def _notes(text: str) -> str:
    text = text.strip().replace("-->", "→")
    # A blank line first, or markdown folds the comment into the block above it.
    return f"\n\n<!--\n{text}\n-->\n" if text else ""


def _header_fields(header: str) -> dict[str, str]:
    """Title, subtitle and the **Bold.** lines a notebook header opens with."""
    fields = {"title": re.search(r"^# (.+)$", header, re.M).group(1).strip()}
    subtitle = re.search(r"^\*([^*].+?)\*\s*$", header, re.M)
    if subtitle:
        fields["subtitle"] = subtitle.group(1).strip()
    for key in ("Experiment", "Claim", "Result", "Requires"):
        match = re.search(rf"^\*\*{key}\.\*\*\s*(.+)$", header, re.M)
        if match:
            fields[key.lower()] = match.group(1).strip()
    return fields


def _plain(markdown: str) -> str:
    """Markdown emphasis, code ticks and links flattened to their text."""
    text = re.sub(r"\[([^\]]*)\]\([^)\s]+\)", r"\1", markdown)
    text = re.sub(r"[*`]+", "", text)
    return html.escape(" ".join(text.split()))


def write_index(decks: list[tuple[Path, dict]], out_dir: Path) -> Path:
    """A front page for the published site, linking each rendered deck."""
    tracks: dict[str, list[str]] = {}
    for rel, fields in decks:
        row = [f"<h3><a href=\"{rel.with_suffix('.html').as_posix()}\">"
               f"{_plain(fields['title'])}</a> "
               f"<a class=\"pdf\" href=\"{rel.with_suffix('.pdf').as_posix()}\">PDF</a></h3>"]
        if "subtitle" in fields:
            row.append(f"<p class=\"sub\">{_plain(fields['subtitle'])}</p>")
        if "result" in fields:
            row.append(f"<p class=\"result\"><b>Result.</b> {_plain(fields['result'])}</p>")
        tracks.setdefault(rel.parent.as_posix().strip("."), []).append("\n".join(row))

    def order(track: str) -> tuple[int, str]:
        return (TRACK_ORDER.index(track) if track in TRACK_ORDER else len(TRACK_ORDER), track)

    sections = "\n".join(
        f"<section><h2>{html.escape(track) or 'Start here'}</h2>\n" + "\n".join(rows) + "</section>"
        for track, rows in sorted(tracks.items(), key=lambda kv: order(kv[0]))
    )
    page = INDEX_TEMPLATE.format(sections=sections)
    out = out_dir / "index.html"
    out.write_text(page)
    return out


def build(path: Path, out_dir: Path) -> tuple[Path, int, str]:
    nb = json.loads(path.read_text())
    header_cell, sections = _sections(nb["cells"])
    header = _source(header_cell)
    rel = path.relative_to(ROOT)
    base = _github_base(header)
    link = lambda text: _absolute_links(text, base, rel.parent.as_posix())  # noqa: E731

    slides: list[str] = []

    # Title slide.
    fields = _header_fields(header)
    lines = ["<!-- _class: lead -->", f"# {fields['title']}"]
    if "subtitle" in fields:
        lines.append(f"*{fields['subtitle']}*")
    for key in ("experiment", "claim", "result"):
        if key in fields:
            lines.append(f"**{key.title()}.** {fields[key]}")
    badges = re.findall(r"\[!\[[^\]]*\]\([^)]+\)\]\([^)]+\)", header)
    if badges:
        lines.append('<div class="badges">\n\n' + " ".join(badges) + "\n\n</div>")
    if "requires" in fields:
        lines.append(f"<div class=\"more\">Requires: {fields['requires']} · "
                     f"<a href=\"{base}{rel.as_posix()}\">{rel.as_posix()}</a></div>")
    intro = header.split(fields["requires"], 1)[-1] if "requires" in fields else ""
    intro = re.sub(r"^\*\*Read\*\*.*$", "", intro, flags=re.M)
    slides.append("\n\n".join(lines) + _notes(link(intro)))

    plan, warning = load_plan(path)
    entries = {str(e.get("heading", "")).strip(): e for e in plan.get("sections") or []}

    # Summary slide: the plan's overview, for an audience that has not read the
    # notebook. Written by whoever reviewed the plan, never generated here.
    if plan.get("summary"):
        bullets = "\n".join(f"- {line}" for line in plan["summary"])
        slides.append(f"## {plan.get('summary_heading', 'In short')}\n\n{bullets}")

    image_count = 0
    for section in sections:
        cells = section["cells"]
        entry = entries.get(section["title"], {})
        if entry.get("setup") or entry.get("skip"):
            continue
        prose_cells = [c for c in cells if c["cell_type"] == "markdown"]
        is_closing = section["title"].lower().startswith("where to take this")

        if is_closing:
            prose = "\n\n".join(_source(c) for c in prose_cells)
            bullets = re.findall(r"^[-*] \*\*(.+?)\*\*", prose, re.M)
            body = "\n".join(f"- {b}" for b in bullets) or _sentences(prose, MAX_LEAD_WORDS)
            slides.append(f"## {section['title']}\n\n{link(body)}" + _notes(link(prose)))
            continue

        evidence = (entry.get("evidence") or {})
        found = _last_output(cells, prefer=evidence.get("cell"))
        split_at = found[0] if found else len(cells)
        before, after = cells[:split_at + 1], cells[split_at + 1:]

        # Section slide: heading, the main idea, the prose the plan kept, and
        # either the code it chose to show or a line per cell saying what it does.
        before_prose = "\n\n".join(_source(c) for c in before if c["cell_type"] == "markdown")
        paragraphs = section_paragraphs(section)
        after_paragraphs = _paragraphs("\n\n".join(_source(c) for c in after
                                                   if c["cell_type"] == "markdown"))
        chosen = [paragraphs[i] for i in entry.get("paragraphs", []) if i < len(paragraphs)]
        # A paragraph written under the evidence belongs on the result slide, where
        # it already appears; on the section slide it would give the result away.
        chosen = [p for p in chosen if p not in after_paragraphs]
        modes = {c.get("cell"): c.get("mode", "summarize") for c in entry.get("code") or []}
        shown = [c for c in before if c["cell_type"] == "code" and modes.get(c["index"]) == "show"]
        steps = [_comment(c) for c in before if c["cell_type"] == "code" and _comment(c)
                 and modes.get(c["index"], "summarize") != "hide"]
        panels = _code_panels(shown[0]) if shown else []

        # Code takes half the slide, so the prose beside it gets half the budget.
        chosen = _fit(chosen, MAX_COLUMN_WORDS if panels else MAX_SLIDE_WORDS)
        lead = "\n\n".join(chosen) if chosen else _lead(_paragraphs(before_prose))
        if entry.get("idea"):
            idea = f"**{entry['idea']}**"
            # Beside code, a long paragraph under the idea is what tips a slide
            # over. The idea is written to carry the section on its own.
            if panels and len(f"{idea} {lead}".split()) > MAX_COLUMN_WORDS + 25:
                lead = ""
            lead = idea + (f"\n\n{lead}" if lead else "")

        body = [f"## {section['title']}"]
        column = [link(lead)]
        if steps and not panels:
            column.append('<div class="steps">\n\n' + "\n".join(f"▸ {s}  " for s in steps)
                          + "\n\n</div>")
        if panels:
            body.append('<div class="cols">\n\n' + "\n\n".join(column)
                        + f"\n\n```python\n{panels[0]}\n```\n\n</div>")
        else:
            body.extend(column)
        slide = "\n\n".join(b for b in body if b)
        slides.append(_dense(slide) + slide + _notes(link(before_prose)))

        # The rest of a long cell, a slide at a time rather than a cut.
        for panel in panels[1:]:
            slide = f"### {section['title']}, continued\n\n```python\n{panel}\n```"
            slides.append(_dense(f"```\n{panel}\n```") + slide)

        if not found or evidence.get("cell") is False:
            continue

        # Result slide: the evidence, then what the notebook says about it.
        _, payload = found
        after_prose = "\n\n".join(_source(c) for c in after if c["cell_type"] == "markdown")
        takeaways = _takeaways(after_prose) if evidence.get("explain", True) else []
        body = [f"### {section['title']}"]
        if "png" in payload:
            image_count += 1
            image = out_dir / f"{path.stem}_{image_count}.png"
            image.write_bytes(base64.b64decode("".join(payload["png"])))
            body.append(f"![w:900]({image.name})")
        elif _authored_table(after_prose):
            # The author's own table, written under the output it summarises.
            body.append(_authored_table(after_prose))
        else:
            table, caption = _html_table(payload["html"])
            if caption:
                body.append(f"*{html.unescape(caption)}*")
            body.append(html.unescape(table))
        if takeaways:
            body.append("\n".join(f"- {link(t)}" for t in _fit(takeaways, MAX_COLUMN_WORDS)[:4]))
        slide = "\n\n".join(body)
        slides.append(_dense(slide) + slide + _notes(link(after_prose)))

    # Marp repeats this on every slide; the title slide shows the badges instead.
    badge_link = lambda label: next(  # noqa: E731
        (m.group(1) for m in re.finditer(rf"\[!\[{label}[^\]]*\]\([^)]+\)\]\(([^)]+)\)", header)), "")
    footer = " · ".join(filter(None, [
        f"[{rel.as_posix()}]({base}{rel.as_posix()})" if base else rel.as_posix(),
        f"[Open in Colab]({badge_link('Open In Colab')})" if badge_link("Open In Colab") else "",
        f"[Open in Codespaces]({badge_link('Open in Codespaces')})"
        if badge_link("Open in Codespaces") else "",
    ]))

    out = out_dir / f"{path.stem}.md"
    out.write_text(FRONT_MATTER.format(footer=footer) + "\n" + "\n\n---\n\n".join(slides) + "\n")
    return out, len(slides), warning


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("notebook", help="a path, a prefix like retrieval/03, or 'all'")
    args = parser.parse_args(argv)
    root_out = ROOT / "build" / "slides"

    if args.notebook == "all":
        paths = [p for p in sorted((ROOT / "notebooks").glob("**/*.ipynb"))
                 if ".ipynb_checkpoints" not in p.parts]
    else:
        paths = [resolve_notebook(args.notebook)]

    decks = []
    for path in paths:
        out_dir = root_out / path.parent.relative_to(ROOT / "notebooks")
        out_dir.mkdir(parents=True, exist_ok=True)
        out, count, warning = build(path, out_dir)
        if warning:
            print(f"    ~ {warning}")
        decks.append((out.relative_to(root_out), _header_fields(_source(json.loads(
            path.read_text())["cells"][0]))))
        print(f"{count:3} slides -> {out.relative_to(ROOT)}")

    if args.notebook == "all":
        index = write_index(decks, root_out)
        print(f"{len(decks):3} decks  -> {index.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
