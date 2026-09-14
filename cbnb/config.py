"""Credentials and connection settings.

Resolution order for every value:

1. an explicit argument,
2. an environment variable,
3. ``.env`` in the repo root (local runs),
4. Colab's secrets manager (``google.colab.userdata``),
5. an interactive prompt -- ``getpass`` for secrets, ``input`` for the rest.

Step 5 is what makes the notebooks work on a stranger's Colab runtime without
anyone editing a config file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from getpass import getpass

from cbnb.bootstrap import in_colab, repo_root

#: Where a value came from, for the "what am I connected to" summary.
_ENV_FILE_LOADED = False


def _load_dotenv_once() -> None:
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return
    _ENV_FILE_LOADED = True
    root = repo_root()
    if root is None:
        return
    env_path = root / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path)


def _colab_secret(name: str) -> str | None:
    if not in_colab():
        return None
    try:
        from google.colab import userdata  # type: ignore[import-not-found]

        return userdata.get(name)
    except Exception:
        # Secret not set, or the notebook was denied access to it.
        return None


def get(
    name: str,
    default: str | None = None,
    *,
    secret: bool = False,
    prompt: str | None = None,
    required: bool = True,
) -> str:
    """Fetch one setting, asking the user only as a last resort."""
    _load_dotenv_once()
    value = os.environ.get(name) or _colab_secret(name)
    if not value and default is not None:
        value = default
    if not value and required:
        label = prompt or name
        if os.environ.get("CBNB_NONINTERACTIVE"):
            # Headless runs (scripts/run_notebook.py) would hang on a prompt.
            raise RuntimeError(f"{name} is not set. Add it to .env ({label}).")
        value = getpass(f"{label}: ") if secret else input(f"{label}: ")
        value = value.strip()
    if value:
        # Cache it so re-running a cell does not re-prompt.
        os.environ[name] = value
    return value or ""


def mask_host(connection_string: str) -> str:
    """Hide the identifying part of a cluster address.

    Notebook outputs get committed and rendered on GitHub, and a Capella
    hostname tells the internet exactly where a cluster is.
    ``couchbases://cb.abc123.cloud.couchbase.com`` becomes
    ``cb.***.cloud.couchbase.com``. Local addresses are shown as-is.
    """
    hosts = connection_string.split("//")[-1].split("?")[0].split("/")[0]
    host = hosts.split(",")[0].split(":")[0].strip()
    if not host:
        return "not set"
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("192.168.") or host.startswith("10."):
        return host
    labels = host.split(".")
    if host.endswith(".cloud.couchbase.com") and len(labels) >= 5:
        return f"{labels[0]}.***.cloud.couchbase.com"
    return "***." + ".".join(labels[-2:]) if len(labels) > 2 else "***"


@dataclass
class Settings:
    """Everything a notebook needs to reach Couchbase and a model provider."""

    cb_connection_string: str = ""
    cb_username: str = ""
    cb_password: str = ""
    cb_bucket: str = "demos"

    llm_provider: str = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    embedding_backend: str = "local"
    embedding_model: str = ""

    extras: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        """One line describing the setup, safe to leave in a published output."""
        host = mask_host(self.cb_connection_string)
        return (
            f"Couchbase: {host} (bucket {self.cb_bucket!r}) | "
            f"LLM: {self.llm_provider}/{self.llm_model or 'default'} | "
            f"embeddings: {self.embedding_backend}"
        )

    def require_couchbase(self) -> Settings:
        """Prompt for any missing Couchbase credential. Call before connecting."""
        self.cb_connection_string = self.cb_connection_string or get(
            "CB_CONNECTION_STRING",
            prompt="Couchbase connection string (e.g. couchbases://cb.abc123.cloud.couchbase.com)",
        )
        self.cb_username = self.cb_username or get(
            "CB_USERNAME", prompt="Couchbase database access username"
        )
        self.cb_password = self.cb_password or get(
            "CB_PASSWORD", secret=True, prompt="Couchbase database access password"
        )
        self.cb_bucket = self.cb_bucket or get("CB_BUCKET", default="demos")
        return self

    def require_llm(self) -> Settings:
        """Prompt for the model API key if it is still missing."""
        from cbnb.llm import PROVIDERS

        provider = PROVIDERS[self.llm_provider]
        if provider.key_env and not self.llm_api_key:
            self.llm_api_key = get(
                provider.key_env,
                secret=True,
                prompt=f"{provider.label} API key",
                required=provider.key_required,
            )
        return self


def load_settings(**overrides: str) -> Settings:
    """Read settings from the environment without prompting for anything.

    Prompting is deferred to :meth:`Settings.require_couchbase` /
    :meth:`Settings.require_llm` so that importing the package never blocks.
    """
    _load_dotenv_once()

    provider = overrides.get("llm_provider") or os.environ.get("CBNB_LLM_PROVIDER", "openai")
    from cbnb.llm import PROVIDERS

    if provider not in PROVIDERS:
        raise KeyError(f"Unknown LLM provider {provider!r}. Known: {sorted(PROVIDERS)}")
    spec = PROVIDERS[provider]

    cfg = Settings(
        cb_connection_string=os.environ.get("CB_CONNECTION_STRING", ""),
        cb_username=os.environ.get("CB_USERNAME", ""),
        cb_password=os.environ.get("CB_PASSWORD", ""),
        cb_bucket=os.environ.get("CB_BUCKET", "demos"),
        llm_provider=provider,
        llm_base_url=os.environ.get("CBNB_LLM_BASE_URL") or spec.base_url,
        llm_api_key=os.environ.get(spec.key_env, "") if spec.key_env else "",
        llm_model=os.environ.get("CBNB_LLM_MODEL") or spec.default_model,
        embedding_backend=os.environ.get("CBNB_EMBEDDING_BACKEND", "local"),
        embedding_model=os.environ.get("CBNB_EMBEDDING_MODEL", ""),
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg
