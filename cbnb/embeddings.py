"""Text embeddings, from a local model or an OpenAI-compatible endpoint.

The default is a local sentence-transformers model: no API key, no per-call
cost, and small enough that a Colab CPU runtime encodes a few thousand strings
in seconds. Switch to the API backend when you would rather not download a
model, or when you want embeddings from the same provider as your LLM.

Vectors are always L2-normalised, so a dot product is a cosine similarity --
which is also what a Couchbase ``dot_product`` vector index expects.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np

DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder:
    """Encode text to normalised vectors.

    Args:
        backend: ``"local"`` (sentence-transformers) or ``"api"`` (an
            OpenAI-compatible ``/embeddings`` endpoint).
        model: model id. Defaults per backend.
        llm: an existing :class:`cbnb.llm.LLM` to borrow the client from, for
            the ``"api"`` backend.
        cache_dir: where to memoise encoded batches. ``None`` disables caching.
    """

    def __init__(
        self,
        backend: str | None = None,
        model: str | None = None,
        *,
        llm: object | None = None,
        device: str | None = None,
        cache_dir: str | Path | None = "~/.cache/cbnb/embeddings",
    ) -> None:
        self.backend = backend or os.environ.get("CBNB_EMBEDDING_BACKEND", "local")
        if self.backend not in {"local", "api"}:
            raise ValueError(f"backend must be 'local' or 'api', got {self.backend!r}")

        self._llm = llm
        self._model_obj = None
        self._device = device
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

        if self.backend == "local":
            self.model = model or os.environ.get("CBNB_EMBEDDING_MODEL") or DEFAULT_LOCAL_MODEL
        else:
            if llm is None:
                from cbnb.llm import LLM

                self._llm = LLM()
            provider_default = getattr(self._llm.provider, "default_embedding_model", None)  # type: ignore[union-attr]
            self.model = model or os.environ.get("CBNB_EMBEDDING_MODEL") or provider_default or ""
            if not self.model:
                raise ValueError("No embedding model for this provider; pass model=...")

        self._dims: int | None = None

    def __repr__(self) -> str:
        return f"Embedder(backend={self.backend!r}, model={self.model!r}, dims={self._dims})"

    @property
    def dims(self) -> int:
        """Vector width. Encodes one probe string the first time it is asked."""
        if self._dims is None:
            self._dims = int(self.encode(["dimension probe"], cache=False).shape[1])
        return self._dims

    def _load_local(self):
        if self._model_obj is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - guidance, not logic
                raise ImportError(
                    "The local embedding backend needs sentence-transformers. "
                    "Run cbnb.bootstrap(extras=['local-embeddings']), or use "
                    "Embedder(backend='api')."
                ) from exc
            self._model_obj = SentenceTransformer(self.model, device=self._device)
        return self._model_obj

    def _cache_path(self, texts: Sequence[str]) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(
            ("\x00".join(texts) + f"|{self.backend}|{self.model}").encode()
        ).hexdigest()[:32]
        return self.cache_dir / f"{digest}.npy"

    def encode(
        self,
        texts: Iterable[str],
        *,
        batch_size: int = 256,
        cache: bool = True,
        progress: bool = False,
    ) -> np.ndarray:
        """Return an ``(n, dims)`` array of unit-length float32 vectors."""
        items = [t if isinstance(t, str) else str(t) for t in texts]
        if not items:
            return np.zeros((0, self.dims), dtype=np.float32)

        path = self._cache_path(items) if cache else None
        if path is not None and path.exists():
            vectors = np.load(path)
            self._dims = int(vectors.shape[1])
            return vectors

        if self.backend == "local":
            model = self._load_local()
            vectors = model.encode(
                items,
                batch_size=batch_size,
                convert_to_numpy=True,
                show_progress_bar=progress,
            )
        else:
            chunks = []
            for start in range(0, len(items), batch_size):
                chunk = items[start : start + batch_size]
                chunks.extend(self._llm.embed(chunk, model=self.model))  # type: ignore[union-attr]
                if progress:
                    print(f"\r  embedded {min(start + batch_size, len(items))}/{len(items)}",
                          end="", flush=True)
            if progress:
                print()
            vectors = np.array(chunks)

        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.where(norms == 0, 1.0, norms)
        self._dims = int(vectors.shape[1])

        if path is not None:
            np.save(path, vectors)
        return vectors

    def encode_one(self, text: str, *, cache: bool = True) -> np.ndarray:
        """Encode a single string to a 1-D vector."""
        return self.encode([text], cache=cache)[0]


def top_k(query: np.ndarray, matrix: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Brute-force nearest neighbours, for comparing against the database.

    Both arguments must already be normalised, so the dot product is a cosine
    similarity. Returns ``(row_index, score)`` pairs, best first.
    """
    scores = matrix @ query
    if k >= len(scores):
        order = np.argsort(-scores)
    else:
        top = np.argpartition(-scores, k)[:k]
        order = top[np.argsort(-scores[top])]
    return [(int(i), float(scores[i])) for i in order[:k]]
