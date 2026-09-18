"""Fast, typed decisions from a System One model, reached through OpenRouter.

A decision model answers questions about a piece of text ("state") with typed
values instead of generated prose: a yes/no probability, one option from a set,
or a position on a scale. TypeSafe's Jev is the first of these. Access is
limited for now, and OpenRouter's alpha ``/decisions`` endpoint is the way in,
so this client speaks that endpoint and nothing else.

Three question types, built with :func:`noul`, :func:`choice` and :func:`score`:

* **noul** -- is this true? Answers ``noul``, the probability of yes.
* **choice** -- which of these options? Answers ``choice``, ``probabilities``
  over every option and ``confidence``.
* **score** -- where on this scale? Answers ``score`` (the probability-weighted
  mean of the level numbers), ``probabilities`` per level and ``confidence``.

Every question in one call sees the same state and is answered independently.
Reference: https://docs.typesafe.ai/primitives.md

Deliberately separate from :mod:`cbnb.llm`: that client is for chat completions
from whichever provider a reader configured; this one always needs an
OpenRouter key, whatever ``CBNB_LLM_PROVIDER`` says.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["DEFAULT_MODEL", "Decision", "choice", "decide", "noul", "score"]

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"
KEY_ENV = "OPENROUTER_API_KEY"


def noul(instructions: str, *, true: str | None = None, false: str | None = None) -> dict:
    """A yes/no question. ``true``/``false`` optionally pin down what each answer means."""
    question: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true is not None or false is not None:
        question["criteria"] = {"true": true or "", "false": false or ""}
    return question


def choice(instructions: str, options: dict[str, str | None]) -> dict:
    """Pick one option. Keys are option names, values describe them (``None`` if obvious)."""
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def score(instructions: str, levels: list[str]) -> dict:
    """Place the state on a scale. ``levels`` run low to high; 2 to 10 of them."""
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


@dataclass
class Decision:
    """One response: the answers by question id, plus what the call cost and took."""

    answers: dict[str, dict[str, Any]]
    model: str
    seconds: float
    #: 1 unless a timeout or a server error forced a retry.
    attempts: int = 1
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, question_id: str) -> dict[str, Any]:
        return self.answers[question_id]

    def value(self, question_id: str) -> Any:
        """The headline value of one answer: the noul, the choice, or the score."""
        answer = self.answers[question_id]
        return answer[answer["type"]]

    @property
    def cost(self) -> float:
        """US dollars, as OpenRouter reported it."""
        return float(self.usage.get("cost") or 0.0)


class DecisionError(RuntimeError):
    """The endpoint refused or failed the request. The message says which."""


def _api_key() -> str:
    from cbnb.config import get

    return get(KEY_ENV, secret=True, prompt="OpenRouter API key")


def decide(
    state: str,
    questions: dict[str, dict],
    *,
    model: str = DEFAULT_MODEL,
    timeout: float = 10.0,
    retries: int = 2,
    client: Any = None,
) -> Decision:
    """Ask every question in ``questions`` about ``state`` in one call.

    ``seconds`` is wall-clock time for the successful HTTP round trip, as a
    caller would experience it -- network included. Pass an ``httpx.Client`` as
    ``client`` to reuse one connection across many calls; the first call on a
    fresh connection also pays for the TLS handshake.

    The endpoint is an alpha, and now and then a request hangs or fails with a
    server error. Those are retried ``retries`` times; ``attempts`` on the result
    says whether that happened.
    """
    import httpx

    body = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {_api_key()}"}
    owned = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        for attempt in range(1, retries + 2):
            started = time.perf_counter()
            try:
                response = client.post(ENDPOINT, json=body, headers=headers, timeout=timeout)
            except httpx.TransportError as exc:
                if attempt > retries:
                    raise DecisionError(f"no response from {ENDPOINT} after {attempt} tries: {exc!r}") from exc
                continue
            seconds = time.perf_counter() - started
            if (response.status_code == 429 or response.status_code >= 500) and attempt <= retries:
                time.sleep(0.5 * attempt)
                continue
            break
    finally:
        if owned:
            client.close()

    if response.status_code == 401:
        raise DecisionError(
            f"OpenRouter rejected the key (HTTP 401). Check {KEY_ENV}; it is separate "
            "from whichever key CBNB_LLM_PROVIDER uses."
        )
    if response.status_code >= 400:
        raise DecisionError(f"HTTP {response.status_code} from {ENDPOINT}: {response.text[:300]}")
    data = response.json()
    if "answers" not in data:
        raise DecisionError(f"no answers in the response: {str(data)[:300]}")
    return Decision(
        answers=data["answers"],
        model=data.get("model", model),
        seconds=seconds,
        attempts=attempt,
        usage=data.get("usage") or {},
        raw=data,
    )
