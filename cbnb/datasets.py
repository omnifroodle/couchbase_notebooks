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
