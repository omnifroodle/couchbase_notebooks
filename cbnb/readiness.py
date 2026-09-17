"""What can this environment actually do?

Every notebook declares the capabilities it needs. This module answers whether
they are available, and says what to do about it when they are not.

Two depths, because they serve different callers:

*shallow*
    Is it plausibly configured? Settings present, packages importable. Cheap,
    no network. :func:`cbnb.bootstrap` uses this so a notebook fails in cell 1
    with a sentence a reader can act on, rather than in cell 12 with a
    ``KeyError``.

*deep*
    Does it actually work? A real connection, a real API call. Slower and
    occasionally costs a fraction of a cent. ``00_check_setup`` uses this,
    because a shallow check reports green for an API key that the provider has
    revoked -- which is exactly the failure that is expensive to diagnose.

This module knows nothing about notebooks. :mod:`cbnb.inventory` knows about
notebooks and nothing about capabilities. They meet in ``00_check_setup``.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "CAPABILITIES",
    "Capability",
    "NotReady",
    "Result",
    "check",
    "report",
    "require",
]


class NotReady(RuntimeError):
    """A capability a notebook asked for is not available here."""

    def __init__(self, capability: str, detail: str, fix: str) -> None:
        self.capability = capability
        self.detail = detail
        self.fix = fix
        super().__init__(f"{capability}: {detail}\n  Fix: {fix}")


@dataclass(frozen=True)
class Result:
    """The verdict on one capability."""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    deep: bool = False

    @property
    def mark(self) -> str:
        return "ok" if self.ok else "--"


@dataclass(frozen=True)
class Capability:
    """One named thing a notebook can require."""

    name: str
    label: str
    #: Returns (ok, detail, fix). Must not raise, must not prompt.
    shallow: Callable[[], tuple[bool, str, str]]
    #: Same contract, but allowed to open connections and spend a little money.
    deep: Callable[[], tuple[bool, str, str]] | None = None
    #: bootstrap extras this capability implies.
    extras: tuple[str, ...] = ()


# --- helpers ---------------------------------------------------------------

def _settings():
    from cbnb.config import load_settings

    return load_settings()


def _fix_setting(*names: str) -> str:
    """How to supply a missing setting, phrased for wherever this is running."""
    from cbnb.bootstrap import in_codespaces, in_colab

    listed = ", ".join(names)
    if in_colab():
        return f"add {listed} in the Colab secrets panel (the key icon), then re-run this cell"
    if in_codespaces():
        return (f"add {listed} at https://github.com/settings/codespaces, then stop and "
                "restart the codespace (a running one does not see new secrets)")
    return f"add {listed} to the repo's .env file (copy .env.example), then restart the kernel"


# --- couchbase -------------------------------------------------------------

def _couchbase_shallow() -> tuple[bool, str, str]:
    cfg = _settings()
    missing = [
        name for name, value in (
            ("CB_CONNECTION_STRING", cfg.cb_connection_string),
            ("CB_USERNAME", cfg.cb_username),
            ("CB_PASSWORD", cfg.cb_password),
        )
        if not value
    ]
    if missing:
        return False, f"not configured ({', '.join(missing)} unset)", _fix_setting(*missing)
    from cbnb.config import mask_host

    return True, f"configured for {mask_host(cfg.cb_connection_string)}", ""


def _couchbase_deep() -> tuple[bool, str, str]:
    ok, detail, fix = _couchbase_shallow()
    if not ok:
        return ok, detail, fix
    cfg = _settings()
    from cbnb.config import mask_host

    try:
        from cbnb.couchbase_io import connect

        cluster = connect(cfg)
        bucket = cluster.bucket(cfg.cb_bucket)
        bucket.ping()
    except Exception as exc:  # noqa: BLE001 - every failure here is reportable
        first = str(exc).strip().splitlines()[0]
        return False, f"cannot reach {mask_host(cfg.cb_connection_string)}: {first}", (
            "check the cluster is running, your IP is on its allow list, and the database "
            "access user is right -- see docs/capella-setup.md"
        )
    return True, f"connected to {mask_host(cfg.cb_connection_string)}, bucket {cfg.cb_bucket!r}", ""


# --- llm -------------------------------------------------------------------

def _split_auth_help(exc: Exception) -> tuple[str, str]:
    """Turn ``LLM._auth_help`` text into (detail, fix).

    Its first line already says what went wrong, which is the detail; the rest is
    what to do about it. Repeating the first line in both reads like a stutter.
    """
    lines = str(exc).strip().splitlines()
    detail = lines[0] if lines else "the provider rejected the API key"
    return detail, "\n".join(lines[1:]).strip()


def _llm_shallow() -> tuple[bool, str, str]:
    cfg = _settings()
    from cbnb.llm import PROVIDERS

    provider = PROVIDERS[cfg.llm_provider]
    if provider.key_required and not cfg.llm_api_key:
        name = provider.key_env or "CBNB_LLM_API_KEY"
        return False, f"no API key for {provider.label} ({name} unset)", _fix_setting(name)
    return True, f"{provider.label} / {cfg.llm_model or 'default model'}, key present", ""


def _llm_deep() -> tuple[bool, str, str]:
    ok, detail, fix = _llm_shallow()
    if not ok:
        return ok, detail, fix
    cfg = _settings()
    from cbnb.llm import LLM, LLMAuthenticationError

    try:
        llm = LLM(cfg.llm_provider, model=cfg.llm_model)
        # force_refresh: a cached reply would prove nothing about the key.
        llm.chat("Reply with the single word: ok", max_tokens=5, force_refresh=True)
    except LLMAuthenticationError as exc:
        # _auth_help already explains this one properly; don't truncate it.
        return (False, *_split_auth_help(exc))
    except Exception as exc:  # noqa: BLE001
        return False, f"{cfg.llm_provider} call failed: {str(exc).strip().splitlines()[0]}", (
            "check the provider is up and the model name is one your account can use"
        )
    return True, f"{cfg.llm_provider} answered as {cfg.llm_model or 'default model'}", ""


# --- embeddings ------------------------------------------------------------

def _local_embeddings_shallow() -> tuple[bool, str, str]:
    if importlib.util.find_spec("sentence_transformers") is None:
        return False, "sentence-transformers is not installed", (
            "run cbnb.bootstrap(requires=[...]) -- it installs this -- or "
            "pip install sentence-transformers"
        )
    return True, "sentence-transformers installed", ""


def _local_embeddings_deep() -> tuple[bool, str, str]:
    ok, detail, fix = _local_embeddings_shallow()
    if not ok:
        return ok, detail, fix
    try:
        from cbnb.embeddings import Embedder

        embedder = Embedder(backend="local")
        embedder.encode(["a coffee table"])
    except Exception as exc:  # noqa: BLE001
        return False, f"model would not load: {str(exc).strip().splitlines()[0]}", (
            "the first run downloads ~90MB; check disk space and network access to "
            "huggingface.co"
        )
    return True, f"model loaded, {embedder.dims} dimensions", ""


def _api_embedding_model() -> str:
    """The model the api backend would use: CBNB_EMBEDDING_MODEL, else the provider's."""
    cfg = _settings()
    from cbnb.llm import PROVIDERS

    return cfg.embedding_model or PROVIDERS[cfg.llm_provider].default_embedding_model or ""


