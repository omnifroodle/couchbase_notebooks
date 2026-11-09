"""What a model charges per token, read live from the provider's public price list.

A notebook that compares models on cost has to price their calls somewhere, and
a hard-coded table goes stale the week it is written. OpenRouter and NanoGPT
both publish every model's list price without a key, so this reads it from
whichever of them the reader has configured.

The arithmetic stays in the notebook, where a reader can see it::

    dollars = prompt_tokens * price.prompt + completion_tokens * price.completion

Reasoning tokens are part of ``completion_tokens`` and billed at the output
price. List prices ignore prompt-cache discounts and per-host differences, so
this is what the calls cost at list, not necessarily what an invoice says.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

__all__ = ["Price", "decision_prices", "list_prices", "openrouter_prices"]

#: Where each provider publishes chat-model prices, and where it publishes the
#: prices of decision models, which a plain chat listing leaves out.
SOURCES = {
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1/models",
                   "https://openrouter.ai/api/v1/models?output_modalities=decisions"),
    "nanogpt": ("NanoGPT", "https://nano-gpt.com/api/v1/models?detailed=true",
                "https://nano-gpt.com/api/v1/decision-models"),
}

MODELS_URL = SOURCES["openrouter"][1]


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


def _per_token(entry: dict) -> tuple[float, float]:
    """One listing's prices in dollars per token, whichever way the provider quotes them.

    OpenRouter quotes dollars per token as strings. NanoGPT quotes dollars per
    million tokens and says so in a ``unit`` field.
    """
    pricing = entry.get("pricing") or {}
    scale = 1e-6 if pricing.get("unit") == "per_million_tokens" else 1.0
    return float(pricing.get("prompt") or 0) * scale, float(pricing.get("completion") or 0) * scale


def _read(url: str, label: str, models: list[str], timeout: float) -> dict[str, Price]:
    import httpx

    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    listed = {entry["id"]: entry for entry in response.json()["data"]}

    prices = {}
    for model in models:
        if model not in listed:
            near = difflib.get_close_matches(model, list(listed), n=5, cutoff=0.5)
            hint = f" Closest listed: {', '.join(near)}." if near else ""
            raise KeyError(f"{label} does not list a model called {model!r}.{hint}")
        prices[model] = Price(model, *_per_token(listed[model]))
    return prices


def _source(provider: str, what: str) -> tuple[str, str]:
    if provider not in SOURCES:
        raise KeyError(
            f"No public price list is known for provider {provider!r} (known: "
            f"{', '.join(sorted(SOURCES))}). Give the prices yourself: "
            f"Price('model-id', dollars_per_input_token, dollars_per_output_token)."
        )
    label, chat, decisions = SOURCES[provider]
    return label, chat if what == "chat" else decisions


def list_prices(provider: str, models: list[str], *, timeout: float = 20.0) -> dict[str, Price]:
    """List prices for chat ``models``, by the model id ``provider`` uses.

    Raises ``KeyError`` naming the closest ids when one is not listed, because a
    model id that has been renamed or retired is the usual reason.
    """
    label, url = _source(provider, "chat")
    return _read(url, label, models, timeout)


def decision_prices(provider: str, models: list[str], *, timeout: float = 20.0) -> dict[str, Price]:
    """List prices for decision ``models``. Only input tokens are billed."""
    label, url = _source(provider, "decisions")
    return _read(url, label, models, timeout)


def openrouter_prices(models: list[str], *, timeout: float = 20.0) -> dict[str, Price]:
    """List prices for ``models``, by OpenRouter model id."""
    return list_prices("openrouter", models, timeout=timeout)
