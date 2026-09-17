"""Environment setup shared by every notebook.

The notebooks run in three places and this module papers over the differences:

* a local checkout with the repo's virtualenv already installed,
* Google Colab (nothing installed, no ``.env`` file, secrets in the Colab
  secrets manager),
* GitHub's notebook viewer, where nothing executes at all and the only thing
  that matters is that stored outputs read well.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

# Packages every notebook needs, as (import name, pip requirement).
CORE_REQUIREMENTS: list[tuple[str, str]] = [
    ("couchbase", "couchbase>=4.6"),
    ("openai", "openai>=1.40"),
    ("numpy", "numpy>=1.24"),
    ("pandas", "pandas>=2.0"),
    ("dotenv", "python-dotenv>=1.0"),
]

# Optional extras a notebook can ask for by name.
EXTRA_REQUIREMENTS: dict[str, list[tuple[str, str]]] = {
    "local-embeddings": [("sentence_transformers", "sentence-transformers>=3.0")],
    "plots": [("matplotlib", "matplotlib>=3.7")],
    # trec_eval bindings for retrieval metrics; wheels, so no compiler needed.
    "metrics": [("ir_measures", "ir-measures>=0.3")],
}


#: Where each setting's value came from, by name -- "the .env file", "a Colab
#: secret", "a prompt in this session". Used to explain a rejected credential. Names only;
#: values are never recorded here.
SETTING_SOURCES: dict[str, str] = {}


def in_colab() -> bool:
    return "google.colab" in sys.modules or "COLAB_RELEASE_TAG" in os.environ


def in_codespaces() -> bool:
    return os.environ.get("CODESPACES") == "true"


def repo_root() -> Path | None:
    """Directory holding the ``cbnb`` package, when running from a checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "cbnb" / "__init__.py").exists():
            return parent
    return None


#: Used only if .env.example cannot be found.
_FALLBACK_SETTING_NAMES = [
    "CB_CONNECTION_STRING", "CB_USERNAME", "CB_PASSWORD", "CB_BUCKET",
    "CBNB_LLM_PROVIDER", "CBNB_LLM_MODEL", "CBNB_LLM_BASE_URL", "CBNB_LLM_API_KEY",
    "OPENAI_API_KEY", "NANOGPT_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY",
    "CBNB_EMBEDDING_BACKEND", "CBNB_EMBEDDING_MODEL",
]


def _setting_names() -> list[str]:
    """Every setting name in .env.example, commented-out ones included."""
    root = repo_root()
    example = root / ".env.example" if root else None
    if example is None or not example.exists():
        return list(_FALLBACK_SETTING_NAMES)
    names = re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", example.read_text(), flags=re.MULTILINE)
    return list(dict.fromkeys(names)) or list(_FALLBACK_SETTING_NAMES)


def _load_colab_secrets() -> list[str]:
    """Copy settings from Colab's secrets manager into the environment.

    Locally, settings come from ``.env``. On Colab they live in the secrets
    manager (the key icon), and everything in ``cbnb`` reads the environment,
    so this is the one place Colab secrets are bridged in. Values already in the
    environment win. Returns the names loaded -- never the values.
    """
    if not in_colab():
        return []
    try:
        from google.colab import userdata  # type: ignore[import-not-found]
    except ImportError:
        return []
    loaded = []
    for name in _setting_names():
        if os.environ.get(name):
            continue
        try:
            value = userdata.get(name)
        except Exception:  # noqa: BLE001 - secret not defined, or access not granted
            continue
        if value:
            os.environ[name] = value
            SETTING_SOURCES[name] = "a Colab secret"
            loaded.append(name)
    return loaded


def _missing(requirements: list[tuple[str, str]]) -> list[str]:
    """Requirements whose module is not installed.

    Uses ``find_spec`` rather than importing: importing sentence-transformers
    pulls in transformers and huggingface_hub, which read their progress-bar
    settings at import time -- before ``bootstrap`` has set them.
    """
    return [req for module, req in requirements if importlib.util.find_spec(module) is None]


def _pip_install(requirements: list[str]) -> None:
    print(f"Installing: {', '.join(requirements)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *requirements]
    )


