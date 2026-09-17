"""Two ways of pointing a model at a notebook's results, both deliberately weak.

:func:`check_claims` audits finished prose **for the author**: which statements
do the stored outputs no longer support? :func:`commentary` explains a fresh
result **to a live reader**, and exists only in their session -- tag its cell
``cbnb-ephemeral`` and ``make ship`` runs it and then empties it.

Neither is allowed to become one of the notebook's claims. The prose is written
by a person and backed by a measurement; that is what this repo is for. These
are a second pair of eyes and a tutor, respectively, and both are fallible.

---

Ask a model which of a notebook's claims its own outputs no longer support.

Prose in these notebooks names specifics from the run stored beside it: the
lowest-scoring row, a particular product that resolved wrongly, the shape of the
failures. Re-running the notebook moves those, and nothing catches it -- the
notebook still executes, the checks still pass, and the text quietly describes a
run that no longer exists.

This module is the advisory pass for that. It reads the committed prose and the
committed outputs, and reports statements the outputs contradict or cannot
support. It is deliberately **advisory only**:

* nothing it produces is written into a notebook,
* readers never see it -- it reports to whoever is shipping,
* it never fails a build, and it skips cleanly when no model is configured.

So a wrong answer costs a few seconds of attention, which is the right price for
a check that cannot itself be checked. Isolated on purpose: nothing else in
``cbnb`` imports this, so it can be deleted in one commit if it does not earn
its keep.

Model: ``CBNB_REVIEW_MODEL``, falling back to the notebook's own model. A
notebook may deliberately demonstrate a *cheap* model; judging whether prose
matches evidence is not the job to economise on.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Commentary",
    "Finding",
    "Report",
    "check_claims",
    "commentary",
    "evidence_of",
    "prose_of",
]

#: Per-cell cap on output text handed to the model. Long tables say what they
#: need to say early, and one runaway cell should not crowd out the rest.
MAX_OUTPUT_CHARS = 4000

_TAG = re.compile(r"<[a-zA-Z/!][^>]*>")
_BLANK = re.compile(r"\n{3,}")
#: A bare object repr standing in for real content -- "<pandas.io.formats.style.Styler
#: at 0x10a3f2d5>", "<Figure size 800x360 with 1 Axes>". The content, if there is any,
#: is in a richer representation alongside it.
_OBJECT_REPR = re.compile(r"^<[^<>\n]{1,160}>$")


@dataclass(frozen=True)
class Finding:
    """One prose statement the run does not back up."""

    cell: int
    quote: str
    verdict: str  # "contradicted" or "unsupported"
    why: str

    def __str__(self) -> str:
        return f"cell {self.cell} [{self.verdict}] {self.quote}\n    {self.why}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    skipped: str = ""  # why the review did not run, if it did not
    model: str = ""

    @property
    def ok(self) -> bool:
        return not self.findings

    def __str__(self) -> str:
        if self.skipped:
            return f"claim review skipped: {self.skipped}"
        if not self.findings:
            return f"claim review ({self.model}): nothing flagged"
        lines = [f"claim review ({self.model}): {len(self.findings)} to look at", ""]
        lines += [str(f) + "\n" for f in self.findings]
        lines.append("Advisory only -- a model's opinion, not a test. Check each against the "
                     "outputs yourself before editing.")
        return "\n".join(lines)


def _first_line(exc: Exception) -> str:
    """Some exceptions carry no message at all -- EOFError from a blocked prompt."""
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else "no detail"


def _cell_text(cell: dict[str, Any]) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def prose_of(nb: dict[str, Any]) -> str:
    """The notebook's markdown, numbered by cell so findings can point at one."""
    blocks = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "markdown":
            continue
        text = _cell_text(cell).strip()
        if text:
            blocks.append(f"[cell {i}]\n{text}")
    return "\n\n".join(blocks)


_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_CELL = re.compile(r"<t[hd]\b.*?</t[hd]>", re.S | re.I)


def _table_rows(value: Any) -> str:
    """An HTML table as ``a | b | c`` lines, or "" if the output holds no table."""
    if not value:
        return ""
    markup = "".join(value) if isinstance(value, list) else str(value)
    if "<table" not in markup.lower():
        return ""
    import html

    lines = []
    for row in _ROW.findall(markup):
        cells = [" ".join(html.unescape(_TAG.sub(" ", c)).split()) for c in _CELL.findall(row)]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def _render_output(output: dict[str, Any]) -> str:
    """One output as plain text, preferring representations that need no parsing."""
    text = output.get("text", "")
    if text:
        return "".join(text) if isinstance(text, list) else text

    data = output.get("data") or {}
    # A table is read from its HTML, one row per line. pandas' text/plain of a wide
    # table wraps columns into separate blocks and elides long cells with "...",
    # and a reviewing model then misreads which value sits at which rank.
    table = _table_rows(data.get("text/html"))
    if table:
        return table
    # pandas emits text/plain alongside text/html; the former needs no stripping,
    # which is the whole reason to prefer it -- except for a styled DataFrame,
    # whose text/plain is a bare object repr and whose table lives only in the
    # HTML. Preferring the repr silently drops the most evidence-rich cells.
    for mime in ("text/plain", "text/markdown"):
        if mime in data:
            value = data[mime]
            text = "".join(value) if isinstance(value, list) else str(value)
            if not _OBJECT_REPR.match(text.strip()):
                return text
    if "text/html" in data:
        value = data["text/html"]
        html = "".join(value) if isinstance(value, list) else str(value)
        # Only real tags: plain text in these outputs contains "<- correct"
        # arrows, and a greedy <...> would swallow everything up to the next ">".
        html = _TAG.sub(" ", html)
        for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
            html = html.replace(entity, char)
        return re.sub(r"[ \t]{2,}", "  ", html)
    if output.get("output_type") == "error":
        return "\n".join(output.get("traceback", []))
    return ""  # images and anything else a model cannot read as text


def evidence_of(nb: dict[str, Any]) -> str:
    """Everything the stored run actually printed, numbered by cell."""
    blocks = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        rendered = [_render_output(o) for o in cell.get("outputs", [])]
        text = _BLANK.sub("\n\n", "\n".join(r for r in rendered if r.strip()).strip())
        if not text:
            continue
        if len(text) > MAX_OUTPUT_CHARS:
            text = text[:MAX_OUTPUT_CHARS] + "\n[... truncated ...]"
        blocks.append(f"[output of cell {i}]\n{text}")
    return "\n\n".join(blocks)


SYSTEM = """You are reviewing a technical notebook before it is published, checking one \
narrow thing: does the prose still describe the run whose outputs are stored beside it?

Notebooks here are re-run periodically. Numbers shift and individual examples change, so \
prose that names a specific example, value, ordering or count can quietly stop being true \
while everything still executes cleanly. Finding those is the entire job.

Flag a statement only when the outputs contradict it, or when it names something specific \
that does not appear in the outputs at all. Quote the statement exactly as written.

Do NOT flag:
- general explanation, background, motivation, or how something works
- suggestions, next steps, or anything forward-looking
- statements deliberately hedged about variation between runs
- anything that is not checkable against the outputs shown
- approximate descriptions that remain fair (e.g. "clear gap" when a clear gap exists)

Report nothing if nothing is wrong. A short, correct list is worth far more than a long one: \
every false flag costs the author time they will not spend on the real ones."""

USER = """Prose from the notebook:

{prose}

=====

Outputs produced by the run stored in the notebook:

{evidence}

=====

List the statements in the prose that these outputs contradict or cannot support."""


