"""Shared helpers for the Couchbase demo notebooks.

Everything in here exists so the notebooks stay readable: connection
boilerplate, index management, embeddings and LLM calls live in this package
and the notebooks show only the technique being demonstrated.

Only :func:`bootstrap` and its friends are imported eagerly -- everything else
is resolved on first attribute access, because on a fresh Colab runtime
``bootstrap()`` is what installs the dependencies the other modules need.
"""

from __future__ import annotations

import importlib
from typing import Any

from cbnb.bootstrap import bootstrap, in_colab, repo_root

__version__ = "0.1.0"

_LAZY = {
    "Settings": "cbnb.config",
    "load_settings": "cbnb.config",
    "update_setting": "cbnb.config",
    "Embedder": "cbnb.embeddings",
    "LLM": "cbnb.llm",
    "PROVIDERS": "cbnb.llm",
    "connect": "cbnb.couchbase_io",
    "datasets": "cbnb.datasets",
}

__all__ = ["bootstrap", "in_colab", "repo_root", "__version__", *_LAZY]


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        return module if name == "datasets" else getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