def _quiet_model_downloads() -> None:
    """Hide Hugging Face progress bars and token nags.

    They are noise in a live session and worse in a committed output. In a
    notebook they also render as Jupyter widgets, which not every front end can
    display -- VS Code in the browser (Codespaces) shows a renderer error.
    """
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    # couchbase 4.6 warns about its *own* internal use of scope_name on every
    # scope-level search. Nothing a caller can fix; keep it out of outputs.
    warnings.filterwarnings("ignore", message=r".*scope_name option is not used.*")
    warnings.filterwarnings("ignore", message=r".*unauthenticated requests to the HF Hub.*")
    import logging

    for name in ("huggingface_hub", "sentence_transformers", "transformers"):
        logging.getLogger(name).setLevel(logging.ERROR)


def _enable_autoreload() -> bool:
    """Reload edited ``cbnb`` modules before each cell, like ``%autoreload 2``.

    Only in a local checkout: that is where you are editing the helpers
    alongside the notebook. Opt out with ``CBNB_AUTORELOAD=0``.
    """
    if in_colab() or os.environ.get("CBNB_AUTORELOAD", "1") == "0":
        return False
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    shell = get_ipython()
    if shell is None:
        return False
    if "autoreload" not in shell.extension_manager.loaded:
        shell.run_line_magic("load_ext", "autoreload")
    shell.run_line_magic("autoreload", "2")
    return True


def bootstrap(
    extras: list[str] | None = None,
    quiet: bool = False,
    requires: list[str] | None = None,
) -> Settings:  # noqa: F821
    """Install what is missing, load credentials, and return the settings.

    Safe to call repeatedly -- it only installs packages that fail to import.

    Args:
        extras: names from :data:`EXTRA_REQUIREMENTS`, e.g. ``["plots"]``. Pure
            installs, with nothing to verify at runtime.
        quiet: suppress the summary line.
        requires: capabilities this notebook needs, from
            :data:`cbnb.readiness.CAPABILITIES` -- e.g.
            ``["couchbase", "llm", "local-embeddings"]``. Anything they imply is
            installed, then checked, so a notebook stops here with an actionable
            message instead of failing ten cells later. Checks are shallow: they
            confirm the setting is present, not that the credential still works.
            ``00_check_setup`` does the live version.

    Returns:
        A populated :class:`cbnb.config.Settings`.

    Raises:
        NotReady: a required capability is unavailable here.
    """
    # First: libraries read these settings when they are imported.
    _quiet_model_downloads()

    requires = list(requires or [])
    from cbnb.readiness import CAPABILITIES, extras_for

    unknown = [name for name in requires if name not in CAPABILITIES]
    if unknown:
        raise KeyError(
            f"Unknown capability {unknown[0]!r}. Known: {', '.join(sorted(CAPABILITIES))}"
        )

    requirements = list(CORE_REQUIREMENTS)
    for extra in [*extras_for(requires), *(extras or [])]:
        if extra not in EXTRA_REQUIREMENTS:
            raise KeyError(f"Unknown extra {extra!r}. Known: {sorted(EXTRA_REQUIREMENTS)}")
        requirements += [r for r in EXTRA_REQUIREMENTS[extra] if r not in requirements]

    missing = _missing(requirements)
    if missing:
        _pip_install(missing)

    root = repo_root()
    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))

    autoreload = root is not None and _enable_autoreload()
    from_colab = _load_colab_secrets()

    from cbnb.config import load_settings

    cfg = load_settings()

    if in_colab():
        where = "Colab"
    else:
        where = "Codespaces" if in_codespaces() else "local"
        where += ", autoreload on" if autoreload else ""
    summary = f"{where}. {cfg.summary()}"
    if from_colab:
        summary += f" | from Colab secrets: {', '.join(from_colab)}"

    from cbnb.readiness import NotReady, check
    from cbnb.readout import Item, Panel

    # After Colab secrets, or this reports settings that are about to arrive.
    # Shallow checks: presence, not validity -- 00_check_setup does the live ones.
    results = [check(name) for name in requires]
    failed = [r for r in results if not r.ok]
    if failed:
        # Show every blocker at once, then stop the notebook on the first.
        Panel(
            f"Not ready: {', '.join(r.name for r in failed)}",
            [("Needs", [Item("ok" if r.ok else "blocked", r.name, r.detail, r.fix)
                        for r in results])],
            summary=summary,
            status="blocked",
        ).show()
        raise NotReady(failed[0].name, failed[0].detail, failed[0].fix)

    if not quiet:
        headline = f"Ready for {' · '.join(requires)}" if requires else "cbnb ready"
        Panel(headline, summary=summary, status="ok").show()
    return cfg
