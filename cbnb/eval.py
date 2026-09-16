"""Retrieval metrics, from the implementation the IR literature reports against.

The arithmetic here is deliberately not ours. ``ir_measures`` wraps ``pytrec_eval``,
which wraps ``trec_eval``: a hand-rolled nDCG that is subtly wrong fails silently
and quietly poisons every claim in the repo, and "our numbers come from
``trec_eval``" is worth more to a sceptical reader than any amount of prose.

What is ours, and stays visible in the notebooks, is the part that is a
judgement call rather than a calculation:

* **which measures to report.** Recall@k and nDCG@k disagree about which system
  is better, and the disagreement is the lesson -- recall is what matters when a
  reranker runs next and only needs the right document somewhere in the pool,
  nDCG is what matters when a person reads the list from the top.
* **how graded labels become gains.** WANDS grades are Exact / Partial /
  Irrelevant. Turning those into 2 / 1 / 0 is a choice that moves the numbers,
  and it belongs in the notebook where a reader can argue with it.

The formulas each measure uses are in ``ir_measures``' own documentation at
https://ir-measur.es/ -- the point of using it is that they are not a mystery.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

__all__ = ["DEFAULT_GAINS", "Run", "compare", "measure_names", "score_run", "to_qrels"]

#: WANDS' three grades as gains. Exact is worth twice a Partial; Irrelevant is
#: worth nothing. Deliberately simple, and deliberately arguable: raise Exact to
#: 3 and every nDCG in the repo moves. Notebooks state the mapping they used.
DEFAULT_GAINS: dict[str, int] = {"Exact": 2, "Partial": 1, "Irrelevant": 0}


@dataclass(frozen=True)
class Run:
    """One retrieval system's results: query id -> ranked (doc id, score)."""

    name: str
    results: Mapping[str, Sequence[tuple[str, float]]]

    def as_dict(self) -> dict[str, dict[str, float]]:
        """The ``{qid: {docid: score}}`` shape ir_measures expects.

        Scores, not ranks: trec_eval sorts by score, so a system whose scores
        descend already ranks correctly.
        """
        return {qid: {str(doc): float(score) for doc, score in hits}
                for qid, hits in self.results.items()}


def to_qrels(
    judgements: Iterable[tuple[str, str, str]],
    gains: Mapping[str, int] | None = None,
) -> dict[str, dict[str, int]]:
    """Graded judgements -> the ``{qid: {docid: gain}}`` trec_eval expects.

    Args:
        judgements: ``(query_id, product_id, label)`` triples.
        gains: label -> gain. Defaults to :data:`DEFAULT_GAINS`; an unknown
            label is an error rather than a silent zero, because a typo that
            scores as irrelevant is invisible and changes every result.
    """
    table = dict(gains or DEFAULT_GAINS)
    qrels: dict[str, dict[str, int]] = {}
    for query_id, doc_id, label in judgements:
        if label not in table:
            raise KeyError(f"No gain defined for label {label!r}. Known: {sorted(table)}")
        qrels.setdefault(str(query_id), {})[str(doc_id)] = table[label]
    return qrels


def _parse(measures: Sequence[str]):
    import ir_measures

    return [ir_measures.parse_measure(m) for m in measures]


def measure_names(measures: Sequence[str]) -> list[str]:
    """Canonical names, so a table's columns match what ir_measures reports."""
    return [str(m) for m in _parse(measures)]


def score_run(
    run: Run,
    qrels: Mapping[str, Mapping[str, int]],
    measures: Sequence[str] = ("nDCG@10", "R@50", "RR", "AP"),
) -> dict[str, float]:
    """Aggregate scores for one run.

    Queries with no judgements are dropped by trec_eval, so a run is only
    compared over queries the qrels actually cover.
    """
    import ir_measures

    scored = ir_measures.calc_aggregate(_parse(measures), dict(qrels), run.as_dict())
    return {str(measure): value for measure, value in scored.items()}


def compare(
    runs: Iterable[Run],
    qrels: Mapping[str, Mapping[str, int]],
    measures: Sequence[str] = ("nDCG@10", "R@50", "RR", "AP"),
):
    """Score several runs into one table, one row per system.

    Returns a pandas DataFrame indexed by run name, columns in the order given.
    """
    import pandas as pd

    rows = {run.name: score_run(run, qrels, measures) for run in runs}
    return pd.DataFrame.from_dict(rows, orient="index")[measure_names(measures)]