def _api_embeddings_shallow() -> tuple[bool, str, str]:
    cfg = _settings()
    from cbnb.llm import PROVIDERS

    provider = PROVIDERS[cfg.llm_provider]
    if not _api_embedding_model():
        return False, f"no embedding model known for {provider.label}", (
            "set CBNB_EMBEDDING_MODEL to one the endpoint serves, or use "
            "CBNB_EMBEDDING_BACKEND=local"
        )
    return _llm_shallow()


def _api_embeddings_deep() -> tuple[bool, str, str]:
    ok, detail, fix = _api_embeddings_shallow()
    if not ok:
        return ok, detail, fix
    cfg = _settings()
    from cbnb.llm import LLM, LLMAuthenticationError

    try:
        model = _api_embedding_model()
        vectors = LLM(cfg.llm_provider).embed(["a coffee table"], model=model)
    except LLMAuthenticationError as exc:
        return (False, *_split_auth_help(exc))
    except Exception as exc:  # noqa: BLE001
        return False, f"embedding call failed: {str(exc).strip().splitlines()[0]}", (
            "check the provider offers embeddings on your plan, and that "
            f"{cfg.llm_provider} serves the embedding model you asked for"
        )
    return True, f"{cfg.llm_provider} / {model} returned {len(vectors[0])} dimensions", ""


