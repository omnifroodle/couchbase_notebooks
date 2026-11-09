"""Fast, typed decisions from a System One model, reached through the reader's provider.

A decision model answers questions about a piece of text ("state") with typed
values instead of generated prose: a yes/no probability, one option from a set,
or a position on a scale. TypeSafe's Jev is the first of these. OpenRouter and
NanoGPT both serve it, and both take the same request body, so this client
speaks that one body to whichever of them the reader has configured.

Three question types, built with :func:`noul`, :func:`choice` and :func:`score`:

* **noul** -- is this true? Answers ``noul``, the probability of yes.
* **choice** -- which of these options? Answers ``choice``, ``probabilities``
  over every option and ``confidence``.
* **score** -- where on this scale? Answers ``score`` (the probability-weighted
  mean of the level numbers), ``probabilities`` per level and ``confidence``.

Every question in one call sees the same state and is answered independently.
Reference: https://docs.typesafe.ai/primitives.md

Which provider answers is :func:`decision_provider`'s choice, from the reader's
own configuration. A provider here has to be one that speaks this body *and* has
been tried; adding one is a row in ``PROVIDERS`` and a live call.

Deliberately separate from :mod:`cbnb.llm`: that client is for chat completions;
this one posts to a decisions endpoint, which a chat client cannot reach.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import cache
from typing import Any

__all__ = ["DEFAULT_MODEL", "PROVIDERS", "Decision", "DecisionError", "choice", "decide",
           "decision_provider", "noul", "score"]

DEFAULT_MODEL = "typesafe/jev-1.13"


@dataclass(frozen=True)
class DecisionProvider:
    """Where one provider serves decision models."""

    key: str
    label: str
    endpoint: str
    key_env: str


#: Keyed like :data:`cbnb.llm.PROVIDERS`, so a reader's chat provider names its own row.
#: OpenRouter's endpoint is an alpha, and says its shape may change.
PROVIDERS: dict[str, DecisionProvider] = {
    "openrouter": DecisionProvider("openrouter", "OpenRouter",
                                   "https://openrouter.ai/api/alpha/decisions", "OPENROUTER_API_KEY"),
    "nanogpt": DecisionProvider("nanogpt", "NanoGPT",
                                "https://nano-gpt.com/api/v1/decisions", "NANOGPT_API_KEY"),
}


def decision_provider(name: str | None = None) -> DecisionProvider:
    """The provider that answers decisions, from the reader's own configuration.

    In order: ``name`` if given; ``CBNB_DECISION_PROVIDER``; the chat provider
    (``CBNB_LLM_PROVIDER``) if it serves decisions; the first provider here with a
    key set. With none of those, OpenRouter, so the error names a key to set.
    """
    from cbnb.config import get

    asked = name or get("CBNB_DECISION_PROVIDER", required=False)
    if asked:
        if asked not in PROVIDERS:
            raise KeyError(f"No decision provider {asked!r}. Known: {sorted(PROVIDERS)}")
        return PROVIDERS[asked]
    chat = get("CBNB_LLM_PROVIDER", required=False)
    if chat in PROVIDERS and get(PROVIDERS[chat].key_env, required=False):
        return PROVIDERS[chat]
    return next((p for p in PROVIDERS.values() if get(p.key_env, required=False)),
                PROVIDERS["openrouter"])


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
    #: Which provider answered: a key of :data:`PROVIDERS`.
    provider: str = ""
    #: 1 unless a timeout or a server error forced a retry.
    attempts: int = 1
    #: Tokens read, as the provider counted them. Output is free and not kept.
    input_tokens: int = 0
    #: What the call cost at list price: ``input_tokens`` times the model's published price.
    #: Zero when no list price could be found, in which case the provider's own figure is in ``usage``.
    cost: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, question_id: str) -> dict[str, Any]:
        return self.answers[question_id]

    def value(self, question_id: str) -> Any:
        """The headline value of one answer: the noul, the choice, or the score.

        A model can decline a question, and the rest of the response still stands.
        Asking for the value of a declined one raises, so the gap is never a silent zero.
        """
        answer = self.answers[question_id]
        if answer["type"] == "refusal":
            raise DecisionError(f"the model declined question {question_id!r}")
        return answer[answer["type"]]


class DecisionError(RuntimeError):
    """The endpoint refused or failed the request. The message says which."""


@cache
def _list_price(provider: str, model: str) -> float:
    """Dollars per input token for ``model``, or 0.0 when the provider does not list one."""
    from cbnb.pricing import decision_prices

    try:
        return decision_prices(provider, [model])[model].prompt
    except Exception:  # noqa: BLE001 -- a price is a convenience; the decision still stands
        return 0.0


def decide(
    state: str,
    questions: dict[str, dict],
    *,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
    timeout: float = 10.0,
    retries: int = 2,
    client: Any = None,
) -> Decision:
    """Ask every question in ``questions`` about ``state`` in one call.

    ``seconds`` is wall-clock time for the successful HTTP round trip, as a
    caller would experience it -- network included. Pass an ``httpx.Client`` as
    ``client`` to reuse one connection across many calls; the first call on a
    fresh connection also pays for the TLS handshake.

    The endpoint is an alpha on OpenRouter, and now and then a request hangs or
    fails with a server error. Those are retried ``retries`` times; ``attempts``
    on the result says whether that happened.
    """
    import httpx

    from cbnb.config import get

    where = decision_provider(provider)
    body = {"model": model, "state": state, "questions": questions}
    headers = {"Authorization": "Bearer " + get(where.key_env, secret=True,
                                                prompt=f"{where.label} API key")}
    owned = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        for attempt in range(1, retries + 2):
            started = time.perf_counter()
            try:
                response = client.post(where.endpoint, json=body, headers=headers, timeout=timeout)
            except httpx.TransportError as exc:
                if attempt > retries:
                    raise DecisionError(
                        f"no response from {where.endpoint} after {attempt} tries: {exc!r}") from exc
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
            f"{where.label} rejected the key (HTTP 401). Check {where.key_env}; it is separate "
            "from whichever key CBNB_LLM_PROVIDER uses unless they are the same provider."
        )
    if response.status_code >= 400:
        raise DecisionError(f"HTTP {response.status_code} from {where.endpoint}: {response.text[:300]}")
    data = response.json()
    if "answers" not in data:
        raise DecisionError(f"no answers in the response: {str(data)[:300]}")
    usage = data.get("usage") or {}
    tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    served = data.get("model", model)

    from cbnb import provenance

    # The response names the dated build that answered; record that, not the alias.
    provenance.record("decisions", served, where.label, routed=True, prompt_tokens=tokens)
    return Decision(
        answers=data["answers"],
        model=served,
        seconds=seconds,
        provider=where.key,
        attempts=attempt,
        input_tokens=tokens,
        cost=tokens * _list_price(where.key, model),
        usage=usage,
        raw=data,
    )
