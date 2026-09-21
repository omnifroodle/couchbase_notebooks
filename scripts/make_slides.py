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

No model is involved. Every word on a slide is already in the notebook, which
already had its prose checked against its outputs. The deck is a condensation
by rule:

* **Title slide** -- the header's title, subtitle, Claim, Result and Requires.
* **One slide per ``##`` section** -- its heading, its first paragraph, and
  what the code does, as each code cell's opening comment.
* **A result slide** when a section's code printed a table or a chart -- the
  last one in the section, and the bold lead-ins (or opening sentences) of the
  prose that follows it.
* **"Where to take this"** -- the bullets' bold lead-ins.

The rest of each section's prose goes into speaker notes. Setup and clean-up
cells are left out. Stored outputs are used as they are; nothing is re-run.
"""

from __future__ import annotations

import argparse
import base64
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
  section.dense table {{ font-size: 14px; }}
  section.dense th, section.dense td {{ padding: 2px 8px !important; }}
  blockquote {{ font-size: 22px; }}
  .steps {{ font-size: 20px; color: #555; }}
  .more {{ font-size: 16px; color: #888; }}
  .badges img {{ height: 28px; }}
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
    for cell in cells[1:]:
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


def _last_output(cells: list[dict]) -> tuple[int, dict] | None:
    """Index (within ``cells``) and payload of the section's last table or chart."""
    for i in range(len(cells) - 1, -1, -1):
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


def build(path: Path, out_dir: Path) -> tuple[Path, int]:
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

    image_count = 0
    for section in sections:
        cells = section["cells"]
        prose_cells = [c for c in cells if c["cell_type"] == "markdown"]
        is_closing = section["title"].lower().startswith("where to take this")

        if is_closing:
            prose = "\n\n".join(_source(c) for c in prose_cells)
            bullets = re.findall(r"^[-*] \*\*(.+?)\*\*", prose, re.M)
            body = "\n".join(f"- {b}" for b in bullets) or _sentences(prose, MAX_LEAD_WORDS)
            slides.append(f"## {section['title']}\n\n{link(body)}" + _notes(link(prose)))
            continue

        found = _last_output(cells)
        split_at = found[0] if found else len(cells)
        before, after = cells[:split_at + 1], cells[split_at + 1:]

        # Section slide: heading, lead paragraph, what the code does.
        before_prose = "\n\n".join(_source(c) for c in before if c["cell_type"] == "markdown")
        paragraphs = _paragraphs(before_prose)
        lead = _lead(paragraphs)
        steps = [_comment(c) for c in before if c["cell_type"] == "code" and _comment(c)]
        body = [f"## {section['title']}", link(lead)]
        if steps:
            body.append('<div class="steps">\n\n' + "\n".join(f"▸ {s}  " for s in steps)
                        + "\n\n</div>")
        slides.append("\n\n".join(b for b in body if b) + _notes(link(before_prose)))

        if not found:
            continue

        # Result slide: the output, then what the notebook says about it.
        _, payload = found
        after_prose = "\n\n".join(_source(c) for c in after if c["cell_type"] == "markdown")
        takeaways = _takeaways(after_prose)
        body = [f"### {section['title']}"]
        if "png" in payload:
            image_count += 1
            image = out_dir / f"{path.stem}_{image_count}.png"
            image.write_bytes(base64.b64decode("".join(payload["png"])))
            body.append(f"![w:900]({image.name})")
        else:
            table, caption = _html_table(payload["html"])
            if table.count("\n") > 6:  # more than about five rows
                body.insert(0, "<!-- _class: dense -->")
            if caption:
                body.append(f"*{html.unescape(caption)}*")
            body.append(html.unescape(table))
        if takeaways:
            body.append("\n".join(f"- {link(t)}" for t in takeaways[:4]))
        slides.append("\n\n".join(body) + _notes(link(after_prose)))

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
    return out, len(slides)


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
        out, count = build(path, out_dir)
        decks.append((out.relative_to(root_out), _header_fields(_source(json.loads(
            path.read_text())["cells"][0]))))
        print(f"{count:3} slides -> {out.relative_to(ROOT)}")

    if args.notebook == "all":
        index = write_index(decks, root_out)
        print(f"{len(decks):3} decks  -> {index.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
