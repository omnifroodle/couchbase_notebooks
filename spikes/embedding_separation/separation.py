"""Spike: a cheap fit check from a few ideal results.

Each query is searched against an index holding only the N ideal documents. Separation is its
own ideal's score minus the mean score of the other queries' ideals. Uses the embeddings that
retrieval/04 cached, so it sends nothing once that notebook has run. Run from the repo root.
"""
import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from cbnb.datasets import load_wands_eval_set
from cbnb.embeddings import Embedder

load_dotenv(".env")
os.environ["CBNB_LLM_PROVIDER"] = "nanogpt"

QWEN_TASK = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
THREE = ["all-MiniLM-L6-v2", "Qwen3-Embedding-0.6B", "text-embedding-3-small"]
DRAWS = 2000

ev = load_wands_eval_set()
products = ev.products.reset_index(drop=True)
texts = (products.product_name.fillna("") + " " + products.product_class.fillna("")).str.strip().tolist()
row_of = {str(p): i for i, p in enumerate(products.product_id)}
queries = ev.queries.reset_index(drop=True)
labels = ev.labels.assign(product_id=ev.labels.product_id.astype(str)).drop_duplicates(
    ["query_id", "product_id"], keep="last")

# One ideal per query, fixed independently of any model: its first Exact label.
exact = labels[(labels.label == "Exact") & labels.product_id.isin(row_of)]
ideal = exact.groupby("query_id").product_id.first().map(row_of)
query_row = {q: i for i, q in enumerate(queries.query_id)}
query_ids = [q for q in queries.query_id if q in ideal.index]

qwen = Embedder("api", "Qwen/Qwen3-Embedding-0.6B")
embedders = {
    "all-MiniLM-L6-v2": (Embedder("local", "sentence-transformers/all-MiniLM-L6-v2"), ""),
    "Qwen3-Embedding-0.6B": (qwen, QWEN_TASK),
    "text-embedding-3-small": (Embedder("api", "text-embedding-3-small"), ""),
    "Qwen3 (no instruction)": (qwen, ""),
}
vectors = {name: (e.encode([prefix + t for t in queries["query"]]), e.encode(texts))
           for name, (e, prefix) in embedders.items()}


def separation(name, ids):
    """Score each query against an index of only these queries' ideal documents."""
    q, d = vectors[name]
    m = q[[query_row[x] for x in ids]] @ d[[ideal[x] for x in ids]].T
    off = ~np.eye(len(ids), dtype=bool)
    good = np.diag(m)
    bad = m[off].reshape(len(ids), -1)
    gap = good - bad.mean(axis=1)
    return {"good": good.mean(), "bad": bad.mean(), "separation (good - mean bad)": gap.mean(),
            "separation / spread of bad": (gap / m[off].std()).mean(),
            "good ranked first": (good > bad.max(axis=1)).mean()}


pd.set_option("display.width", 220)
print(f"All {len(query_ids)} queries, index of their ideal documents:")
print(pd.DataFrame({name: separation(name, query_ids) for name in vectors}).T.round(3).to_string())

rng = np.random.default_rng(0)
scores = ["separation (good - mean bad)", "separation / spread of bad"]
results = {}
for n in (4, 10, 20):
    picks_best = dict.fromkeys(scores, 0)
    prefers_instruction = dict.fromkeys(scores, 0)
    for _ in range(DRAWS):
        ids = list(rng.choice(query_ids, n, replace=False))
        s = {name: separation(name, ids) for name in vectors}
        for k in scores:
            picks_best[k] += max(THREE, key=lambda name: s[name][k]) == "text-embedding-3-small"
            prefers_instruction[k] += s["Qwen3-Embedding-0.6B"][k] > s["Qwen3 (no instruction)"][k]
    for k in scores:
        results[(k, n)] = {"picks text-embedding-3-small (of 3)": picks_best[k] / DRAWS,
                           "prefers Qwen3 with instruction": prefers_instruction[k] / DRAWS}
print(pd.DataFrame(results).T.rename_axis(["score", "queries"]).round(2).to_string())
