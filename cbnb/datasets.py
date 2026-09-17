"""Openly-licensed datasets the notebooks can use.

Currently WANDS -- Wayfair's product search relevance dataset, released under
the MIT licence at https://github.com/wayfair/WANDS. It is the rare public
e-commerce dataset that ships *both* real product listings and the real,
messy, 1,600-node category taxonomy those listings were filed under, which is
exactly what a classification demo needs.

A stratified sample of the products, the full taxonomy, and all 480 search
queries are committed under ``data/`` so a notebook runs immediately. Call
:func:`load_wands_products` with ``full=True`` to pull the complete 43k-product
file (~86 MB) from GitHub instead.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from cbnb.bootstrap import repo_root

WANDS_BASE_URL = "https://raw.githubusercontent.com/wayfair/WANDS/main/dataset"
WANDS_CITATION = (
    "Chen et al., 'WANDS: Dataset for Product Search Relevance Assessment', "
    "ECIR 2022. Dataset: https://github.com/wayfair/WANDS (MIT licence)."
)


def data_dir() -> Path | None:
    """The repo's committed ``data/`` directory, if we are running from a checkout.

    ``None`` when ``cbnb`` was pip-installed on its own, in which case the
    loaders below rebuild what they need from the upstream dataset.
    """
    root = repo_root()
    if root is None:
        return None
    directory = root / "data"
    return directory if directory.exists() else None


def cache_dir() -> Path:
    path = Path(os.environ.get("CBNB_CACHE_DIR", Path.home() / ".cache" / "cbnb" / "datasets"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(filename: str) -> Path:
    target = cache_dir() / filename
    if target.exists():
        return target
    url = f"{WANDS_BASE_URL}/{filename}"
    print(f"Downloading {url} -> {target} ...")
    with urlopen(url) as response, open(target, "wb") as handle:  # noqa: S310 - fixed https URL
        handle.write(response.read())
    return target


def _download_url(url: str, filename: str) -> Path:
    """Cache any dataset file by URL. ``_download`` is the WANDS-specific form."""
    target = cache_dir() / filename
    if target.exists():
        return target
    print(f"Downloading {url} -> {target} ...")
    with urlopen(url) as response, open(target, "wb") as handle:  # noqa: S310 - fixed https URL
        handle.write(response.read())
    return target


def _committed(filename: str) -> Path | None:
    directory = data_dir()
    if directory is None:
        return None
    path = directory / filename
    return path if path.exists() else None


def _full_products() -> pd.DataFrame:
    """All 42,994 products, downloading the 86 MB source file on first use."""
    return pd.read_csv(
        _download("product.csv"),
        sep="\t",
        usecols=["product_id", "product_name", "product_class", "category hierarchy"],
    ).rename(columns={"category hierarchy": "category_hierarchy"})


def load_wands_taxonomy() -> list[str]:
    """Every distinct category path in WANDS, sorted.

    A path looks like ``"Furniture / Living Room Furniture / Coffee Tables &
    End Tables / Coffee Tables"``. There are 1,623 of them, up to eight levels
    deep -- far too many to paste into a prompt, which is the whole reason the
    hypothetical-classification trick exists.
    """
    path = _committed("wands_taxonomy.txt") or (cache_dir() / "wands_taxonomy.txt")
    if not path.exists():
        paths = sorted(_full_products()["category_hierarchy"].dropna().unique())
        path.write_text("\n".join(paths) + "\n")
    return [line for line in path.read_text().splitlines() if line.strip()]


def load_wands_products(full: bool = False) -> pd.DataFrame:
    """Product listings with their true category path.

    Args:
        full: use all 42,994 products (downloads ~86 MB) instead of the
            2,500-row stratified sample committed to the repo.

    Returns:
        A frame with ``product_id``, ``product_name``, ``product_class`` and
        ``category_hierarchy``.
    """
    if full:
        frame = _full_products()
    else:
        committed = _committed("wands_products_sample.tsv")
        if committed is not None:
            frame = pd.read_csv(committed, sep="\t")
        else:
            frame = _sample_products(_full_products())
    frame = frame.dropna(subset=["product_name", "category_hierarchy"])
    return frame.reset_index(drop=True)


def _sample_products(frame: pd.DataFrame, per_category: int = 2, cap: int = 2500) -> pd.DataFrame:
    """Deterministically rebuild the committed sample: broad category coverage.

    Sampling per category rather than uniformly keeps rare departments in the
    evaluation, which is where classification is hardest and most interesting.
    """
    frame = frame.dropna(subset=["product_name", "category_hierarchy"])
    picked = (
        frame.groupby("category_hierarchy", group_keys=False)
        .apply(lambda g: g.sample(min(len(g), per_category), random_state=1729))
        .sample(frac=1.0, random_state=1729)
    )
    return picked.head(cap).reset_index(drop=True)


def load_wands_queries() -> pd.DataFrame:
    """The 480 real search queries, each with a hand-assigned product class."""
    committed = _committed("wands_queries.tsv")
    if committed is not None:
        return pd.read_csv(committed, sep="\t")
    return pd.read_csv(_download("query.csv"), sep="\t")


def load_wands_labels() -> pd.DataFrame:
    """Query/product relevance judgements (``Exact`` / ``Partial`` / ``Irrelevant``).

    Downloads the 5.5 MB label file on first use; it is too big to commit.
    """
    return pd.read_csv(_download("label.csv"), sep="\t")


@dataclass
class Taxonomy:
    """A list of category paths, with the small helpers a demo keeps needing."""

    paths: Sequence[str]
    separator: str = " / "

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> str:
        return self.paths[index]

    def __iter__(self):
        return iter(self.paths)

    def segments(self, path: str) -> list[str]:
        return [part.strip() for part in path.split(self.separator) if part.strip()]

    def leaf(self, path: str) -> str:
        """The most specific segment -- ``"Coffee Tables"``."""
        parts = self.segments(path)
        return parts[-1] if parts else path

    def top_level(self, path: str) -> str:
        """The department -- ``"Furniture"``."""
        parts = self.segments(path)
        return parts[0] if parts else path

    def departments(self) -> list[str]:
        return sorted({self.top_level(p) for p in self.paths})

    def prefix_overlap(self, predicted: str, actual: str) -> float:
        """Fraction of the true path's segments matched from the root.

        ``1.0`` is an exact match; ``0.0`` means even the department is wrong.
        A path-structured taxonomy makes "nearly right" a meaningful outcome,
        and a plain accuracy number hides all of it.
        """
        want = self.segments(actual)
        got = self.segments(predicted)
        if not want:
            return 0.0
        matched = 0
        for a, b in zip(want, got, strict=False):
            if a.lower() != b.lower():
                break
            matched += 1
        return matched / len(want)


@dataclass
class EvalSet:
    """A retrieval benchmark small enough to run, complete enough to trust.

    WANDS judges 480 queries against the full 43k catalogue. Indexing all of
    that for a demo is slow and mostly wasted: a single query's results are
    scored against the handful of products anyone judged for it. So this is a
    **pool** -- a subset of queries, plus every product judged for one of them.

    Pooling is standard practice in IR evaluation, and it has a consequence the
    notebook using this must state: recall is measured against the pool, not
    against the whole catalogue. Comparing two systems over the same pool is
    sound; reading a recall figure as "of everything Wayfair sells" is not.
    """

    queries: pd.DataFrame  # query_id, query, query_class
    products: pd.DataFrame  # product_id, product_name, product_class, category_hierarchy
    labels: pd.DataFrame  # query_id, product_id, label

    def judgements(self) -> list[tuple[str, str, str]]:
        """``(query_id, product_id, label)`` triples, for :func:`cbnb.eval.to_qrels`."""
        return [
            (str(r.query_id), str(r.product_id), r.label)
            for r in self.labels.itertuples(index=False)
        ]

    def summary(self) -> str:
        exact = int((self.labels.label == "Exact").sum())
        return (f"{len(self.queries)} queries, {len(self.products):,} products, "
                f"{len(self.labels):,} judgements ({exact:,} Exact)")


#: Queries worth evaluating: enough judged products to separate two systems,
#: few enough to keep the pool indexable, and enough Exact matches that
#: precision-oriented measures are not all zero.
_EVAL_MIN_JUDGED, _EVAL_MAX_JUDGED, _EVAL_MIN_EXACT = 40, 400, 5
_EVAL_SEED = 1729


def _build_wands_eval_set(n_queries: int = 40) -> EvalSet:
    """Rebuild the committed evaluation set from the full WANDS download."""
    import numpy as np

    labels = load_wands_labels()
    queries = load_wands_queries()

    judged = labels.groupby("query_id").size()
    exact = labels[labels.label == "Exact"].groupby("query_id").size()
    eligible = [
        qid for qid in judged[(judged >= _EVAL_MIN_JUDGED) & (judged <= _EVAL_MAX_JUDGED)].index
        if exact.get(qid, 0) >= _EVAL_MIN_EXACT
    ]
    chosen = np.random.default_rng(_EVAL_SEED).choice(
        sorted(eligible), size=min(n_queries, len(eligible)), replace=False
    )
    chosen = sorted(int(q) for q in chosen)

    picked_labels = labels[labels.query_id.isin(chosen)][["query_id", "product_id", "label"]]
    products = _full_products()
    pool = products[products.product_id.isin(set(picked_labels.product_id))]
    return EvalSet(
        queries=queries[queries.query_id.isin(chosen)].reset_index(drop=True),
        products=pool.sort_values("product_id").reset_index(drop=True),
        labels=picked_labels.sort_values(["query_id", "product_id"]).reset_index(drop=True),
    )


def load_wands_eval_set() -> EvalSet:
    """The committed retrieval benchmark, or rebuild it from the full download.

    See :class:`EvalSet` for what pooling means for the numbers.
    """
    names = ("wands_eval_queries.tsv", "wands_eval_products.tsv", "wands_eval_labels.tsv")
    committed = [_committed(name) for name in names]
    if all(path is not None for path in committed):
        queries, products, labels = (pd.read_csv(path, sep="\t") for path in committed)
        return EvalSet(queries=queries, products=products, labels=labels)
    return _build_wands_eval_set()


# --- CUAD: contracts, clause questions, and character-level answer spans ----
#
# The Contract Understanding Atticus Dataset (CC BY 4.0, The Atticus Project):
# 510 commercial contracts filed with the SEC, annotated by lawyers for 41
# categories of clause that matter in a corporate transaction.
#
# It is here because it answers two questions at once. It is a retrieval
# benchmark -- each annotation is a character span, so "did we retrieve the
# right passage" is exactly measurable. And the categories are a ready-made
# extraction schema: parties, dates, governing law, renewal terms. The same
# documents can carry a RAG notebook and a structured-extraction one.
#
# The property that makes it honest: **68% of the annotations are absent**. Most
# contracts do not have a source-code-escrow clause, and the correct answer is
# "not in this document". A system that always produces a confident answer is
# wrong most of the time, and no hand-picked demo query will show you that.
#
# Citation: Hendrycks, Burns, Chen, Ball. "CUAD: An Expert-Annotated NLP Dataset
# for Legal Contract Review." NeurIPS 2021. https://www.atticusprojectai.org/cuad
# The annotations are CC BY 4.0; the underlying contracts are SEC filings
# obtained from EDGAR, whose licence status the CUAD authors do not warrant.

CUAD_URL = "https://huggingface.co/datasets/theatticusproject/cuad/resolve/main/CUAD_v1/CUAD_v1.json"

_CUAD_QUESTION = re.compile(
    r'related to "(?P<category>.+?)" that should be reviewed by a lawyer\. '
    r'Details: (?P<details>.+)',
    re.S,
)

#: A few categories are described as noun phrases rather than questions; the
#: rest of CUAD's "Details" text already reads as one. Asking a real question
#: matters here, because the notebook feeds these to a retriever and a model.
_CUAD_REPHRASED = {
    "Document Name": "What is the name or title of this contract?",
    "Parties": "Who are the parties to this agreement?",
    "Agreement Date": "What date was this contract signed?",
    "Effective Date": "On what date does this agreement become effective?",
}


@dataclass
class ContractSet:
    """Contracts, clause questions, and where the answers actually are.

    ``spans`` holds one row per annotated answer. A (contract, category) pair
    with no row is a genuine absence -- the clause is not in that contract --
    and those are the majority. :meth:`questions_with_absences` makes them
    explicit, because a benchmark that only contains answerable questions
    measures the easy half of the problem.
    """

    contracts: pd.DataFrame  # contract_id, title, contract_type, text
    categories: pd.DataFrame  # category, question
    spans: pd.DataFrame  # contract_id, category, start, end, text

    def questions_with_absences(self) -> pd.DataFrame:
        """Every (contract, category) pair, answerable or not."""
        pairs = self.contracts[["contract_id"]].merge(self.categories, how="cross")
        present = self.spans.groupby(["contract_id", "category"]).size().rename("spans")
        merged = pairs.merge(present, on=["contract_id", "category"], how="left")
        merged["spans"] = merged["spans"].fillna(0).astype(int)
        merged["answerable"] = merged.spans > 0
        return merged

    def summary(self) -> str:
        pairs = self.questions_with_absences()
        absent = (~pairs.answerable).mean()
        return (f"{len(self.contracts)} contracts, {len(self.contracts.contract_type.unique())} types, "
                f"{len(self.categories)} clause categories, {len(self.spans):,} annotated spans; "
                f"{absent:.0%} of questions have no answer in their contract")


#: CUAD titles are filenames: company, filing date, exhibit number, then the
#: kind of agreement -- "LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT",
#: "MetLife, Inc. - Remarketing Agreement". The type is the trailing
#: human-readable part, which is worth recovering: it is a structured field
#: extracted from nothing but a filename, and it filters retrieval later.
_CUAD_TYPE = re.compile(
    r"[_-]\s*([A-Za-z][A-Za-z0-9 ,&'/.\-]*?"
    r"(?:AGREEMENT|CONTRACT|LICENSE|LICENCE|GUARANTY|AMENDMENT|LETTER|ADDENDUM))"
    r"\s*\d*\s*$",
    re.IGNORECASE,
)
#: Strips an exhibit number the greedy match above may have swallowed.
_CUAD_EXHIBIT = re.compile(r"^EX[-.]?[\d.]*\s*-\s*", re.IGNORECASE)


def _cuad_contract_type(title: str) -> str:
    """The kind of agreement, from CUAD's filename-shaped titles."""
    found = _CUAD_TYPE.search(title)
    if not found:
        return "OTHER"
    name = _CUAD_EXHIBIT.sub("", found.group(1))
    return re.sub(r"\s+", " ", name).strip().upper() or "OTHER"


