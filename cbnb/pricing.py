"""What a model charges per token, read live from OpenRouter's public model list.

A notebook that compares models on cost has to price their calls somewhere, and
a hard-coded table goes stale the week it is written. OpenRouter publishes every
model's list price at ``/api/v1/models``, no key needed, so this reads it.

The arithmetic stays in the notebook, where a reader can see it::

    dollars = prompt_tokens * price.prompt + completion_tokens * price.completion

Reasoning tokens are part of ``completion_tokens`` and billed at the output
price. List prices ignore prompt-cache discounts and per-host differences, so
this is what the calls cost at list, not necessarily what an invoice says.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

__all__ = ["Price", "openrouter_prices"]

MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass(frozen=True)
class Price:
    """US dollars per token, input and output, for one model."""

    model: str
    prompt: float
    completion: float

    @property
    def per_million(self) -> tuple[float, float]:
        """The same prices per million tokens, the way price pages quote them."""
        return self.prompt * 1e6, self.completion * 1e6


def openrouter_prices(models: list[str], *, timeout: float = 20.0) -> dict[str, Price]:
    """List prices for ``models``, by OpenRouter model id.

    Raises ``KeyError`` naming the closest ids when one is not listed, because a
    model id that has been renamed or retired is the usual reason.
    """
    import httpx

    response = httpx.get(MODELS_URL, timeout=timeout)
    response.raise_for_status()
    listed = {entry["id"]: entry.get("pricing") or {} for entry in response.json()["data"]}

    prices = {}
    for model in models:
        if model not in listed:
            near = difflib.get_close_matches(model, list(listed), n=5, cutoff=0.5)
            hint = f" Closest listed: {', '.join(near)}." if near else ""
            raise KeyError(f"OpenRouter does not list a model called {model!r}.{hint}")
        pricing = listed[model]
        prices[model] = Price(model, float(pricing.get("prompt") or 0),
                              float(pricing.get("completion") or 0))
    return prices
