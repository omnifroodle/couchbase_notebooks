"""Reranking: a second model that re-scores candidates a search returned.

A retrieval model embeds the query and the document *separately*, which is what
makes search fast -- every document vector is computed once, long before anyone
searches. A **cross-encoder** gives that up on purpose: it reads the query and
one document together, in one forward pass, and returns a relevance score. No
document vector can be precomputed, so it can only ever run over a shortlist,
and the shortlist is what a Couchbase search is for.

That is the whole shape of "retrieve wide, rerank narrow", and the reason this
module has no index and no store: it never sees the corpus, only the handful of
candidates handed to it.

Not to be confused with the ``rerank`` argument on Couchbase's Hyperscale Vector
indexes, which re-scores quantised results against full-precision vectors. Same
word, different job: that one recovers arithmetic the index gave up, and no
second opinion about relevance is involved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["DEFAULT_MODEL", "Reranker", "Scored"]

#: Small, fast, and trained for exactly this: scoring (query, passage) pairs.
#: Trained on MS MARCO, which WANDS and CUAD are not, so the benchmarks in this
#: repo are not part of its training data.
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass(frozen=True)
class Scored:
    """One candidate, with the score the cross-encoder gave it."""

    id: str
    score: float
    text: str
    #: Where this candidate sat before reranking, 1-based.
    was_rank: int


class Reranker:
    """A cross-encoder, loaded once and applied to shortlists.

    Args:
        model: any cross-encoder on the Hugging Face hub.
        max_length: tokens per (query, document) pair. Product names are short;
            passages of prose need more, and pay for it in time.
        batch_size: pairs scored per forward pass.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_length: int = 256,
        batch_size: int = 32,
    ) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model
        self.batch_size = batch_size
        self._model = CrossEncoder(model, max_length=max_length)

    def __repr__(self) -> str:
        return f"Reranker({self.model_name!r})"

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        """Relevance of each text to the query. Higher is better."""
        if not texts:
            return []
        pairs = [(query, text) for text in texts]
        scores = self._model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        return [float(s) for s in scores]

    def rank(
        self,
        query: str,
        candidates: Sequence[Any],
        *,
        fields: Sequence[str] = ("text",),
        k: int | None = None,
        separator: str = " | ",
    ) -> list[Scored]:
        """Reorder search hits by cross-encoder score, best first.

        ``candidates`` are hits from a Couchbase search -- anything with ``id``
        and the named fields. The returned order is the reranker's alone: the
        retrieval score is not blended in, so a comparison against the original
        ranking stays readable.

        ``fields`` is worth thinking about rather than accepting. The model can
        only judge what it is given, so a short title and the same title plus its
        category are different experiments with the same model.
        """
        texts = [
            separator.join(str(c.fields.get(f, "")) for f in fields if c.fields.get(f))
            for c in candidates
        ]
        scores = self.score(query, texts)
        scored = [
            Scored(id=c.id, score=score, text=text, was_rank=rank)
            for rank, (c, text, score) in enumerate(zip(candidates, texts, scores, strict=True), 1)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k] if k else scored
