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

import json
import os
from dataclasses import dataclass, field
from getpass import getpass

from cbnb.bootstrap import SETTING_SOURCES, in_codespaces, in_colab, repo_root

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
        from dotenv import dotenv_values, load_dotenv
    except ImportError:
        return
    already_set = {name for name in dotenv_values(env_path) if os.environ.get(name)}
    load_dotenv(env_path)
    for name in dotenv_values(env_path):
        if name not in already_set and os.environ.get(name):
            SETTING_SOURCES[name] = "the .env file"


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
    value = os.environ.get(name)
    if not value:
        value = _colab_secret(name)
        if value:
            SETTING_SOURCES[name] = "a Colab secret"
    if not value and default is not None:
        value = default
    if not value and required:
        label = prompt or name
        if os.environ.get("CBNB_NONINTERACTIVE"):
            # Headless runs (scripts/run_notebook.py) would hang on a prompt.
            raise RuntimeError(f"{name} is not set. Add it to .env ({label}).")
        value = getpass(f"{label}: ") if secret else input(f"{label}: ")
        value = value.strip()
        SETTING_SOURCES[name] = "a prompt in this session"
    if value:
        # Cache it so re-running a cell does not re-prompt.
        os.environ[name] = value
    return value or ""


_SECRET_SUFFIXES = ("PASSWORD", "API_KEY", "SECRET", "TOKEN")


def setting_source(name: str) -> str:
    """Where a setting's current value came from, in words. Never the value."""
    if name in SETTING_SOURCES and os.environ.get(name):
        return SETTING_SOURCES[name]
    if os.environ.get(name):
        return "a Codespaces secret" if in_codespaces() else "an environment variable"
    return "nowhere (it is not set)"


def how_to_fix_permanently(name: str) -> str:
    """Instructions for correcting a setting at its source, for this environment."""
    source = setting_source(name)
    if in_codespaces():
        return (f"update the {name} secret at https://github.com/settings/codespaces, "
                "then stop and restart the codespace (running codespaces don't see changes)")
    if in_colab():
        return (f"update {name} in the Colab secrets panel (key icon), then "
                "Runtime -> Disconnect and delete runtime, and run from the top")
    if source == "the .env file":
        return f"fix {name} in the repo's .env file, then restart the kernel"
    return (f"put the right value for {name} in the repo's .env file (or wherever you export "
            f"it), then restart the kernel")


def update_setting(name: str) -> None:
    """Re-enter a setting for the rest of this session, e.g. after a rejected API key.

    Secrets (names ending in PASSWORD, API_KEY, SECRET or TOKEN) are read with a
    masked prompt, so the value never lands in the notebook. Anything that already
    read the old value -- an ``LLM()`` or a cluster connection -- needs to be
    created again afterwards.
    """
    if os.environ.get("CBNB_NONINTERACTIVE"):
        raise RuntimeError(f"Cannot prompt for {name} in a headless run; set it in .env instead.")
    secret = name.upper().endswith(_SECRET_SUFFIXES)
    value = (getpass if secret else input)(f"New value for {name}: ").strip()
    if not value:
        print(f"Nothing entered; {name} is unchanged.")
        return
    os.environ[name] = value
    SETTING_SOURCES[name] = "a prompt in this session"
    print(f"{name} updated for this session. Re-run the cell that creates the object using it "
          f"(for an API key, the cell with LLM()). To keep it, "
          f"{how_to_fix_permanently(name)}.")


def setting_descriptions() -> dict[str, str]:
    """A sentence about each setting, by name.

    Read from the ``secrets`` block of ``.devcontainer/devcontainer.json`` -- what
    GitHub shows on the create-a-codespace page -- so every environment describes
    a setting in the same words. Empty if the file is missing.
    """
    root = repo_root()
    path = root / ".devcontainer" / "devcontainer.json" if root else None
    if path is None or not path.exists():
        return {}
    # JSON with comments: every comment in it is a whole line.
    text = "\n".join(line for line in path.read_text().splitlines()
                     if not line.lstrip().startswith("//"))
    try:
        secrets = json.loads(text).get("secrets", {})
    except ValueError:
        return {}
    return {name: spec.get("description", "") for name, spec in secrets.items()
            if isinstance(spec, dict)}


def ask_for_settings(names: list[str], descriptions: dict[str, str] | None = None) -> list[str]:
    """Prompt once for each of *names* that is still unset; return the ones answered.

    Secrets get a masked prompt. Answers last for this session only. A blank
    answer leaves the setting unset, so a reader can skip one and let the
    readiness check say what that costs.
    """
    if descriptions is None:
        descriptions = setting_descriptions()
    answered = []
    for name in names:
        if os.environ.get(name):
            continue
        label = f"{name} -- {descriptions[name]}" if descriptions.get(name) else name
        secret = name.upper().endswith(_SECRET_SUFFIXES)
        try:
            value = (getpass if secret else input)(f"{label}: ").strip()
        except EOFError:
            # No stdin to read from (a plain script under a pipe): stop asking.
            break
        if value:
            os.environ[name] = value
            SETTING_SOURCES[name] = "a prompt in this session"
            answered.append(name)
    return answered


def ask_for_provider() -> str:
    """Ask which model provider to use, before asking for its key.

    The key's name depends on the answer, so this has to come first.
    """
    from cbnb.llm import PROVIDERS

    choices = ", ".join(PROVIDERS)
    while True:
        try:
            answer = input(f"CBNB_LLM_PROVIDER -- one of {choices} [openai]: ")
        except EOFError:
            return os.environ.get("CBNB_LLM_PROVIDER", "openai")
        answer = answer.strip().lower() or "openai"
        if answer in PROVIDERS:
            break
        print(f"{answer!r} is not a known provider.")
    os.environ["CBNB_LLM_PROVIDER"] = answer
    SETTING_SOURCES["CBNB_LLM_PROVIDER"] = "a prompt in this session"
    if answer == "custom":
        ask_for_settings(["CBNB_LLM_BASE_URL", "CBNB_LLM_MODEL"])
    return answer


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