def check_claims(
    notebook: str | Path | dict[str, Any],
    *,
    model: str | None = None,
    provider: str | None = None,
) -> Report:
    """Review one notebook's prose against its stored outputs.

    Never raises: anything that goes wrong becomes a skipped report, because
    this is advice and advice is not worth failing a build over.
    """
    try:
        nb = notebook if isinstance(notebook, dict) else json.loads(Path(notebook).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return Report(skipped=f"could not read the notebook ({exc})")

    prose, evidence = prose_of(nb), evidence_of(nb)
    if not evidence.strip():
        return Report(skipped="the notebook has no stored outputs to check against")
    if not prose.strip():
        return Report(skipped="the notebook has no prose to check")

    try:
        from pydantic import BaseModel, Field

        from cbnb.llm import LLM

        class _Finding(BaseModel):
            cell: int = Field(description="the [cell N] the statement appears in")
            quote: str = Field(description="the statement, copied exactly from the prose")
            verdict: str = Field(description="'contradicted' or 'unsupported'")
            why: str = Field(description="what the outputs show instead, in one sentence")

        class _Review(BaseModel):
            # Required, not defaulted: with a default, a bare "{}" validates as a
            # clean review, and a model that said nothing reads as one that found
            # nothing. Required makes it a failed reply, which gets retried.
            findings: list[_Finding] = Field(description="empty list if nothing is wrong")

        # Via load_settings, so .env is read: os.environ alone would miss the
        # configured provider and fall back to openai, then prompt for a key.
        from cbnb.config import load_settings

        cfg = load_settings()
        chosen = model or os.environ.get("CBNB_REVIEW_MODEL") or cfg.llm_model or None
        llm = LLM(provider or cfg.llm_provider, model=chosen)
        review = llm.structured(
            USER.format(prose=prose, evidence=evidence),
            _Review,
            system=SYSTEM,
            temperature=0,
            max_tokens=2048,  # a findings list with quotes outgrows the default
        )
    except Exception as exc:  # noqa: BLE001 - advisory: degrade, never break
        return Report(skipped=f"{type(exc).__name__}: {_first_line(exc)}")

    findings = [
        Finding(cell=f.cell, quote=f.quote.strip(), verdict=f.verdict.strip().lower(), why=f.why)
        for f in review.findings
    ]
    return Report(findings=findings, model=llm.model)


# --- Live commentary -------------------------------------------------------
#
# The other half of this module, pointed the other way: check_claims audits
# finished prose for the author, this explains a fresh result to whoever is
# running the notebook. It exists only in a live session. Put it in a cell
# tagged `cbnb-ephemeral` (see cbnb.nbstamp) so `make ship` runs it and then
# empties it: a model's reading of the results is unreviewed, differs every run,
# and is not one of the notebook's claims. The prose around it is.

TUTOR_SYSTEM = """You are a teaching assistant for a technical notebook, reading a result \
the reader has just produced and helping them interpret it.

Ground every sentence in the figures you are given. Where the result differs from what the \
author expected, say so plainly and say what the figures actually show -- that is the most \
useful thing you can offer, and agreeing pleasantly is the least.

Use the figures as printed. Do not derive new ones: no converting rates into counts, no \
ratios, no recomputed totals. Arithmetic you do in your head arrives looking exactly as \
confident as the numbers you were given, and it is the one thing here nobody checks. A \
difference between two printed figures is the most you should ever compute, and describing \
the direction and rough size is usually better than computing anything at all.

If the evidence is too thin to support a reading, say that instead of filling the space.

Four sentences or fewer, or up to three short bullets. Plain markdown, no heading. The \
reader can see the output already; tell them what it means, not what it says."""

TUTOR_USER = """What the notebook is demonstrating:
{context}

What the author expected:
{expectation}

The result the reader is looking at:
{evidence}
{question}"""


@dataclass
class Commentary:
    """A model's reading of a fresh result, for a live reader only."""

    text: str = ""
    model: str = ""
    skipped: str = ""

    _BANNER = ("**Agent commentary** — written by `{model}` from the output above, in this "
               "session only. Unreviewed, and not one of this notebook's claims.")

    def _body(self) -> str:
        if self.skipped:
            return f"*Agent commentary unavailable: {self.skipped}*"
        return f"> {self._BANNER.format(model=self.model)}\n\n{self.text}"

    def _repr_markdown_(self) -> str:
        return self._body()

    def __str__(self) -> str:
        if self.skipped:
            return f"Agent commentary unavailable: {self.skipped}"
        return f"--- agent commentary ({self.model}), unreviewed ---\n{self.text}"


def commentary(
    evidence: Any,
    expectation: str = "",
    *,
    context: str = "",
    question: str = "",
    model: str | None = None,
    provider: str | None = None,
) -> Commentary:
    """Explain a fresh result to whoever is running the notebook.

    Args:
        evidence: the result itself -- a DataFrame, dict, string, anything whose
            printed form carries the numbers. Rendered with ``str``.
        expectation: what the notebook predicted would happen. Give it honestly,
            including the parts that are uncertain: it is what lets the model
            tell the reader the result disagreed.
        context: one line on what is being demonstrated, if it isn't obvious.
        question: an explicit question to answer instead of a general reading.

    Returns a :class:`Commentary`, which renders as markdown in a notebook. Never
    raises -- with no model configured it renders a one-line note.
    """
    text = evidence if isinstance(evidence, str) else _render_evidence(evidence)
    if not text.strip():
        return Commentary(skipped="there is no result to read")

    try:
        from cbnb.config import load_settings
        from cbnb.llm import LLM

        cfg = load_settings()
        chosen = model or os.environ.get("CBNB_REVIEW_MODEL") or cfg.llm_model or None
        llm = LLM(provider or cfg.llm_provider, model=chosen)
        answer = llm.chat(
            TUTOR_USER.format(
                context=context or "(not stated)",
                expectation=expectation or "(not stated)",
                evidence=text,
                question=f"\nThe reader asks: {question}" if question else "",
            ),
            system=TUTOR_SYSTEM,
            temperature=0,
            max_tokens=400,
        )
    except Exception as exc:  # noqa: BLE001 - commentary is a bonus, never a blocker
        return Commentary(skipped=f"{type(exc).__name__}: {_first_line(exc)}")

    return Commentary(text=answer.strip(), model=llm.model)


def _render_evidence(value: Any) -> str:
    """Printed form of a result, preferring the readable one a DataFrame offers."""
    for attr in ("to_string", "to_markdown"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return str(method())
            except Exception:  # noqa: BLE001 - fall back to repr
                break
    return str(value)
