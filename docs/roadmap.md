# Roadmap

What gets built next, how it's organised, and the traps we already know about.

This is a working document — edit it rather than re-deriving the plan. Nothing here is a
commitment; the order is a recommendation and the backlog is deliberately longer than what
will ever get built.

## Tracks

Four tracks, each a directory. Notebook numbers restart inside a track and encode
difficulty-within-track, not global reading order. The root `README.md` carries reading
order, because that is the page people actually land on.

```
notebooks/retrieval/    Recall mechanics: vector, hybrid, filtered, rerank, freshness
notebooks/flows/        AI-powered applications: RAG, chat with memory, agents
notebooks/enrich/       AI on the write path: classification, extraction, normalisation
notebooks/data-model/   One document, many views — Couchbase-specific data modelling
```

**On `data-model/`:** this is the "single write" track, but pitched as *one document, many
views*. Structured fields, extracted entities, raw text, and vectors land in one document, in
one write, in one transaction — no dual-write consistency problem, no sync job between a
document store and a vector store. That framing sells itself; "single write capability" needs
a paragraph of setup before anyone cares.

**Agent memory belongs in `flows/`, not `retrieval/`.** Mechanically it is vector recall.
But a reader looking for "how do I make my chatbot remember" will never look under vector
search, and the interesting part is the flow, not the index.

**Evaluation is not a track.** It runs through all four — see below.

### Moving notebook 01

`01_hypothetical_classification` belongs in `enrich/`. Moving it costs us: the Colab and
Codespaces badges embed the path, and any link already shared breaks. The repo is days old,
so now is the cheapest this will ever be. Do it as part of building 02, not before.

## Next up

**`retrieval/01` — Hybrid and filtered retrieval, measured.**
WANDS ships 480 queries and 233k relevance judgements that we currently ignore. Compare
BM25, vector, hybrid, and filtered-hybrid over the same queries with NDCG@10 and recall@50.
No new dataset, no new LLM spend. Two reasons it goes first: it is the notebook retrieval
people will judge the whole repo by, and it forces `cbnb.eval` into existence — which
everything after it needs in order to make an honest claim.

**`flows/01` — RAG with citations.**
Deliberately stresses what 01 and 02 did not: a prose corpus, chunking and parent/child
document modelling, retrieval → generation, and groundedness checking. Third rather than
second because it needs `cbnb.eval` to say anything true about whether the answers are
right.

That ordering builds a measurement spine before building the things that need measuring.

## Backlog

Ordered roughly by value within each track. Nothing here is scheduled.

### `retrieval/`

| Idea | Note |
| --- | --- |
| Hybrid + filtered, measured | Next up. Creates `cbnb.eval`. |
| Freshness — a document changes, its embedding is now a lie | The most Couchbase-native story after single-write. Almost nobody demos it. See warnings: free-tier services. |
| SQL++ and vector search in one query | Joining vector hits against structured data in one statement. A real differentiator against standalone vector stores; currently unrepresented. |
| Cost and latency engineering | Quantisation, dimension choice, `vector_index_optimized_for`, cheap-retrieve → expensive-rerank cascade. "Same accuracy, 10x cheaper" is the most manager-legible result available. |
| Multi-tenancy | Scopes and collections as tenant boundaries, tenant prefilters on vector search. Boring to build, disproportionately convincing to enterprise readers. |
| Chunking strategies, compared | Could fold into the RAG notebook or stand alone once there's a corpus. |

### `flows/`

| Idea | Note |
| --- | --- |
| RAG with citations | Next up after 02. |
| Chat with memory | Working memory vs. durable memory, recall over past turns, what to forget. |
| Agent memory with `agentc` | **Pin down the actual current API surface before planning this.** Do not design from memory of the library. |
| Agentic retrieval / query planning | Includes the second-pass "fitting" idea from notebook 01: use Couchbase indexes to build a short candidate list, then a narrow refining prompt. |
| Text-to-SQL++ with a safety net | Tool-calling over the query service with guardrails. Pairs with the single-query idea above. |

### `enrich/`

| Idea | Note |
| --- | --- |
| Hypothetical classification | Shipped (currently `notebooks/01_...`). |
| Structured extraction from unstructured text | Overlaps `data-model/`; decide which one owns it. |
| Language normalisation | Units, sizes, colours, brand variants — unglamorous and extremely real. |
| Translation / multilingual retrieval | **Blocked on a dataset with a usable licence.** See warnings. |
| Enrichment quality gates | When to accept the model's answer and when to route to a human. Pairs with eval. |

### `data-model/`

| Idea | Note |
| --- | --- |
| Ingest unstructured, get structured + vectors in one write | The flagship. |
| Parent/child chunk modelling | Where chunks live relative to their source document; subdocument operations. |
| Schema evolution | Re-extracting when the extraction prompt improves, without a migration. |

## Evaluation

This is the spine, and it deserves more attention than a demo repo usually gives it. It is
the difference between a demo and an argument, and it is the part a manager can read.

Build it bottom-up — each layer only means something if the layer beneath it holds:

1. **Retrieval quality.** recall@k, NDCG@k, MRR against judgements. WANDS gives this to us
   for free today. Everything else rests here: an agent cannot be right about documents it
   never retrieved.
2. **Groundedness / faithfulness.** Does the answer actually follow from the retrieved
   context, or did the model fill the gap? (*Faithfulness* is probably the word that goes
   with "prompt fidelity" — it is the standard term for answer-follows-from-context. If the
   question is instead "did it obey the format and constraints I gave it", that is
   *instruction-following*.)
