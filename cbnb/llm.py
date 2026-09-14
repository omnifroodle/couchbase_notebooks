"""One opinionated LLM client that speaks the OpenAI API to anybody.

Every provider worth using now exposes an OpenAI-compatible ``/chat/completions``
endpoint, so there is exactly one client here and providers differ only by
``base_url``, key name, and how much of the structured-output spec they honour.

Three things this adds over calling ``openai`` directly, all of which matter in
a notebook:

* **Structured output that degrades.** Ask for a Pydantic model; the client
  tries strict ``json_schema``, falls back to ``json_object``, then to plain
  prompting with a schema in the system message, and remembers which rung of
  the ladder your provider actually reached.
* **Retries for flaky replies.** Aggregators route to whichever upstream host is
  free, and some occasionally return ``{}`` or an empty message for a request
  that works fine a second later. Those are retried with backoff before the
  client concludes a mechanism is unsupported.
* **A disk cache.** Notebook cells get re-run. Identical requests are answered
  from ``~/.cache/cbnb/llm`` instead of being paid for twice.
* **Token accounting.** ``llm.usage`` tells you what the demo cost, which is
  usually the point being demonstrated.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class Provider:
    """An OpenAI-API-compatible endpoint."""

    key: str
    label: str
    base_url: str
    key_env: str | None
    default_model: str
    #: Best structured-output mechanism this endpoint is known to support.
    #: One of ``json_schema`` (strict), ``json_object``, ``prompt``.
    structured_mode: str = "json_schema"
    default_embedding_model: str | None = None
    key_required: bool = True
    notes: str = ""


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        key_env="OPENAI_API_KEY",
        default_model="gpt-4.1-mini",
        default_embedding_model="text-embedding-3-small",
    ),
    "nanogpt": Provider(
        key="nanogpt",
        label="NanoGPT",
        base_url="https://nano-gpt.com/api/v1",
        key_env="NANOGPT_API_KEY",
        default_model="gpt-4.1-mini",
        structured_mode="json_object",
        default_embedding_model="text-embedding-3-small",
        notes="Aggregator: one key, many upstream models. Structured-output support varies by model.",
    ),
    "openrouter": Provider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
        default_model="openai/gpt-4.1-mini",
        structured_mode="json_object",
    ),
    "groq": Provider(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        key_env="GROQ_API_KEY",
        default_model="llama-3.3-70b-versatile",
        structured_mode="json_object",
    ),
    "anthropic": Provider(
        key="anthropic",
        label="Anthropic (OpenAI-compatible endpoint)",
        base_url="https://api.anthropic.com/v1",
        key_env="ANTHROPIC_API_KEY",
        default_model="claude-haiku-4-5",
        structured_mode="prompt",
        notes=(
            "Anthropic's OpenAI compatibility layer. Fine for these demos; for "
            "production Claude work use the native `anthropic` SDK, which supports "
            "structured outputs, thinking and prompt caching properly."
        ),
    ),
    "ollama": Provider(
        key="ollama",
        label="Ollama (local)",
        base_url="http://localhost:11434/v1",
        key_env=None,
        default_model="llama3.2",
        structured_mode="json_object",
        default_embedding_model="nomic-embed-text",
        key_required=False,
    ),
    "custom": Provider(
        key="custom",
        label="Custom OpenAI-compatible endpoint",
        base_url=os.environ.get("CBNB_LLM_BASE_URL", ""),
        key_env="CBNB_LLM_API_KEY",
        default_model=os.environ.get("CBNB_LLM_MODEL", ""),
        structured_mode="json_object",
        key_required=False,
    ),
}

_MODES = ["json_schema", "json_object", "prompt"]


@dataclass
class Usage:
    """Running token totals, so a notebook can show what a technique costs."""

    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    #: Replies that came back empty or invalid and were retried.
    retries: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __str__(self) -> str:
        return (
            f"{self.calls} API calls ({self.cached_calls} served from cache), "
            f"{self.prompt_tokens:,} prompt + {self.completion_tokens:,} completion tokens, "
            f"{self.seconds:.1f}s"
            + (f", {self.retries} bad replies retried" if self.retries else "")
        )


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic JSON schema acceptable to OpenAI strict mode.

    Strict mode requires every object to set ``additionalProperties: false`` and
    to list every property in ``required``.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema.setdefault("additionalProperties", False)
            props = schema.get("properties")
            if isinstance(props, dict):
                schema["required"] = list(props)
        for value in schema.values():
            _strictify(value)
    elif isinstance(schema, list):
        for item in schema:
            _strictify(item)
    return schema


def _extract_json(text: str) -> str:
    """Pull the first JSON object out of a model response.

    Small models wrap JSON in prose or fences even when told not to; this is the
    difference between a demo that runs and one that raises on cell 12.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    depth = 0
    in_string = False
    escaped = False
    for i, char in enumerate(cleaned[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    return cleaned[start:]


class LLM:
    """A chat client for any OpenAI-compatible endpoint.

    Args:
        provider: key from :data:`PROVIDERS`. Defaults to ``$CBNB_LLM_PROVIDER``
            or ``"openai"``.
        model: model id. Defaults to the provider's ``default_model`` or
            ``$CBNB_LLM_MODEL``.
        api_key: overrides the provider's key environment variable.
        base_url: overrides the provider's base URL.
        temperature: default sampling temperature. ``0`` for classification work.
        max_retries: HTTP-level retries (429s, 5xx, timeouts), handled by the
            ``openai`` SDK with backoff that honours ``Retry-After``.
        attempts: tries per structured-output mechanism when the reply is empty
            or fails validation, before falling back to the next mechanism.
        cache: cache responses on disk. Set ``False`` (or ``CBNB_LLM_CACHE=0``)
            to measure real latency and token usage.
    """

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        cache: bool | None = None,
        cache_dir: str | Path | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
        attempts: int | None = None,
    ) -> None:
        provider = provider or os.environ.get("CBNB_LLM_PROVIDER", "openai")
        if provider not in PROVIDERS:
            raise KeyError(f"Unknown provider {provider!r}. Known: {sorted(PROVIDERS)}")
        self.provider = PROVIDERS[provider]
        self.model = model or os.environ.get("CBNB_LLM_MODEL") or self.provider.default_model
        if not self.model:
            raise ValueError(f"No model set for provider {provider!r}; pass model=...")

        self.base_url = base_url or os.environ.get("CBNB_LLM_BASE_URL") or self.provider.base_url
        key = api_key
        if key is None and self.provider.key_env:
            key = os.environ.get(self.provider.key_env)
        if not key and self.provider.key_required:
            from cbnb.config import get

            key = get(
                self.provider.key_env or "CBNB_LLM_API_KEY",
                secret=True,
                prompt=f"{self.provider.label} API key",
            )
        self.api_key = key or "not-needed"

        self.temperature = temperature
        if attempts is not None:
            self.attempts = attempts
        self.usage = Usage()
        self._mode = self.provider.structured_mode
        self._cache_dir = Path(cache_dir or Path.home() / ".cache" / "cbnb" / "llm")
        if cache is None:
            cache = os.environ.get("CBNB_LLM_CACHE", "1") != "0"
        self._cache_enabled = cache
        if cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

        from openai import OpenAI

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    #: Class-level so an instance created before an autoreload still has it.
    attempts: int = 3

    def __repr__(self) -> str:
        return f"LLM(provider={self.provider.key!r}, model={self.model!r})"

    # ---------------------------------------------------------------- caching

    def _cache_path(self, payload: dict[str, Any]) -> Path:
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        digest = hashlib.sha256(blob).hexdigest()[:32]
        return self._cache_dir / f"{digest}.json"

    def _cache_get(self, path: Path) -> Any | None:
        if not self._cache_enabled or not path.exists():
            return None
        try:
            return json.loads(path.read_text())["response"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _cache_put(self, path: Path, payload: dict[str, Any], response: Any) -> None:
        if not self._cache_enabled:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"request": payload, "response": response}, default=str))
        tmp.replace(path)

    # ------------------------------------------------------------------- chat

    def chat(
        self,
        user: str,
        system: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
        force_refresh: bool = False,
        **kwargs: Any,
    ) -> str:
        """Send one message, get the text back."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "base_url": self.base_url,
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        path = self._cache_path(payload)
        if not force_refresh:
            hit = self._cache_get(path)
            if hit is not None:
                self.usage.cached_calls += 1
                return hit

        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=payload["temperature"],
            max_tokens=max_tokens,
            **kwargs,
        )
        self._record(response, time.perf_counter() - started)
        text = response.choices[0].message.content or ""
        self._cache_put(path, payload, text)
        return text

    def _record(self, response: Any, elapsed: float) -> None:
        self.usage.calls += 1
        self.usage.seconds += elapsed
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.usage.completion_tokens += getattr(usage, "completion_tokens", 0) or 0

    # ------------------------------------------------------- structured output

    def structured(
        self,
        user: str,
        schema: type[M],
        system: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
        force_refresh: bool = False,
    ) -> M:
        """Return a validated instance of ``schema``.

        Walks down the structured-output ladder until something works, and
        remembers the rung so later calls start there.
        """
        json_schema = _strictify(schema.model_json_schema())
        payload = {
            "base_url": self.base_url,
            "model": self.model,
            "system": system,
            "user": user,
            "schema": json_schema,
            "temperature": self.temperature if temperature is None else temperature,
        }
        path = self._cache_path(payload)
        if not force_refresh:
            hit = self._cache_get(path)
            if hit is not None:
                self.usage.cached_calls += 1
                return schema.model_validate(hit)

        from openai import (
            APIConnectionError,
            APITimeoutError,
            BadRequestError,
            InternalServerError,
            RateLimitError,
            UnprocessableEntityError,
        )
        from pydantic import ValidationError

        # Still failing after the SDK's own HTTP retries: worth another go.
        transient = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
        # The endpoint rejected the request shape -- this mechanism is unsupported.
        unsupported = (BadRequestError, UnprocessableEntityError)
        # Anything else (bad key, unknown model, ...) is raised as-is.

        start_at = _MODES.index(self._mode)
        last_error: Exception | None = None
        for mode in _MODES[start_at:]:
            for attempt in range(self.attempts):
                if attempt:
                    time.sleep(min(2**attempt, 10))
                try:
                    text = self._call_structured(
                        mode,
                        user=user,
                        system=system,
                        schema=schema,
                        json_schema=json_schema,
                        temperature=payload["temperature"],
                        max_tokens=max_tokens,
                    )
                except unsupported as exc:
                    last_error = exc
                    break
                except transient as exc:
                    last_error = exc
                    continue
                try:
                    parsed = schema.model_validate_json(_extract_json(text))
                except ValidationError as exc:
                    # Empty message, "{}", or truncated JSON. Usually a flaky
                    # upstream rather than an unsupported mechanism.
                    last_error = exc
                    self.usage.retries += 1
                    continue
                if mode != self._mode:
                    self._mode = mode
                self._cache_put(path, payload, parsed.model_dump())
                return parsed

        raise RuntimeError(
            f"{self.provider.label} model {self.model!r} did not return valid "
            f"{schema.__name__} JSON ({self.attempts} attempts per mechanism, "
            f"{', '.join(_MODES[start_at:])}). Last reply error: {last_error}"
        ) from last_error

    def _call_structured(
        self,
        mode: str,
        *,
        user: str,
        system: str | None,
        schema: type[BaseModel],
        json_schema: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> str:
        system_text = system or ""
        kwargs: dict[str, Any] = {}

        if mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": json_schema,
                    "strict": True,
                },
            }
        elif mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
            system_text = (
                f"{system_text}\n\nRespond with a single JSON object matching this "
                f"JSON Schema:\n{json.dumps(json_schema)}"
            ).strip()
        else:  # prompt
            system_text = (
                f"{system_text}\n\nRespond with a single JSON object and nothing else "
                f"-- no prose, no markdown fences. It must match this JSON Schema:\n"
                f"{json.dumps(json_schema)}"
            ).strip()

        messages: list[dict[str, str]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user})

        started = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        self._record(response, time.perf_counter() - started)
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------ batch

    def map(
        self,
        items: Sequence[Any],
        fn: Callable[[Any], Any],
        *,
        max_workers: int = 8,
        progress: bool = True,
    ) -> list[Any]:
        """Run ``fn`` over ``items`` concurrently, preserving order.

        Classifying a few hundred documents one at a time is the slowest part of
        these notebooks; the endpoints are all happy to be called in parallel.

        Every item runs even if some fail, so all the successes are cached; the
        failures are then raised together. Re-running only repeats the failures.
        """
        results: list[Any] = [None] * len(items)
        errors: dict[int, Exception] = {}
        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:  # noqa: BLE001 - collected and re-raised below
                    errors[index] = exc
                done += 1
                if progress and (done % 25 == 0 or done == len(items)):
                    failed = f" ({len(errors)} failed)" if errors else ""
                    print(f"\r  {done}/{len(items)}{failed}", end="", flush=True)
        if progress:
            print()
        if errors:
            listed = "\n".join(f"  - {items[i]!r}: {exc}" for i, exc in list(errors.items())[:5])
            more = f"\n  ... and {len(errors) - 5} more" if len(errors) > 5 else ""
            raise RuntimeError(
                f"{len(errors)} of {len(items)} items failed. The rest succeeded and are "
                f"cached, so re-running this cell only retries these:\n{listed}{more}"
            ) from next(iter(errors.values()))
        return results

    # ------------------------------------------------------------- embeddings

    def embed(self, texts: Iterable[str], model: str | None = None) -> list[list[float]]:
        """Embeddings from the same endpoint, for providers that offer them."""
        model = model or self.provider.default_embedding_model
        if not model:
            raise ValueError(
                f"{self.provider.label} has no default embedding model; pass model=..."
            )
        batch = list(texts)
        response = self.client.embeddings.create(model=model, input=batch)
        return [item.embedding for item in response.data]
