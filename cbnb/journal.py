"""Every uncached run of a notebook, kept, so one run is never mistaken for the result.

A ship overwrites the last ship. On its own that hides how much a result moves:
the same code, through the same provider, has turned a six-point gain into a
half-point one between two days, and each notebook's prose was rewritten to the
run in front of it. The journal keeps one entry per run -- ship or trial -- with
the models that answered, what they cost in tokens, and what the notebook
*measured* and *claimed*. ``make journal`` then shows which claims hold every
time and which flap.

What to keep is declared in the notebook's own metadata, so a reader never sees
it and adding one needs no re-ship::

    "cbnb": {
      "measures": {"strict accuracy": "scores.loc['strict', 'accuracy']"},
      "claims":   {"strict prompt beats loose":
                   "scores.loc['strict', 'accuracy'] > scores.loc['loose', 'accuracy']"}
    }

Each value is a Python expression evaluated in the notebook's kernel after its
last cell. A measure is a number; a claim is something the prose asserts, as a
test. A renamed variable makes an expression fail; the entry records the error
rather than losing the run.

Entries are only written for uncached runs: a cached answer is the earlier run
again, and would make a claim look steadier than it is.

Standard library only, so the checker can read the journal without the
notebook dependencies.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "journal"
NOTEBOOKS = ROOT / "notebooks"

#: Prefixes the probe cell's single output line, so it cannot be confused with
#: anything the notebook printed.
MARKER = "CBNB-JOURNAL "

#: Entry fields that identify a model, without what changes every run.
_MODEL_KEY = ("role", "model", "provider")


def declared(nb: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """The measures and claims a notebook asks the journal to keep."""
    meta = nb.get("metadata", {}).get("cbnb") or {}
    return dict(meta.get("measures") or {}), dict(meta.get("claims") or {})


def probe_source(measures: dict[str, str], claims: dict[str, str]) -> str:
    """A cell that evaluates the declarations in the kernel and prints one JSON line.

    Runs after the notebook's last cell and is removed before anything is
    written, so it never reaches the committed notebook.
    """
    return f'''\
def _cbnb_journal_probe(measures, claims):
    import json, math
    from cbnb import provenance
    found = {{"measures": {{}}, "claims": {{}}, "errors": {{}}}}
    for kind, exprs in (("measures", measures), ("claims", claims)):
        for name, expr in exprs.items():
            try:
                value = eval(expr, globals())
                if kind == "claims":
                    found[kind][name] = bool(value)
                else:
                    value = float(value)
                    found[kind][name] = None if math.isnan(value) else value
            except Exception as exc:
                found["errors"][name] = f"{{type(exc).__name__}}: {{exc}}"
    found["models"] = [
        {{"role": u.role, "model": u.model, "provider": u.provider, "routed": u.routed,
          "calls": u.calls, "cached": u.cached, "served": sorted(u.served),
          "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens}}
        for u in provenance.uses()]
    print({MARKER!r} + json.dumps(found))
_cbnb_journal_probe({json.dumps(measures)}, {json.dumps(claims)})
'''


def parse_probe(outputs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """What the probe cell printed, or None if it printed nothing usable."""
    for output in outputs:
        text = output.get("text", "")
        text = "".join(text) if isinstance(text, list) else text
        for line in text.splitlines():
            if line.startswith(MARKER):
                return json.loads(line[len(MARKER):])
    return None


def name_of(path: Path) -> str:
    """``notebooks/flows/01_rag_that_you_can_trust.ipynb`` -> ``flows/01_rag_that_you_can_trust``."""
    return str(path.resolve().relative_to(NOTEBOOKS).with_suffix(""))


def write(notebook: Path, entry: dict[str, Any]) -> Path:
    """Store one run. One file per run, so two branches never conflict over the journal."""
    run_at = entry.setdefault("run_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    folder = JOURNAL / name_of(notebook)
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{run_at.replace(':', '')}-{entry['kind']}.json"
    out.write_text(json.dumps(entry, indent=1, ensure_ascii=False) + "\n")
    return out


def entries(name: str) -> list[dict[str, Any]]:
    """Every run of one notebook, oldest first."""
    folder = JOURNAL / name
    runs = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return sorted(runs, key=lambda e: e["run_at"])


def journaled() -> list[str]:
    """Every notebook with at least one entry."""
    if not JOURNAL.is_dir():
        return []
    return sorted({str(p.parent.relative_to(JOURNAL)) for p in JOURNAL.rglob("*.json")})


def _models_label(entry: dict[str, Any]) -> str:
    """The models that answered a run, as one short line, for grouping runs."""
    parts = sorted({f"{m['model']} via {m['provider']}" for m in entry.get("models", [])
                    if m["role"] != "embeddings" or m["provider"] != "this machine"})
    return "; ".join(parts) or "no remote model"


def _fmt(value: float) -> str:
    if value == int(value):
        return f"{value:,.0f}"
    return f"{value:.3g}" if abs(value) < 1 else f"{value:,.2f}"


def flapping(runs: list[dict[str, Any]]) -> list[str]:
    """Claims that held in some completed runs and not in others."""
    seen: dict[str, set[bool]] = {}
    for run in runs:
        for name, held in (run.get("claims") or {}).items():
            seen.setdefault(name, set()).add(held)
    return sorted(name for name, results in seen.items() if len(results) > 1)


def summary(name: str) -> str:
    """Plain-text account of every run of one notebook: claims first, then measures."""
    runs = entries(name)
    if not runs:
        return f"{name}: no journaled runs"
    done = [r for r in runs if r.get("status") == "ok"]
    kinds = {k: sum(r["kind"] == k for r in runs) for k in ("ship", "trial")}
    failed = len(runs) - len(done)
    lines = [f"{name}: {len(runs)} run{'s' if len(runs) != 1 else ''} "
             f"({kinds['ship']} ship, {kinds['trial']} trial"
             f"{f', {failed} failed' if failed else ''}), "
             f"{runs[0]['run_at'][:10]} to {runs[-1]['run_at'][:10]}"]

    groups = sorted({_models_label(r) for r in done})
    if len(groups) > 1:
        lines.append("  models differed between runs:")
        lines += [f"    [{i}] {g}" for i, g in enumerate(groups, 1)]
    elif groups:
        lines.append(f"  models: {groups[0]}")

    claims = sorted({c for r in done for c in (r.get("claims") or {})})
    flaps = set(flapping(done))
    if claims:
        lines.append("  claims")
        width = max(map(len, claims))
        for claim in claims:
            results = [r["claims"][claim] for r in done if claim in (r.get("claims") or {})]
            held = sum(results)
            mark = "  FLAPPING" if claim in flaps else ("  never held" if not held else "")
            lines.append(f"    {claim:<{width}}  held {held} of {len(results)}{mark}")

    measures = sorted({m for r in done for m in (r.get("measures") or {})})
    if measures:
        width = max(len("measures") - 2, *map(len, measures))
        lines.append(f"  {'measures':<{width + 2}}  {'last':>9} {'min':>9} {'median':>9} {'max':>9}  runs")
        for measure in measures:
            values = [r["measures"][measure] for r in done
                      if (r.get("measures") or {}).get(measure) is not None]
            if not values:
                continue
            row = (values[-1], min(values), statistics.median(values), max(values))
            lines.append(f"    {measure:<{width}}  " + " ".join(f"{_fmt(v):>9}" for v in row)
                         + f"  {len(values)}")
            if len(groups) > 1:
                for i, group in enumerate(groups, 1):
                    mine = [r["measures"][measure] for r in done if _models_label(r) == group
                            and (r.get("measures") or {}).get(measure) is not None]
                    if mine:
                        lines.append(f"      [{i}] median {_fmt(statistics.median(mine))} over {len(mine)}")

    tokens = [sum(m.get("completion_tokens", 0) for m in r.get("models", []) if m["role"] == "chat")
              / max(sum(m["calls"] - m.get("cached", 0) for m in r.get("models", []) if m["role"] == "chat"), 1)
              for r in done if any(m["role"] == "chat" for m in r.get("models", []))]
    if tokens:
        lines.append("  chat completion tokens per call, by run: "
                     + ", ".join(f"{t:.0f}" for t in tokens))

    errors = {k: v for r in done[-1:] for k, v in (r.get("errors") or {}).items()}
    if errors:
        lines.append("  could not evaluate, last run:")
        lines += [f"    {k}: {v}" for k, v in sorted(errors.items())]
    for run in runs:
        if run.get("status") == "failed":
            lines.append(f"  failed {run['run_at'][:16]} at code cell {run.get('failed_cell')}")
    return "\n".join(lines)
