#!/usr/bin/env python3
"""Ask a model to plan a slide deck for a notebook, and write the plan to a file.

    python scripts/review_slides.py retrieval/03
    make review-slides NB=retrieval/03
    make review-slides NB=all       # every notebook, one call each

The plan lands in ``slides/<track>/<name>.yml``. Read it, edit it, commit it:
``make slides`` builds the deck from it. Section by section the model answers
the questions a person would -- is this section only setup, what is its main
idea, which paragraphs carry that idea, which code is worth reading on a slide
and which is summarised to its comment, which output is the evidence, and does
that evidence need explaining -- plus a summary of the deck for an audience that
has not read the notebook.

**Run again after editing the notebook and it updates, rather than overwrites.**
Each entry records a hash of the section it was written against. Sections that
have not changed keep their entry exactly as you left it; only changed and new
sections are replanned, and the run prints which were which.

Advisory in the same sense as ``make review``: a model proposes, a person
approves by committing. Nothing here reaches a slide until the plan is on disk,
and a slide's own words are still the notebook's prose. Exits 0 whatever
happens, including when no model is configured.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# A batch tool: report a missing credential, never stop and ask for one.
os.environ.setdefault("CBNB_NONINTERACTIVE", "1")

from make_slides import (  # noqa: E402 - needs the scripts directory on sys.path
    _sections,
    load_plan,
    plan_path_for,
    resolve_notebook,
    section_hash,
    section_paragraphs,
)

from cbnb.review import check_slides  # noqa: E402 - needs ROOT on sys.path

HEADER = """# Slide plan for {notebook}
#
# Drafted by `make review-slides NB={stem}`, then edited and committed by hand.
# `make slides` builds the deck from this file; without it the deck falls back
# to the generator's own rules.
#
#   setup       drop the section: it only makes the notebook run
#   idea        the section's point, shown in bold above its prose
#   paragraphs  which of the section's paragraphs reach the slide
#   code        per cell: show it, summarize it to its comment, or hide it
#   evidence    the cell whose output is the section's result; false for none
#
# `hash` is what the entry was planned against. Change the section in the
# notebook and the next review replans that entry and leaves the others alone.
"""


def as_yaml(plan: dict) -> str:
    import yaml

    return yaml.safe_dump(plan, sort_keys=False, allow_unicode=True, width=88, indent=2)


def plan_notebook(name: str) -> int:
    path = resolve_notebook(name)
    nb_json = json.loads(path.read_text())
    _, sections = _sections(nb_json["cells"])
    sections = [s for s in sections if not s["title"].lower().startswith("where to take this")]

    existing, warning = load_plan(path)
    if warning and "no plan at" not in warning:
        print(f"    ~ {warning}")
    kept = {str(e.get("heading", "")).strip(): e for e in (existing.get("sections") or [])
            if e.get("hash")}

    hashes = {s["title"]: section_hash(s) for s in sections}
    fresh = [s["title"] for s in sections
             if kept.get(s["title"], {}).get("hash") != hashes[s["title"]]]
    gone = [h for h in kept if h not in hashes]

    print(f"--- {path.relative_to(ROOT)} ---")
    if existing:
        for heading in fresh:
            print(f"    {'new' if heading not in kept else 'changed'}: {heading}")
        for heading in gone:
            print(f"    gone: {heading}")
        if not fresh and not gone:
            print("    every section matches the plan; nothing to replan")
            return 0

    described = [
        {"title": s["title"],
         "first_cell": min(c["index"] for c in s["cells"]) if s["cells"] else 0,
         "last_cell": max(c["index"] for c in s["cells"]) if s["cells"] else 0,
         "paragraphs": [" ".join(p.split())[:400] for p in section_paragraphs(s)]}
        for s in sections
    ]
    plan, report = check_slides(described, nb_json)
    if not plan:
        print(report)  # skipped: no model, no key, a refusal
        return 0

    # Only the sections that changed take the model's new entry; the rest stay
    # exactly as the author last edited them.
    planned = {str(e["heading"]).strip(): e for e in plan["sections"]}
    merged = []
    for section in sections:
        heading = section["title"]
        entry = planned.get(heading, {}) if heading in fresh else kept.get(heading, {})
        entry = {**entry, "heading": heading, "hash": hashes[heading]}
        merged.append(entry)

    out = {
        "notebook": str(path.relative_to(ROOT)),
        "summary_heading": existing.get("summary_heading", "In short"),
        "summary": existing.get("summary") or plan["summary"],
        "sections": merged,
    }
    plan_path = plan_path_for(path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(HEADER.format(notebook=out["notebook"], stem=path.stem) + as_yaml(out))
    replanned = len(fresh) if existing else len(sections)
    print(f"    {report.model} planned {replanned} of {len(sections)} sections"
          f" -> {plan_path.relative_to(ROOT)}")
    print("    A proposal: read it, edit it, commit it. `make slides` builds from it.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 0
    names = argv[1:]
    if names == ["all"]:
        names = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "notebooks").glob("**/*.ipynb"))
                 if ".ipynb_checkpoints" not in p.parts]
    for name in names:
        try:
            plan_notebook(name)
        except Exception as exc:  # noqa: BLE001 - advisory: report and carry on
            print(f"{name}: {type(exc).__name__}: {exc}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
