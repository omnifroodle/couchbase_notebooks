"""Which models produced this notebook's results.

A stored output is only as meaningful as the model behind it, and two runs a few
hours apart through the same provider can differ in ways the model name does not
show. So every helper that calls a model records the use here as it happens --
:class:`cbnb.llm.LLM`, :class:`cbnb.embeddings.Embedder`,
:class:`cbnb.rerank.Reranker` and :func:`cbnb.decisions.decide` -- and
:func:`run_card` reports what was actually used, not what was configured.

Records last for the kernel's lifetime, the same as the results they describe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

__all__ = ["Use", "record", "reset", "run_card", "uses"]

#: Card order, and the label each role is shown under.
ROLES = {
    "chat": "Chat model",
    "embeddings": "Embeddings",
    "reranker": "Reranker",
    "decisions": "Decision model",
}

#: What one recorded use counts, per role.
UNITS = {"chat": "call", "embeddings": "text", "reranker": "pair", "decisions": "call"}

#: Why a routed provider gets a note: the reader cannot see who served the model.
ROUTED_NOTE = ("{providers} {verb} requests on to whichever host serves the model, so what "
               "answered may be a quantised or otherwise modified build of it.")


@dataclass
class Use:
    """One model, through one provider, in one role."""

    role: str
    model: str
    provider: str
    routed: bool = False
    calls: int = 0
    cached: int = 0
    #: Model names the provider reported back, when they differ from ``model``.
    served: set[str] = field(default_factory=set)


#: The provider name for a model that runs in this kernel.
LOCAL = "this machine"

_USES: dict[tuple[str, str, str], Use] = {}


def record(
    role: str,
    model: str,
    provider: str,
    *,
    routed: bool = False,
    cached: bool = False,
    served: str | None = None,
    calls: int = 1,
) -> None:
    """Note that ``model`` answered ``calls`` requests in ``role``.

    ``cached`` marks an answer read back from a cache: still this model's work,
    but from an earlier run. ``served`` is the model name the provider reported,
    if it said one.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}, not {role!r}")
    use = _USES.setdefault((role, model, provider), Use(role, model, provider, routed))
    use.calls += calls
    if cached:
        use.cached += calls
    if served and served != model:
        use.served.add(served)


def uses() -> list[Use]:
    """Everything recorded so far, in card order."""
    order = list(ROLES)
    return sorted(_USES.values(), key=lambda u: (order.index(u.role), u.model, u.provider))


def reset() -> None:
    """Forget everything recorded. For tests; a notebook never needs it."""
    _USES.clear()


def run_card():
    """A card naming every model that produced this notebook's results.

    The last cell of every notebook that uses one. Rows come from what ran, so a
    model swapped in halfway through shows up, and a configured one that was
    never called does not.
    """
    from cbnb.readout import RunCard

    rows, routed = [], []
    for use in uses():
        detail = ["on this machine" if use.provider == LOCAL else f"via {use.provider}"]
        unit = UNITS[use.role]
        detail.append(f"{use.calls:,} {unit}{'s' if use.calls != 1 else ''}")
        if use.cached:
            detail[-1] += f", {use.cached:,} from cache"
        if use.served:
            detail.append(f"served as {', '.join(sorted(use.served))}")
        rows.append((ROLES[use.role], use.model, "; ".join(detail)))
        if use.routed and use.provider not in routed:
            routed.append(use.provider)

    notes = []
    if routed:
        notes.append(ROUTED_NOTE.format(providers=" and ".join(routed),
                                        verb="pass" if len(routed) > 1 else "passes"))
    if any(use.cached for use in uses()):
        notes.append("Cached results came from an earlier run of the same model.")
    if not rows:
        notes.append("No model was called in this run.")

    # UTC, like the ship stamp's shipped_at, so the two agree.
    today = datetime.now(timezone.utc).date().isoformat()
    data = {
        "date": today,
        "uses": [{"role": u.role, "model": u.model, "provider": u.provider, "routed": u.routed,
                  "calls": u.calls, "cached": u.cached, "served": sorted(u.served)}
                 for u in uses()],
    }
    return RunCard(f"The results above came from these models · {today}", rows, notes, data)