#: Contracts long enough to need retrieval, short enough to index quickly, and
#: annotated richly enough to ask real questions of.
_CUAD_MIN_CHARS, _CUAD_MAX_CHARS, _CUAD_MIN_CLAUSES = 12_000, 45_000, 12
_CUAD_SAMPLE_SIZE = 20
_CUAD_SEED = 1729


def _build_cuad(n_contracts: int = _CUAD_SAMPLE_SIZE, per_type: int | None = 2) -> ContractSet:
    """Rebuild a contract set from the 40 MB CUAD download.

    ``per_type`` caps how many contracts of one agreement type are eligible,
    which is what keeps the committed sample from being all distributor
    agreements. Pass ``None`` for everything, which is what ``full=True`` means.
    """
    import json

    import numpy as np

    raw = json.loads(_download_url(CUAD_URL, "CUAD_v1.json").read_text())["data"]

    categories: dict[str, str] = {}
    for qa in raw[0]["paragraphs"][0]["qas"]:
        found = _CUAD_QUESTION.search(qa["question"])
        if found:
            name = found.group("category")
            details = " ".join(found.group("details").split())
            categories[name] = _CUAD_REPHRASED.get(name, details)

    eligible = []
    for index, entry in enumerate(raw):
        para = entry["paragraphs"][0]
        present = sum(1 for qa in para["qas"] if qa["answers"])
        if (_CUAD_MIN_CHARS <= len(para["context"]) <= _CUAD_MAX_CHARS
                and present >= _CUAD_MIN_CLAUSES):
            eligible.append(index)

    if per_type is None:
        pool = eligible
    else:
        # At most ``per_type`` of any one agreement type, so the sample is not
        # all distributor agreements.
        by_type: dict[str, list[int]] = {}
        for index in eligible:
            by_type.setdefault(_cuad_contract_type(raw[index]["title"]), []).append(index)
        pool = [i for indexes in by_type.values() for i in indexes[:per_type]]

    rng = np.random.default_rng(_CUAD_SEED)
    chosen = sorted(rng.choice(sorted(pool), size=min(n_contracts, len(pool)), replace=False))

    contracts, spans = [], []
    for contract_id, index in enumerate(chosen):
        entry = raw[int(index)]
        para = entry["paragraphs"][0]
        contracts.append({
            "contract_id": contract_id,
            "title": entry["title"],
            "contract_type": _cuad_contract_type(entry["title"]),
            "text": para["context"],
        })
        for qa in para["qas"]:
            found = _CUAD_QUESTION.search(qa["question"])
            if not found:
                continue
            for answer in qa["answers"]:
                spans.append({
                    "contract_id": contract_id,
                    "category": found.group("category"),
                    "start": int(answer["answer_start"]),
                    "end": int(answer["answer_start"]) + len(answer["text"]),
                    "text": answer["text"],
                })

    return ContractSet(
        contracts=pd.DataFrame(contracts),
        categories=pd.DataFrame(
            [{"category": k, "question": v} for k, v in categories.items()]
        ),
        spans=pd.DataFrame(spans).drop_duplicates().reset_index(drop=True),
    )


def load_cuad(full: bool = False) -> ContractSet:
    """Contracts with lawyer-annotated clause spans.

    Defaults to the sample committed under ``data/`` so a notebook runs before
    anything downloads.

    ``full=True`` downloads CUAD (40 MB) and returns every contract that is long
    enough to need retrieval and annotated richly enough to ask questions of --
    around 120 of the 510, without the per-type cap that shapes the committed
    sample. Use it when the sample is too small to measure something, which is
    the usual reason to want it.
    """
    names = ("cuad_contracts.jsonl", "cuad_categories.tsv", "cuad_spans.jsonl")
    committed = [_committed(name) for name in names]
    if not full and all(path is not None for path in committed):
        return ContractSet(
            contracts=pd.read_json(committed[0], lines=True),
            categories=pd.read_csv(committed[1], sep="\t"),
            spans=pd.read_json(committed[2], lines=True),
        )
    if full:
        return _build_cuad(n_contracts=510, per_type=None)
    return _build_cuad(n_contracts=_CUAD_SAMPLE_SIZE)
