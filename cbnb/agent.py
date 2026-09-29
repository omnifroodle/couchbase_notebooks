"""The loop an agent runs in: retrieve, judge, adjust, retry.

An agentic search system is a *harness* — a step loop, a budget, a stopping rule
and a trace — with a policy inside it deciding what to do next. This module is
the harness. The policy lives in the notebook, because deciding when a result set
is good enough is the technique, and a reader who cannot see that decision has
learned nothing.

**This module imports nothing but the standard library.** Not :mod:`cbnb.llm`,
not :mod:`cbnb.decisions`, not ``couchbase``. If it imported either model client
the policy seam would be fake: the harness would know which kind of policy it was
serving, and swapping one for another would stop being a fair comparison. That
rule is the whole design, and it is why there is no prompt, no threshold, no
action name and no metric anywhere below.

A notebook supplies three things:

* ``act(action) -> observation`` — do the search, return what came back.
* ``policy(state) -> Move`` — look at what came back, decide whether to stop.
* an :class:`Action` vocabulary, which is any dict the two of them agree on.

and gets back a :class:`Trace`: every step, every decision, what it cost, and why
it stopped. :func:`trace_documents` turns traces into documents so a notebook can
store them and query what the agent actually did.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = ["Budget", "Move", "State", "Step", "Trace", "run", "run_all", "trace_documents"]

#: Whatever the notebook's ``act`` understands. ``{"kind": ...}`` by convention,
#: because :class:`Trace` groups steps by it and a missing key reads as ``None``.
Action = dict[str, Any]

#: Whatever ``act`` returns. ``ids`` is read by default; ``cost`` if present.
#: A key starting with ``_`` is working data — the policy reads it, and
#: :meth:`Trace.to_document` drops it. That is where retrieved text belongs: a
#: policy cannot judge a result set it has not seen, and a trace store does not
#: want a copy of the corpus.
Observation = dict[str, Any]


@dataclass(frozen=True)
class Budget:
    """What one task may spend before the loop gives up.

    Mechanism, not policy: the numbers belong to the notebook that sets them.

    ``max_seconds`` and ``max_cost`` stop the loop once they are passed; they
    cannot cap a spend already made, because neither is known until the step has
    run. ``max_steps`` is the only hard limit, and the only one worth relying on
    to bound a bill.
    """

    max_steps: int = 3
    max_seconds: float = 30.0
    max_cost: float = 0.01

    def spent(self, *, steps: int, seconds: float, cost: float) -> str | None:
        """Why this task must stop, or ``None`` to continue.

        A string rather than a bool, because *which* limit ran out is the
        interesting part — a loop that always ends on ``budget:steps`` is a loop
        whose policy never decides anything.
        """
        if steps >= self.max_steps:
            return "budget:steps"
        if seconds >= self.max_seconds:
            return "budget:seconds"
        if cost >= self.max_cost:
            return "budget:cost"
        return None


@dataclass
class Step:
    """One pass through the loop: an action, what it returned, what followed."""

    n: int
    action: Action
    observation: Observation
    #: The ranked list this step produced. Stored per step, never just at the
    #: end, because "did this action help?" is otherwise unanswerable.
    result_ids: list[str]
    #: The :class:`Move` that followed, as a dict. ``None`` on the final step,
    #: where the budget ran out before anyone was asked.
    move: dict[str, Any] | None
    seconds: float
    cost: float


@dataclass(frozen=True)
class State:
    """Everything a policy may look at. Deliberately small."""

    task: str
    action: Action
    observation: Observation
    #: 1-based, and counts the step just completed.
    step: int
    history: tuple[Step, ...]
    #: So a policy can save its cheapest option for last.
    steps_left: int


@dataclass(frozen=True)
class Move:
    """A policy's answer, and the one type every policy must produce.

    The seam. A chat model returning a Pydantic object and a decision model
    returning typed probabilities both end up here; whatever is structurally
    different about them goes in ``evidence``, which the harness stores verbatim
    and never reads. That is what lets a trace record what each model actually
    said instead of flattening both to a lowest common denominator.
    """

    stop: bool
    #: Required when ``stop`` is False.
    action: Action | None = None
    #: The policy's own words, for the trace.
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    #: What asking cost, if the policy knows. Counted against the budget.
    cost: float = 0.0
    seconds: float = 0.0


@dataclass
class Trace:
    """One task, start to finish."""

    task_id: str
    run_id: str
    policy: str
    task: str
    steps: list[Step]
    #: ``satisfied`` — the policy stopped;
    #: ``budget:steps`` / ``budget:seconds`` / ``budget:cost`` — it ran out;
    #: ``no_move`` — it proposed something already tried;
    #: ``error`` — ``act`` or the policy raised, and ``meta["error"]`` says what.
    stopped: str
    started_at: str
    seconds: float
    cost: float
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def final_ids(self) -> list[str]:
        """The ranked list the task ended with."""
        return self.steps[-1].result_ids if self.steps else []

    @property
    def n_steps(self) -> int:
        return len(self.steps)

    def to_document(self) -> dict[str, Any]:
        """The trace as a document, ready to store.

        Carries no score. A metric computed during the run and stored beside the
        trace is a number nobody can check; the rankings are here, so whoever
        reads the traces can score them in front of their reader.

        Observation keys starting with ``_`` are dropped — see
        :data:`Observation`.
        """
        def step_document(step: Step) -> dict[str, Any]:
            record = asdict(step)
            record["observation"] = {k: v for k, v in step.observation.items()
                                     if not k.startswith("_")}
            return record

        return {
            "type": "traces",
            "run_id": self.run_id,
            "task_id": self.task_id,
            "policy": self.policy,
            "task": self.task,
            "started_at": self.started_at,
            "seconds": round(self.seconds, 3),
            "cost": self.cost,
            "stopped": self.stopped,
            "n_steps": self.n_steps,
            "final_ids": self.final_ids,
            "steps": [step_document(step) for step in self.steps],
            **self.meta,
        }


def _default_ids(observation: Observation) -> list[str]:
    return [str(i) for i in observation.get("ids", [])]


def run(
    task_id: str,
    task: str,
    *,
    start: Action,
    act: Callable[[Action], Observation],
    policy: Callable[[State], Move],
    ids: Callable[[Observation], list[str]] = _default_ids,
    budget: Budget | None = None,
    run_id: str = "",
    policy_name: str = "",
    **meta: Any,
) -> Trace:
    """Run one task to a stop, and return what happened.

    ``start`` always runs: there is no decision to make before there are results
    to judge. After each step the budget is checked *before* the policy is asked,
    so a three-step budget costs at most two policy calls — worth knowing when
    the policy is the expensive part.

    Neither ``act`` nor ``policy`` may take the whole run down. An exception from
    either ends this task with ``stopped="error"`` and returns the partial trace,
    the same bargain :meth:`cbnb.llm.LLM.map` makes: one bad task must not throw
    away the thirty-nine that worked.
    """
    budget = budget or Budget()
    began = time.perf_counter()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    steps: list[Step] = []
    tried: list[Action] = []
    cost = 0.0
    stopped = ""
    action = start

    while True:
        tried.append(action)
        started = time.perf_counter()
        try:
            observation = act(action)
        except Exception as exc:  # noqa: BLE001 - reported on the trace, never raised
            stopped, meta = "error", {**meta, "error": f"{type(exc).__name__}: {exc}"}
            break
        step_cost = float(observation.get("cost") or 0.0)
        cost += step_cost
        steps.append(Step(n=len(steps) + 1, action=action, observation=observation,
                          result_ids=ids(observation), move=None,
                          seconds=time.perf_counter() - started, cost=step_cost))

        stopped = budget.spent(steps=len(steps), seconds=time.perf_counter() - began,
                               cost=cost) or ""
        if stopped:
            break

        try:
            move = policy(State(task=task, action=action, observation=observation,
                                step=len(steps), history=tuple(steps),
                                steps_left=budget.max_steps - len(steps)))
        except Exception as exc:  # noqa: BLE001
            stopped, meta = "error", {**meta, "error": f"{type(exc).__name__}: {exc}"}
            break
        cost += move.cost
        steps[-1].move = asdict(move)

        if move.stop:
            stopped = "satisfied"
            break
        # An agent that proposes what it already tried is looping, not thinking.
        # It gets its own stop reason so a trace store can count how often.
        if move.action is None or move.action in tried:
            stopped = "no_move"
            break
        action = move.action

    return Trace(task_id=task_id, run_id=run_id, policy=policy_name, task=task,
                 steps=steps, stopped=stopped, started_at=started_at,
                 seconds=time.perf_counter() - began, cost=cost, meta=meta)


def run_all(
    tasks: Iterable[tuple[str, str, Action]],
    *,
    max_workers: int = 8,
    **kwargs: Any,
) -> list[Trace]:
    """Run many tasks at once, in order.

    Each task is ``(task_id, task, start)``; everything else is shared and passed
    through to :func:`run`. Pass a per-task ``act`` by closing over it in
    ``act`` itself — see the notebooks, which build one per contract.
    """
    tasks = list(tasks)

    def one(task: tuple[str, str, Action]) -> Trace:
        task_id, text, start = task
        return run(task_id, text, start=start, **kwargs)

    if max_workers <= 1:
        return [one(task) for task in tasks]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(one, tasks))


def trace_documents(traces: Iterable[Trace]) -> dict[str, dict[str, Any]]:
    """``{key: document}`` for a batch of traces, ready for ``upsert_docs``."""
    return {f"trace::{t.run_id}::{t.task_id}": t.to_document() for t in traces}
