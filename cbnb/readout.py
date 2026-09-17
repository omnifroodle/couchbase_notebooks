"""A status panel for notebook output: coloured verdicts instead of a wall of text.

Deliberately generic. It draws rows that are ``ok``, ``blocked`` or ``unknown``,
with a title, a detail line and an optional note underneath, and knows nothing
about what the rows describe. That keeps it out of the boundary between
:mod:`cbnb.readiness` and :mod:`cbnb.inventory`: ``00_check_setup`` does the
joining and hands this module plain rows.

No dependencies. A :class:`Panel` renders as HTML wherever a notebook frontend
shows rich output (Jupyter, VS Code, Colab), and as aligned plain text anywhere
else -- a terminal, a log, ``print(panel)``.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

__all__ = ["Item", "Panel"]

#: status -> (label, pill colour). Solid pills with white text read the same on
#: light and dark themes; everything else inherits the frontend's text colour.
_STATUS = {
    "ok": ("ready", "#1f883d"),
    "blocked": ("blocked", "#cf222e"),
    "unknown": ("unknown", "#6e7781"),
}
_TEXT_MARK = {"ok": "ok", "blocked": "--", "unknown": "? "}


@dataclass(frozen=True)
class Item:
    """One row of a panel."""

    status: str
    title: str
    detail: str = ""
    #: Shown under the row, e.g. how to fix it. May span several lines.
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUS:
            raise ValueError(f"status must be one of {sorted(_STATUS)}, not {self.status!r}")


@dataclass(frozen=True)
class Panel:
    """A headline, an optional summary line, and sections of rows."""

    headline: str
    sections: list[tuple[str, list[Item]]] = field(default_factory=list)
    summary: str = ""
    #: Overall colour of the headline bar: "ok", "blocked" or "unknown".
    status: str = "unknown"

    # --- plain text ---------------------------------------------------------

    def __str__(self) -> str:
        lines = [self.headline]
        if self.summary:
            lines.append(self.summary)
        for heading, items in self.sections:
            if not items:
                continue
            lines += ["", heading]
            for item in items:
                detail = f"  {item.detail}" if item.detail else ""
                lines.append(f"  [{_TEXT_MARK[item.status]}] {item.title}{detail}")
                lines += [f"       {line}" for line in item.note.splitlines()]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)

    # --- html ---------------------------------------------------------------

    def _repr_html_(self) -> str:
        _, colour = _STATUS.get(self.status, _STATUS["unknown"])
        parts = [
            '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
            "font-size:13px;line-height:1.45;max-width:880px;"
            'border:1px solid rgba(127,127,127,.35);border-radius:8px;overflow:hidden">',
            f'<div style="border-left:6px solid {colour};padding:10px 14px;'
            'background:rgba(127,127,127,.08)">',
            f'<div style="font-size:15px;font-weight:600">{_e(self.headline)}</div>',
        ]
        if self.summary:
            parts.append(f'<div style="opacity:.8;margin-top:2px">{_e(self.summary)}</div>')
        parts.append("</div>")

        for heading, items in self.sections:
            if not items:
                continue
            parts.append(
                '<div style="padding:8px 14px 2px;font-size:11px;font-weight:600;'
                f'letter-spacing:.04em;text-transform:uppercase;opacity:.65">{_e(heading)}</div>'
            )
            for item in items:
                parts.append(_row(item))
        parts.append("</div>")
        return "".join(parts)


def _row(item: Item) -> str:
    label, colour = _STATUS[item.status]
    note = ""
    if item.note:
        note = (
            '<div style="margin-top:4px;padding:6px 8px;border-radius:4px;'
            'background:rgba(127,127,127,.1);white-space:pre-wrap;font-size:12px">'
            f"{_e(item.note)}</div>"
        )
    detail = f'<div style="opacity:.8">{_e(item.detail)}</div>' if item.detail else ""
    return (
        '<div style="display:flex;gap:10px;align-items:flex-start;padding:6px 14px;'
        'border-top:1px solid rgba(127,127,127,.18)">'
        f'<span style="flex:none;min-width:58px;text-align:center;margin-top:1px;'
        f"padding:1px 8px;border-radius:10px;background:{colour};color:#fff;"
        f'font-size:11px;font-weight:600">{label}</span>'
        f'<div style="min-width:0"><div style="font-weight:600">{_e(item.title)}</div>'
        f"{detail}{note}</div></div>"
    )


def _e(text: str) -> str:
    return html.escape(str(text))