# --- everything else -------------------------------------------------------

def _dataset_download_shallow() -> tuple[bool, str, str]:
    from cbnb.bootstrap import repo_root

    root = repo_root()
    if root is not None and (root / "data").exists():
        return True, "committed samples present; full files download on demand", ""
    return True, "no local data directory; everything downloads on demand", ""


def _dataset_download_deep() -> tuple[bool, str, str]:
    import urllib.error
    import urllib.request

    url = "https://raw.githubusercontent.com/wayfair/WANDS/main/dataset/product.csv"
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            code = response.status
    except urllib.error.URLError as exc:
        return False, f"cannot reach the dataset host: {exc.reason}", (
            "check outbound HTTPS access; behind a proxy, set HTTPS_PROXY"
        )
    return code == 200, f"dataset host reachable (HTTP {code})", ""


def _ram_8gb() -> tuple[bool, str, str]:
    gib = _total_memory_gib()
    if gib is None:
        return True, "could not determine memory; assuming enough", ""
    if gib < 7.0:
        return False, f"{gib:.1f} GiB of RAM", (
            "embedding a large batch may be killed; reduce the sample size, or use a "
            "bigger machine (Codespaces: 4-core or larger)"
        )
    return True, f"{gib:.1f} GiB of RAM", ""


def _total_memory_gib() -> float | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        return None


CAPABILITIES: dict[str, Capability] = {
    c.name: c
    for c in [
        Capability("couchbase", "A reachable Couchbase cluster",
                   _couchbase_shallow, _couchbase_deep),
        Capability("llm", "An OpenAI-compatible model endpoint",
                   _llm_shallow, _llm_deep),
        Capability("local-embeddings", "Embeddings on this machine",
                   _local_embeddings_shallow, _local_embeddings_deep,
                   extras=("local-embeddings",)),
        Capability("api-embeddings", "Embeddings from the model provider",
                   _api_embeddings_shallow, _api_embeddings_deep),
        Capability("dataset-download", "Downloading a full dataset",
                   _dataset_download_shallow, _dataset_download_deep),
        Capability("ram-8gb", "At least 8 GiB of memory", _ram_8gb),
    ]
}


def check(name: str, *, deep: bool = False) -> Result:
    """Test one capability by name."""
    if name not in CAPABILITIES:
        return Result(name, False, "unknown capability",
                      f"known names: {', '.join(sorted(CAPABILITIES))}")
    capability = CAPABILITIES[name]
    probe = (capability.deep or capability.shallow) if deep else capability.shallow
    try:
        ok, detail, fix = probe()
    except Exception as exc:  # noqa: BLE001 - a probe must never break the report
        return Result(name, False, f"check failed: {exc}", "", deep)
    return Result(name, ok, detail, fix, deep and capability.deep is not None)


def report(names: list[str] | None = None, *, deep: bool = True) -> list[Result]:
    """Test several capabilities. Defaults to all of them."""
    return [check(name, deep=deep) for name in (names or sorted(CAPABILITIES))]


def require(names: list[str]) -> None:
    """Raise :class:`NotReady` for the first capability that is not available.

    Shallow checks only -- this runs at the top of every notebook and must stay
    fast and free.
    """
    for name in names:
        result = check(name, deep=False)
        if not result.ok:
            raise NotReady(name, result.detail, result.fix)


def extras_for(names: list[str]) -> list[str]:
    """Bootstrap extras implied by a list of capabilities."""
    extras: list[str] = []
    for name in names:
        for extra in CAPABILITIES[name].extras if name in CAPABILITIES else ():
            if extra not in extras:
                extras.append(extra)
    return extras
