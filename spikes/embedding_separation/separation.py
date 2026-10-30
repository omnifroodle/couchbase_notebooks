"""Spike: a cheap fit check. Each query searched against an index of only the N ideal docs; separation = its ideal's score minus the mean of the others'. Cached vectors only; run from the repo root."""
import os
os.environ["CBNB_LLM_PROVIDER"] = "nanogpt"
import numpy as np, pandas as pd
from dotenv import load_dotenv
load_dotenv(".env")
from cbnb.datasets import load_wands_eval_set
from cbnb.embeddings import Embedder

ev = load_wands_eval_set()
docs = pd.DataFrame({"doc_id": ev.products.product_id.astype(str),
                     "text": (ev.products.product_name.fillna("") + " " + ev.products.product_class.fillna("")).str.strip(),
                     "cls": ev.products.product_class.fillna("")})
labels = pd.DataFrame({"q": ev.labels.query_id, "doc_id": ev.labels.product_id.astype(str), "label": ev.labels.label}).drop_duplicates(["q", "doc_id"], keep="last")
queries = ev.queries.reset_index(drop=True)
pos = {d: i for i, d in enumerate(docs.doc_id)}
# One ideal per query, fixed independently of any model: its first Exact label in the file.
ideal = {}
for q in queries.query_id:
    ex = [pos[d] for d in labels[(labels.q == q) & (labels.label == "Exact")].doc_id if d in pos]
    if ex: ideal[q] = ex[0]
qs = [q for q in queries.query_id if q in ideal]
qrow = {q: int(queries.index[queries.query_id == q][0]) for q in qs}
TASK = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
models = {"all-MiniLM-L6-v2": (Embedder("local", "sentence-transformers/all-MiniLM-L6-v2"), ""),
          "Qwen3-Embedding-0.6B": (Embedder("api", "Qwen/Qwen3-Embedding-0.6B"), TASK),
          "text-embedding-3-small": (Embedder("api", "text-embedding-3-small"), "")}
V = {}
for name, (e, qp) in models.items():
    V[name] = (e.encode([qp + t for t in queries["query"]]), e.encode(docs.text.tolist()))

def scores(name, sub):
    Q, D = V[name]
    q = Q[[qrow[x] for x in sub]]; d = D[[ideal[x] for x in sub]]
    M = q @ d.T                      # query i vs ideal doc j
    DD = d @ d.T                     # ideal docs vs each other
    n = len(sub); off = ~np.eye(n, dtype=bool)
    diag = np.diag(M)
    return {
        "mean q-ideal sim": diag.mean(),
        "mean doc-doc sim": DD[off].mean(),
        "raw margin (diag - max row off)": (diag - np.where(off, M, -9).max(1)).mean(),
        "sim - doc-doc": diag.mean() - DD[off].mean(),
        "z within matrix": ((diag - M[off].mean()) / M[off].std()).mean(),
        "margin / spread of off": ((diag - np.where(off, M, -9).max(1)) / M[off].std()).mean(),
        "all correct": float((diag > np.where(off, M, -9).max(1)).all()),
    }

e_q = models["Qwen3-Embedding-0.6B"][0]
V["Qwen3 (no instruction)"] = (e_q.encode(queries["query"].tolist()), V["Qwen3-Embedding-0.6B"][1])

def sep(name, sub):
    """Per query: its ideal doc's score vs the other queries' ideal docs, in an index of only the ideals."""
    Q, D = V[name]
    M = Q[[qrow[x] for x in sub]] @ D[[ideal[x] for x in sub]].T
    n = len(sub); off = ~np.eye(n, dtype=bool)
    good = np.diag(M)
    bad = np.array([M[i][off[i]] for i in range(n)])           # each query's bad results
    return {"good": good.mean(), "bad": bad.mean(),
            "separation (good - mean bad)": (good - bad.mean(1)).mean(),
            "separation / spread of bad": ((good - bad.mean(1)) / M[off].std()).mean(),
            "good ranked first": (good > bad.max(1)).mean()}

pd.set_option("display.width", 220)
print("All 40 queries, index of their 40 ideal docs:")
print(pd.DataFrame({m: sep(m, qs) for m in V}).T.round(3).to_string())
rng = np.random.default_rng(0)
K = ["separation (good - mean bad)", "separation / spread of bad"]
out = {}
for n in (4, 10, 20):
    a = {k: 0 for k in K}; b = {k: 0 for k in K}; first = []
    for _ in range(2000):
        sub = list(rng.choice(qs, n, replace=False))
        s = {m: sep(m, sub) for m in V}
        three = ["all-MiniLM-L6-v2", "Qwen3-Embedding-0.6B", "text-embedding-3-small"]
        for k in K:
            a[k] += max(three, key=lambda m: s[m][k]) == "text-embedding-3-small"
            b[k] += s["Qwen3-Embedding-0.6B"][k] > s["Qwen3 (no instruction)"][k]
        first.append(min(s[m]["good ranked first"] for m in three))
    for k in K:
        out[(k, n)] = {"picks text-embedding-3-small (of 3)": a[k] / 2000, "prefers Qwen3 with instruction": b[k] / 2000}
    out[("every model ranks every good result first", n)] = {"picks text-embedding-3-small (of 3)": np.mean(np.array(first) == 1.0), "prefers Qwen3 with instruction": np.nan}
print(pd.DataFrame(out).T.round(2).to_string())