3. **Answer correctness.** Separate from groundedness: an answer can be faithful to a
   retrieved passage that was itself wrong or irrelevant.
4. **Trajectory / task completion.** Did the agent do what was asked, and how often? Step
   accuracy, tool-call correctness, completion rate.
5. **Stability.** Same input, same result across runs and model versions. Cheap to measure,
   and the thing that actually breaks in production.

Layer 4 is where Couchbase's agent tracking is genuinely interesting as *infrastructure*
rather than as a feature demo — traces of what an agent did, queryable, aggregated over
many runs. See the AIDP rule below for how to handle that.

**Practical constraints worth designing around now:** LLM-as-judge is the usual answer for
layers 2–4 and it is both expensive and non-deterministic, which fights the goal of
committed outputs that reproduce. Prefer judgement sets and deterministic metrics where they
exist; where a judge is unavoidable, cache aggressively (we already cache), pin the judge
model, and state in the notebook that the number came from one specific run.

## Couchbase AI Data Plane

**The rule:** every notebook runs free on Capella's free tier or Couchbase Enterprise. Where
a managed capability would replace hand-rolled code, name it in an aside rather than
requiring it.

**Format,** so it is greppable and readers learn to recognise it — a blockquote at the end
of the relevant section, always with this exact heading:

```markdown
> **On Couchbase AI Data Plane** — <what the managed service does instead, in two or three
> sentences, and when it's worth it.>
```

**The known exception:** agent tracking for evaluation (layer 4 above) may not have a
sensible hand-rolled equivalent worth teaching. If a notebook ends up genuinely requiring
AIDP, mark it clearly in its header and in the README table so nobody starts it expecting
the free path. One such notebook is fine. Three means the rule has quietly died.

## Conventions

To adopt as these get built. Once settled, the durable ones move into
[`adding-a-notebook.md`](adding-a-notebook.md), which is the enforced list.

**Fixed header on every notebook** — four lines, above everything else:

```markdown
**Claim.** One sentence: what this notebook demonstrates.
**Result.** The measured number, from the run stored in this file.
**Read** ~N min · **Run** ~N min · **Cost** ~$N.NN
```

**The README is a results table.** One row per notebook with its headline metric. That table
is the entire experience for a reader who will never run anything, and it stays honest
because the numbers come from committed runs.

**`<details>` for the gnarly parts.** Index JSON, search DSL, failure analysis. GitHub
renders them collapsed. Practitioners open them; everyone else scrolls past and the notebook
still reads clean.

**A shared `docs/concepts.md`.** Link into it rather than re-explaining dot_product vs.
cosine for the fourth time. Keeps each notebook lean and stops notebook 07 from re-teaching
notebook 02.

**"Where to take this" close.** Notebook 01 does this well; it is the section that makes a
reader think about their own data.

**The `cbnb` boundary.** The library will get pulled on hard by the next three notebooks —
eval, chunking, more datasets. The failure mode is `cbnb` quietly absorbing the interesting
parts until every notebook is six function calls and teaches nothing.

> `cbnb` owns plumbing: connections, credentials, caching, progress, dataset loading.
> If a reader would want to copy it into their own project, it stays visible in the notebook.

Expected new modules: `cbnb.eval` (metrics, judgement sets, significance testing — notebook
01's McNemar test belongs here), `cbnb.chunk`, and considerable growth in `cbnb.datasets`.

## Warnings

Things we already know will hurt.

**Datasets are the real cost, and it grows.** WANDS carries `retrieval/` and `enrich/`
almost entirely, which makes the current situation look easier than it is. `flows/` and
`data-model/` need prose, and every new corpus is licence review + loader + committed sample
+ citation before a single cell of the actual technique gets written. Budget for the dataset
as a first-class part of each notebook, not a prerequisite to rush through. Where one corpus
can serve two notebooks, that is worth real design effort.

**Translation and multilingual data: licence risk.** Many of the obvious multilingual
corpora are share-alike, research-only, or assembled from sources with murky provenance.
This repo is public and Apache 2.0. Do not start the translation notebook until a corpus
clears review — and check the actual licence file, not the README's claim about it.

**Free-tier service availability is unverified.** The freshness notebook wants
mutation-driven re-embedding, which may mean Eventing — and it is not confirmed that
Capella's free tier includes it. Verify before designing around it. An SDK-side version
using a `needs_embedding` flag runs anywhere and is arguably the better teaching artifact
regardless.

**`agentc` API churn.** The library is young. Anything built on it will need re-verification
at build time and may need maintenance afterwards. Do not plan its notebook from
recollection of the API.

**Committed outputs go stale.** Model providers deprecate models and change behaviour under
a fixed name. Every notebook's stored result is a claim about a specific run with a specific
model. The header's "Result" line should say so, and `make ship` will need running more
often than feels necessary.

**Notebook run cost compounds.** Each notebook that calls an LLM over a dataset costs real
money every time it ships. Caching helps during development and does nothing for a fresh
reader. Keep default sample sizes small and make the full run opt-in.

**Scope creep per notebook.** Every idea in the backlog wants to be three notebooks. A
notebook that demonstrates two things demonstrates neither. When one splits, split it.

## Open questions

- Does `enrich/` or `data-model/` own structured extraction? They overlap badly.
- Is there a "5-minute tour" notebook worth building — a sampler that runs three things fast
  as top-of-funnel? It would help the shallow read, and it duplicates content.
- How much of eval belongs in `cbnb.eval` versus visible in notebooks? Metrics are plumbing;
  the choice of what to measure is the technique.
- Does the repo move to a work GitHub org? Badges and `REPO_URL` in every notebook would
  need updating — a `make` target for that would pay for itself.
