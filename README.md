# Couchbase notebooks

Runnable notebooks for modern retrieval and agentic patterns on
[Couchbase Capella](https://cloud.couchbase.com) — vector search, hybrid search,
LLM-driven enrichment, agent memory.

Each one is self-contained: open it, run it top to bottom, get a result. They read well on
GitHub with their outputs stored, and they run unmodified on Colab.

## Notebooks

| Notebook | Track | What it shows | Result |
| --- | --- | --- | --- |
| [Can I run these?](notebooks/00_check_setup.ipynb) | — | **Start here.** Checks your credentials for real — a live connection and a live model call — then tells you which notebook below you can run right now, and what to fix if you can't. | — |
| [Recall, precision, and the price of a filter](notebooks/retrieval/01_hybrid_and_filtered.ipynb) | retrieval | Four retrieval strategies — BM25, vector, hybrid, filtered-hybrid — over 40 real queries with 7,000 human relevance judgements, scored with `trec_eval`. No LLM, no cost. | No winner: vector leads nDCG@10 (0.78 vs 0.71), the hybrids lead recall@50 |
| [Don't classify. Hallucinate.](notebooks/enrich/01_hypothetical_classification.ipynb) | enrich | Classify into a 1,623-category taxonomy that never enters the prompt. A cheap model invents a plausible category path; Couchbase Vector Search snaps it to a real one. | 48.7% → 71.3% department accuracy over a no-LLM baseline, n=150 |

Notebooks are grouped by track — **retrieval** (recall mechanics), **flows** (RAG, chat,
agents), **enrich** (AI on the write path), **data-model** (Couchbase-specific modelling).
Numbers restart inside a track; this table carries the reading order.

What's coming: [`docs/roadmap.md`](docs/roadmap.md).

## Getting started

**1. A Capella cluster.** Free tier is enough. Five minutes:
[`docs/capella-setup.md`](docs/capella-setup.md).

**2. A model API key.** Anything that speaks the OpenAI API — OpenAI, NanoGPT, OpenRouter,
Groq, Anthropic's compatibility endpoint, or Ollama on your own machine.

**3. Run one.**

*Locally:*

```bash
git clone https://github.com/omnifroodle/couchbase_notebooks.git && cd couchbase_notebooks
make setup             # .venv + editable install + .env from the example
```

Then `make run NB=retrieval/01` to execute a notebook headless, or open it in VS Code. The edit/run
loop — autoreloading helpers, cached LLM calls, and shipping stored outputs — is in
[`docs/local-development.md`](docs/local-development.md).

*On GitHub Codespaces:*
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/omnifroodle/couchbase_notebooks?quickstart=1)
— the full repo in a cloud container with VS Code, set up and ready to run. Credentials go in
Codespaces secrets, which GitHub offers to collect when you create one. See
[`docs/codespaces.md`](docs/codespaces.md).

*On Colab:* click the badge on any notebook. The first cell installs everything. Put your
credentials in Colab's secrets manager (the key icon) using the names from
[`.env.example`](.env.example) — or just run the notebook and answer the prompts.

Nothing is hardcoded and nothing is required up front: every setting resolves from the
environment (where Codespaces secrets land), then `.env`, then Colab secrets, then an
interactive prompt.

**Not sure your setup works?** Run
[`notebooks/00_check_setup.ipynb`](notebooks/00_check_setup.ipynb) first. It takes a minute
and tells you which notebooks you can run before you invest in one.

## What's in `cbnb/`

The shared helper package, so the notebooks show the technique and not the plumbing.

| Module | |
| --- | --- |
| `bootstrap.py` | One-call environment setup. Detects Colab, installs what is missing. |
| `config.py` | Credential resolution: env → `.env` → Colab secrets → `getpass`. |
| `couchbase_io.py` | Connect, provision scopes/collections, build vector indexes, bulk load, search. Every `ensure_*` is idempotent. |
| `llm.py` | One client for any OpenAI-compatible endpoint. Structured output that degrades gracefully, a disk cache, token accounting. |
| `embeddings.py` | Local sentence-transformers or an API endpoint. Always normalised. |
| `datasets.py` | Openly-licensed datasets, with small samples committed so notebooks run instantly. |
| `eval.py` | Retrieval metrics via `ir-measures`/`trec_eval`, plus the judgement calls that are ours. |
| `readiness.py` | What this environment can actually do. Live checks, and what to do when one fails. |
| `inventory.py` | What each notebook asks for, read from the notebook files themselves. |
| `review.py` | Optional. Asks a model which prose a re-run invalidated. Advisory, never published. |

### The LLM client

One `openai` client, provider presets for the base URL and key name:

```python
from cbnb.llm import LLM

llm = LLM("nanogpt", model="gpt-4.1-mini")      # or openai, openrouter, groq,
                                                 # anthropic, ollama, custom
llm.chat("Say hi")
llm.structured("Product: brown coffee table", MySchema, system="...")
```

`structured()` asks for a Pydantic model and works its way down — strict `json_schema`, then
`json_object`, then plain prompting with the schema inlined — remembering which rung your
provider actually reached. Responses are cached on disk, because notebook cells get re-run
and you should only pay once. `llm.usage` reports what a demo cost.

Set the default with `CBNB_LLM_PROVIDER` / `CBNB_LLM_MODEL`, or point `custom` at any
base URL with `CBNB_LLM_BASE_URL`.

## Data

| Dataset | Licence | Used for |
| --- | --- | --- |
| [WANDS](https://github.com/wayfair/WANDS) | MIT | Real product listings, a real 1,623-node retail taxonomy, 480 search queries, 233k relevance judgements |

Committed under [`data/`](data/) so notebooks run before anything is downloaded:

- a stratified 2,500-product sample, the full 1,623-path taxonomy, and all 480 queries;
- a **retrieval benchmark** — 40 queries, the 6,482 products judged for them, and all 6,986
  of those judgements. Enough to score a search system honestly, small enough to index in a
  minute.

The full 43k-product catalogue and the 233k-judgement file download on demand.

Recall on that benchmark is measured against the judged pool, not the whole catalogue — see
the notebook, which computes what the best possible score actually is.

### Measuring retrieval

`cbnb.eval` does not implement its own metrics. It wraps
[`ir-measures`](https://ir-measur.es/), which wraps `pytrec_eval`, which wraps `trec_eval` —
the implementation IR papers report against — so `nDCG@10` here means what a retrieval person
expects it to mean. What the notebooks keep visible is the part that is a judgement rather
than a calculation: which measures to report, and how graded labels become gains.

## Adding a notebook

See [`docs/adding-a-notebook.md`](docs/adding-a-notebook.md) for the rules that keep these
runnable, and [`CLAUDE.md`](CLAUDE.md) for the short version. Then:

```bash
make check
```

## Licence

Apache 2.0. Datasets keep their own licences, noted above.
