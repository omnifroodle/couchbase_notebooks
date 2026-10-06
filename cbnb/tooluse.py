"""The loop a tool-calling model runs in: it asks for tools, gets their results, and says when it is done.

:mod:`cbnb.agent` is built for a policy that looks at what an action returned and chooses the
next action. A model with native tool calling does not fit that: its next action *is* its reply,
and it can ask for several tools in one turn. So this is a separate loop, and it leaves
``agent.py`` alone. What it shares is the record. It returns an :class:`cbnb.agent.Trace`, one
:class:`~cbnb.agent.Step` per tool call, so :func:`cbnb.agent.trace_documents` stores the
attempt like any other.

The loop knows nothing about what the tools do. A notebook gives it a model, the tool schemas,
and ``execute(name, arguments) -> dict`` that returns ``{"result": ...}`` or ``{"error": ...}``.

**One optional hook, and it is the whole of the "fix" an experiment may test.** When the model
first says it is finished, the loop calls ``review()``. If that returns text, the text is sent
to the model as a new message and the loop carries on, so the model may change its mind. It runs
once: the second time the model says it is finished, the loop accepts it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from cbnb.agent import Step, Trace

__all__ = ["run"]


def run(
    task_id: str,
    message: str,
    *,
    llm,
    system: str,
    tools: Sequence[dict[str, Any]],
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    writes: frozenset[str] | set[str] = frozenset(),
    review: Callable[[], str | None] | None = None,
    max_turns: int = 14,
    temperature: float | None = None,
    max_tokens: int = 2048,
    run_id: str = "",
    policy_name: str = "",
    **meta: Any,
) -> Trace:
    """Run one task to a stop, and return what happened.

    ``max_turns`` bounds the number of model calls. A turn that asks for three tools is one
    turn and three steps. ``stopped`` on the trace is ``satisfied`` when the model gave a final
    message, ``budget:steps`` when it ran out of turns, ``no_reply`` when the provider returned
    nothing, and ``error`` when the model call raised; ``meta["error"]`` then says what.

    Nothing raised by the model call takes the run down: the partial trace comes back, as with
    :func:`cbnb.agent.run`.
    """
    began = time.perf_counter()
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    messages: list[dict[str, Any]] = [{"role": "system", "content": system},
                                      {"role": "user", "content": message}]
    steps: list[Step] = []
    tokens = {"prompt": 0, "completion": 0, "model_calls": 0}
    final = ""
    stopped = "budget:steps"
    reviewed = False

    for turn in range(1, max_turns + 1):
        try:
            reply = llm.chat_tools(messages, tools, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 - reported on the trace, never raised
            stopped, meta = "error", {**meta, "error": f"{type(exc).__name__}: {exc}"}
            break
        tokens["prompt"] += reply.prompt_tokens
        tokens["completion"] += reply.completion_tokens
        tokens["model_calls"] += 1
        messages.append(reply.message)

        if not reply.tool_calls:
            if not reply.content.strip():
                stopped = "no_reply"
                break
            if review is not None and not reviewed:
                reviewed = True
                prompt = review()
                if prompt:
                    messages.append({"role": "user", "content": prompt})
                    continue
            final, stopped = reply.content, "satisfied"
            break

        for call in reply.tool_calls:
            started = time.perf_counter()
            if call.error:
                outcome = {"error": f"{call.error}; send the arguments as a JSON object"}
            else:
                outcome = execute(call.name, call.arguments)
            action = {"kind": "tool", "name": call.name, "arguments": call.arguments, "turn": turn}
            observation = {"ok": "error" not in outcome, "write": call.name in writes, **outcome}
            steps.append(Step(n=len(steps) + 1, action=action, observation=observation,
                              result_ids=[], move=None,
                              seconds=time.perf_counter() - started, cost=0.0))
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(outcome)})

    return Trace(task_id=task_id, run_id=run_id, policy=policy_name, task=message, steps=steps,
                 stopped=stopped, started_at=started_at, seconds=time.perf_counter() - began,
                 cost=0.0,
                 meta={**meta, "final_message": final, "reviewed": reviewed,
                       "model_calls": tokens["model_calls"],
                       "prompt_tokens": tokens["prompt"],
                       "completion_tokens": tokens["completion"],
                       "messages": messages[2:]})
