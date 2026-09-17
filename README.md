# Couchbase notebooks

Runnable notebooks for retrieval and AI patterns on
[Couchbase Capella](https://cloud.couchbase.com) — vector search, hybrid search, RAG,
LLM-driven enrichment, and document modelling.

They share a thesis:

> **Eval matters.** "It looks good on my machine with my queries" will not get you far, and
> most of these notebooks exist to show you the gap between a demo that convinces a room and a
> system you can trust.

So every notebook that makes a claim measures it, against judgements a human wrote, and
several of them end up reporting a result less flattering than the one they were designed
around. That is the point.

**Everything here runs on Capella's free tier**, with a model API key you supply. Notebooks
that cost money say so in their header, and none costs more than a few cents.

## Notebooks

Read in this order if you're starting cold. Each row's result comes from the run stored in
that notebook, so the table stays honest.

| Notebook | Track | What it shows | Result |
| --- | --- | --- | --- |
| **[Can I run these?](notebooks/00_check_setup.ipynb)** | — | **Start here.** Checks your credentials for real — a live connection, a live model call — then tells you which notebook below you can run right now, and what to fix if you can't. | — |
| [Building hybrid search on Couchbase](notebooks/retrieval/01_building_hybrid_search.ipynb) | retrieval | The mechanics. Vector, then keyword, then both in one request, then filtered — each step a working search over 6,482 real products. Analysers, prefilters, one index. No LLM. | Two queries, opposite winners — which is why `02` exists |
| [Which parts of that were worth it?](notebooks/retrieval/02_which_parts_helped.ipynb) | retrieval | Takes those four searches and scores them against 7,000 human relevance judgements with `trec_eval`. No LLM. | No winner: vector leads nDCG@10 (0.78 vs 0.71), the hybrids lead recall@50 |
| [Your RAG demo works. Now prove it.](notebooks/flows/01_rag_that_you_can_trust.ipynb) | flows | Build RAG over 20 real contracts, answer one query beautifully, then ask 820 questions a lawyer answered first — and split the failures into retrieval's fault and the model's. | 64.4% correct, inventing answers for 23 of 93 unanswerable questions; one prompt paragraph → 70.6% |
| [Documents that learn](notebooks/data-model/01_documents_that_learn.ipynb) | data-model | Contracts arrive as prose. A model reads their terms; the terms go back on — embedded, and again as referenced derived documents — and SQL++ queries them. No migration, no second store. | Prose becomes `WHERE governing_law = "California" AND agreement_date > "2015"` |
| [Adding retrieval to enriched documents](notebooks/data-model/02_adding_retrieval.ipynb) → *needs `01` first* | data-model | Chunks are derived documents, and a search index cannot join them to their parent. Copy the filterable fields down, or filter afterwards and lose results — both, measured. | A filter on an unindexed field returns 0 hits and no error |
| [Scoring the extraction](notebooks/enrich/02_scoring_the_extraction.ipynb) | enrich | `data-model/01` extracted contract terms and never checked them. This scores 122 contracts against lawyer annotations — four fields, four definitions of "correct" — then tests two ways to flag a bad extraction without ground truth. | 80.3–95.0% by field; 43% of date annotations don't parse; neither self-check catches a quarter of the errors |
| [Don't classify. Hallucinate.](notebooks/enrich/01_hypothetical_classification.ipynb) | enrich | Classify into a 1,623-category taxonomy that never enters the prompt. A cheap model invents a plausible category path; Couchbase Vector Search snaps it to a real one. | 48.7% → 71.3% department accuracy over a no-LLM baseline, n=150 |

Every notebook runs top to bottom on its own, with one exception noted in the table:
`data-model/02` reads what `01` wrote, because that *is* its subject.

Tracks are **retrieval** (recall mechanics), **flows** (RAG, chat, agents), **enrich** (AI on
the write path) and **data-model** (Couchbase-specific modelling). Numbers restart inside each
track.

What's coming, and why things are arranged this way: [`docs/roadmap.md`](docs/roadmap.md).

## Getting started

**1. A Capella cluster.** Free tier is enough. Five minutes:
[`docs/capella-setup.md`](docs/capella-setup.md).

**2. A model API key.** Anything that speaks the OpenAI API — OpenAI, NanoGPT, OpenRouter,
Groq, Anthropic's compatibility endpoint, or Ollama on your own machine. Three of the
notebooks need no model at all — both `retrieval/` ones and `data-model/02`, which reads
what `01` already extracted.

**3. Run one.**

*Locally:*

```bash
git clone https://github.com/omnifroodle/couchbase_notebooks.git && cd couchbase_notebooks
make setup             # .venv + editable install + .env from the example
```

Then `make run NB=retrieval/01` to execute a notebook headless, or open it in VS Code. The
edit/run loop — autoreloading helpers, cached LLM calls, shipping stored outputs — is in
[`docs/local-development.md`](docs/local-development.md).

*On GitHub Codespaces:*
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/omnifroodle/couchbase_notebooks?quickstart=1)
— the full repo in a cloud container with VS Code, set up and ready. Credentials go in
Codespaces secrets, which GitHub offers to collect when you create one. See
[`docs/codespaces.md`](docs/codespaces.md).

*On Colab:* click the badge on any notebook. The first cell installs everything. Put your
credentials in Colab's secrets manager (the key icon) using the names from
[`.env.example`](.env.example) — or just run the notebook and answer the prompts.

Nothing is hardcoded and nothing is required up front: every setting resolves from the
environment (where Codespaces secrets land), then `.env`, then Colab secrets, then an
interactive prompt.

**Not sure your setup works?** Run
[`notebooks/00_check_setup.ipynb`](notebooks/00_check_setup.ipynb) first. It takes a minute and
tells you which notebooks you can run before you invest in one.

## What's in `cbnb/`

The shared helper package, so the notebooks show the technique and not the plumbing.

| Module | |
| --- | --- |
| `bootstrap.py` | One-call environment setup. Detects Colab, installs what is missing, checks what a notebook declared it needs. |
| `config.py` | Credential resolution: env → `.env` → Colab secrets → `getpass`. |
| `couchbase_io.py` | Connect, provision scopes/collections, build Search indexes, bulk load, search. Every `ensure_*` is idempotent. |
| `llm.py` | One client for any OpenAI-compatible endpoint. Structured output that degrades gracefully, a disk cache, token accounting, parallel `map`. |
| `embeddings.py` | Local sentence-transformers or an API endpoint. Always normalised. |
| `datasets.py` | Openly-licensed datasets, with small samples committed so notebooks run instantly. |
| `eval.py` | Retrieval metrics via `ir-measures`/`trec_eval`, plus the judgement calls that are ours. |
| `readiness.py` | What this environment can actually do. Live checks, and what to do when one fails. |
| `inventory.py` | What each notebook asks for, read from the notebook files themselves. |
| `nbstamp.py` | Ties stored outputs to the code that produced them, so stale outputs fail a check. |
| `review.py` | Optional. Asks a model which prose a re-run invalidated. Advisory, never published. |

### The LLM client

One `openai` client, provider presets for the base URL and key name:

```python
from cbnb.llm import LLM

llm = LLM("nanogpt", model="gpt-4.1-mini")      # or openai, openrouter, groq,
                                                 # anthropic, ollama, custom
llm.chat("Say hi")
llm.structured("Product: brown coffee table", MySchema, system="...")
llm.map(items, fn, max_workers=8)                # because a serial eval is an eval you skip
```

`structured()` asks for a Pydantic model and works its way down — strict `json_schema`, then
`json_object`, then plain prompting with the schema inlined — remembering which rung your
provider actually reached. Responses are cached on disk, because notebook cells get re-run and
you should only pay once. `llm.usage` reports what a demo cost.

Set the default with `CBNB_LLM_PROVIDER` / `CBNB_LLM_MODEL`, or point `custom` at any base URL
with `CBNB_LLM_BASE_URL`.

## Data

| Dataset | Licence | Used by | What it is |
| --- | --- | --- | --- |
| [WANDS](https://github.com/wayfair/WANDS) | MIT | `retrieval/*`, `enrich/01` | Real product listings, a real 1,623-node retail taxonomy, 480 search queries, 233k relevance judgements |
| [CUAD](https://www.atticusprojectai.org/cuad) | CC BY 4.0 | `flows/01`, `data-model/*` | 510 SEC-filed commercial contracts, annotated by lawyers for 41 clause categories — every annotation a character span |

Committed under [`data/`](data/) so notebooks run before anything downloads:

- a stratified 2,500-product sample, the full 1,623-path taxonomy, and all 480 queries;
- a **retrieval benchmark** — 40 queries, the 6,482 products judged for them, and all 6,986 of
  those judgements;
- a **contract sample** — 20 contracts across 18 agreement types, with 534 annotated clause
  spans.

The full 43k-product catalogue, the 233k-judgement file and all 510 contracts download on
demand.

Two properties worth knowing before you trust a number from either:

**Recall on the WANDS benchmark is measured against the judged pool, not the catalogue.** A
product nobody judged cannot be found and does not count against you.
[`retrieval/02`](notebooks/retrieval/02_which_parts_helped.ipynb) computes what the best
possible score actually is — 0.462 for R@50, which is why a raw 0.40 is not the failure it
looks like.

**62% of CUAD's questions have no answer in their contract.** Most contracts have no
source-code-escrow clause, and the correct response is "not in this document" — which makes it
a real test of whether a system will say so, and is the spine of
[`flows/01`](notebooks/flows/01_rag_that_you_can_trust.ipynb).

CUAD's annotations are CC BY 4.0; the underlying contracts are EDGAR filings whose licence
status the CUAD authors do not warrant.

### Measuring retrieval

`cbnb.eval` does not implement its own metrics. It wraps
[`ir-measures`](https://ir-measur.es/), which wraps `pytrec_eval`, which wraps `trec_eval` —
the implementation IR papers report against — so `nDCG@10` here means what a retrieval person
expects it to mean. What the notebooks keep visible is the part that is a judgement rather than
a calculation: which measures to report, and how graded labels become gains.

## Adding a notebook

See [`docs/adding-a-notebook.md`](docs/adding-a-notebook.md) for the rules that keep these
runnable, and [`CLAUDE.md`](CLAUDE.md) for the short version. Then:

```bash
make check
```

## Licence

Apache 2.0. Datasets keep their own licences, noted above.
