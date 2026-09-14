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
import os
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
}


def in_colab() -> bool:
    return "google.colab" in sys.modules or "COLAB_RELEASE_TAG" in os.environ


def repo_root() -> Path | None:
    """Directory holding the ``cbnb`` package, when running from a checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "cbnb" / "__init__.py").exists():
            return parent
    return None


def _missing(requirements: list[tuple[str, str]]) -> list[str]:
    missing = []
    for module, requirement in requirements:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(requirement)
    return missing


def _pip_install(requirements: list[str]) -> None:
    print(f"Installing: {', '.join(requirements)}")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *requirements]
    )


def _quiet_model_downloads() -> None:
    """Hide Hugging Face progress bars and token nags.

    They are noise in a live session and worse in a committed output, where
    GitHub renders every carriage-return frame of a progress bar.
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


def bootstrap(extras: list[str] | None = None, quiet: bool = False) -> Settings:  # noqa: F821
    """Install what is missing, load credentials, and return the settings.

    Safe to call repeatedly -- it only installs packages that fail to import.

    Args:
        extras: names from :data:`EXTRA_REQUIREMENTS`, e.g. ``["local-embeddings"]``.
        quiet: suppress the summary line.

    Returns:
        A populated :class:`cbnb.config.Settings`.
    """
    requirements = list(CORE_REQUIREMENTS)
    for extra in extras or []:
        if extra not in EXTRA_REQUIREMENTS:
            raise KeyError(f"Unknown extra {extra!r}. Known: {sorted(EXTRA_REQUIREMENTS)}")
        requirements += EXTRA_REQUIREMENTS[extra]

    missing = _missing(requirements)
    if missing:
        _pip_install(missing)

    root = repo_root()
    if root is not None and str(root) not in sys.path:
        sys.path.insert(0, str(root))

    _quiet_model_downloads()
    autoreload = root is not None and _enable_autoreload()

    from cbnb.config import load_settings

    cfg = load_settings()
    if not quiet:
        where = "Colab" if in_colab() else "local" + (", autoreload on" if autoreload else "")
        print(f"cbnb ready ({where}). {cfg.summary()}")
    return cfg
