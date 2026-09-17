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

### Level, not a fifth track

Some notebooks teach one mechanism; some assemble several into something that resembles a
real system. That difference is a *level*, not a topic, so it is a label rather than a
directory:

- **primitive** — teaches one mechanism, in isolation, measured.
- **capstone** — composes primitives into something end-to-end. Hybrid search is the small
  version of this; "ingest unstructured, get structured + vectors" is the large one.

A capstone lives in the track of its *outcome*, and the README marks the level. This is
also the deep/shallow split: capstones are what a manager reads, because they look like a
product; primitives are what a retrieval engineer reads, because they isolate a variable.

**The rule that keeps this from becoming a junk drawer:** a capstone may only compose
techniques that a primitive already teaches, and must link to them. If a capstone is the
first place a technique appears, the primitive is missing — write that instead. Without
this constraint everything is arguably a fusion of something, and the taxonomy dies inside
a year.

### Where 00 lives

`00_check_setup` stays at `notebooks/` top level, unfiled. It belongs to no track because it
is about the reader's machine rather than any technique, and it is the one notebook the
README tells everyone to open first.

Track directories are created when their first notebook lands, not in advance — git cannot
carry an empty directory, and a tree of placeholder files is worse than no tree.

*Done 2026-09-16:* notebook 01 moved to `enrich/`. Only markdown changed (the Colab badge
path and a `../` link that became `../../`), so the ship stamp survived and no re-run was
needed. Two globs that searched `notebooks/*.ipynb` rather than `notebooks/**/*.ipynb` would
have silently stopped finding anything — `check_notebooks.py` and `run_notebook.py`. Worth
remembering for the next structural change: the failure mode is a checker that passes
because it checked nothing.

## Next up

**`00_check_setup` — what can I run right now?** *Built 2026-09-16.*
Not a demo. A reader arriving from Codespaces or Colab currently discovers whether their
setup works by running a real notebook and seeing how far it gets, which is a bad first five
minutes and the most likely place to lose someone. This notebook resolves credentials,
proves the connection, and then reports **every notebook in the repo with a verdict**: ready,
or blocked and on what.

See [Readiness](#readiness) for the mechanism — the important property is that the report is
generated from what each notebook declares, so adding a notebook never means editing this
one.

**`retrieval/01` and `/02` — build it, then test it.** *Built 2026-09-16, split 2026-09-16.*
Originally one notebook, which was a mistake worth recording: it benchmarked four retrieval
strategies and therefore assumed you already knew how to build them, so the repo had no answer
to *"how do I do hybrid search on Couchbase?"* — the question a practitioner actually arrives
with.

Now `01` is the build: vector, keyword, both in one request, then filtered, with the analyser
and prefilter details that bite people. It measures nothing, and ends by showing two queries
that pick opposite winners — so the reader reaches `02` wanting the answer rather than being
told they should care. `02` is the measurement, reusing the index `01` builds.

**The general rule this suggests:** a notebook that evaluates something needs a notebook that
builds it, and they are usually not the same notebook. `flows/01` is the deliberate exception —
its build is thin and its argument *is* the contrast between the demo and the measurement, so
splitting it would leave a build with no point and a test with no setup.

**`flows/01` — RAG you can trust.** *Built 2026-09-16.*
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
| Hybrid + filtered, measured | Shipped. Created `cbnb.eval` and the pooled WANDS benchmark. |
| Freshness — a document changes, its embedding is now a lie | The most Couchbase-native story after single-write. Almost nobody demos it. See warnings: free-tier services. |
| SQL++ and vector search in one query | Joining vector hits against structured data in one statement. A real differentiator against standalone vector stores; currently unrepresented. |
| Cost and latency engineering | Quantisation, dimension choice, `vector_index_optimized_for`, cheap-retrieve → expensive-rerank cascade. "Same accuracy, 10x cheaper" is the most manager-legible result available. |
| Multi-tenancy | Scopes and collections as tenant boundaries, tenant prefilters on vector search. Boring to build, disproportionately convincing to enterprise readers. |
| Chunking strategies, compared | Could fold into the RAG notebook or stand alone once there's a corpus. |

### `flows/`

| Idea | Note |
| --- | --- |
| RAG with citations | Shipped as *Your RAG demo works. Now prove it.* |
| Chat with memory | Working memory vs. durable memory, recall over past turns, what to forget. |
| Agent memory with `agentc` | **Pin down the actual current API surface before planning this.** Do not design from memory of the library. |
| Agentic retrieval / query planning | Includes the second-pass "fitting" idea from notebook 01: use Couchbase indexes to build a short candidate list, then a narrow refining prompt. |
| Text-to-SQL++ with a safety net | Tool-calling over the query service with guardrails. Pairs with the single-query idea above. |

### `enrich/`

| Idea | Note |
| --- | --- |
| Hypothetical classification | Shipped. |
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

### Don't write the metrics

For layer 1, use [`ir-measures`](https://ir-measur.es/), which wraps `pytrec_eval` — Python
bindings to `trec_eval`, the reference implementation the IR literature reports against.

Two reasons this beats hand-rolling. It removes the silently-wrong-NDCG risk, which would
poison every claim in the repo. And "our numbers come from `trec_eval`" is a credibility
argument with exactly the audience these notebooks are aimed at — a hand-rolled metric
invites a discount that no amount of prose removes.

Verified 2026-09-16, because the obvious worry is a hostile install: `ir-measures` 0.4.3 is
pure Python and its only hard dependency is `pytrec-eval-terrier` 0.5.10, which ships binary
wheels for macOS universal2, manylinux, musllinux and win_amd64 and needs only numpy and
scipy — both already in the venv. No compiler, no Java. The dragons are all in optional
extras nobody has to install (`gdeval` wants Perl; `trectools`, `ranx`, `cwl_eval` are
extras). Smoke-tested in a throwaway venv: `nDCG@10`, `R@10`, `RR` and `AP` computed from
plain qrels/run dicts.

**Using a standard library makes the teaching easier, not harder.** Metric *implementation*
is plumbing; metric *choice* is the technique, and it is the conversation worth having.
Recall@10 and NDCG@10 disagree about which system is better, and the disagreement is the
lesson: recall is what matters when a reranker runs next and only needs the right document
somewhere in the pool; NDCG is what matters when a human reads the list top-down. Make that
a **result** in `retrieval/01` rather than an aside — show two systems where the ranking
flips depending on the metric, and the reader learns more than any explanation delivers.

### Layers 2–4: defer

[Unitxt](https://github.com/IBM/unitxt) (IBM, the one you were thinking of — Apache 2.0,
actively developed, includes an LLM-as-judge catalog) and
[Ragas](https://pypi.org/project/ragas/) are the serious options, and both want to own more
of the pipeline than we should hand over yet. Ragas 0.4.3 alone pulls `datasets`,
`instructor`, `tiktoken`, `typer`, `rich` and its own `openai` usage, which collides with
`cbnb.llm`.

Revisit when `flows/` exists and there is an actual judging need. Deciding now would be
choosing a framework before having the problem.

**Practical constraints worth designing around now:** LLM-as-judge is the usual answer for
layers 2–4 and it is both expensive and non-deterministic, which fights the goal of
committed outputs that reproduce. Prefer judgement sets and deterministic metrics where they
exist; where a judge is unavoidable, cache aggressively (we already cache), pin the judge
model, and state in the notebook that the number came from one specific run.

## Readiness

Every notebook declares what it needs. One library checks those declarations. Two things
consume it, and neither needs editing when a notebook is added.

**Declaration.** The bootstrap cell already exists in every notebook and is already copied
verbatim; requirements ride along with it rather than introducing new ceremony:

```python
cbnb.bootstrap(requires=["couchbase", "llm", "embeddings-local"])
```

**Consumer one — the notebook itself.** `bootstrap()` checks the requirements it was given
and fails immediately, with a specific message, instead of dying in cell 12 with a
`KeyError`. This is the part that helps a reader who is actually running the thing.

**Consumer two — `00_check_setup`.** Reads every notebook's declaration statically (`ast`
over the bootstrap cell — never by executing them), probes the environment once, and prints
the matrix. A new notebook appears in the report because it declared, not because anyone
remembered to register it.

**Capabilities are named, coarse, and few.** Starting set: `couchbase`, `llm`,
`embeddings-local`, `embeddings-api`, `dataset-download`, `ram-8gb`. Resist making these
fine-grained — the point is a reader-legible verdict, not a dependency solver.

**Probes must be real.** `llm` means a live call succeeded, not that a key is present. The
NanoGPT key that was silently rejected for a whole debugging session is the motivating case:
a key-is-set check would have reported green.

**Keeping the human and machine copies honest.** The notebook header's `Requires` line is
for readers; the `bootstrap(requires=...)` call is what executes. `check_notebooks.py` should
verify they agree, the way it already verifies the bootstrap cell and ship state.

### Two modules, not one

A library that notebooks import, which also knows about those notebooks, would be an
uncomfortable coupling — not a true cycle, but the kind of thing that rots. Keep the two
directions in separate modules that don't reference each other:

| Module | Answers | Knows about |
| --- | --- | --- |
| `cbnb.readiness` | "What can this environment do?" | Capabilities. Nothing about notebooks. |
| `cbnb.inventory` | "What does each notebook ask for?" | Notebook *files* on disk — read as data, never imported or executed. |

Notebooks depend on `readiness` only. `inventory` depends on neither notebooks-as-code nor
`readiness`. **`00_check_setup` is the only place the two meet**, and all it does is join two
lists. Couplings belong at the top of the stack, where they're visible, not buried in a
library that everything imports.

This also keeps `cbnb.readiness` — which ships to every Colab reader — free of any knowledge
of repo layout.

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

**Fixed header on every notebook** — above everything else:

```markdown
**Claim.** One sentence: what this notebook demonstrates.
**Result.** The measured number, from the run stored in this file.
**Requires.** couchbase · llm · embeddings-local
**Read** ~N min · **Run** ~N min · **Cost** ~$N.NN
```

`Requires` must match the notebook's `bootstrap(requires=[...])` call — see
[Readiness](#readiness).

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

Expected new modules: `cbnb.eval` (judgement-set loading and alignment, significance testing
— notebook 01's McNemar test belongs here — and a thin pass-through to `ir-measures`, *not*
hand-written metrics), `cbnb.readiness`, `cbnb.inventory`, `cbnb.chunk`, and considerable
growth in `cbnb.datasets`.

**One caveat specific to eval:** a black-box metric undermines you with precisely the
retrieval audience these notebooks are for. Whatever lives in `cbnb.eval` carries the exact
formula in its docstring, and the notebook states it in markdown next to the number. The code
may be hidden; the definition may not. Same split for judges later — harness, caching and
parsing in `cbnb`; the rubric text stays in the notebook, because the rubric *is* the
technique.

**Relevance mapping is never plumbing.** WANDS grades are Exact / Partial / Irrelevant, and
how those become gains changes the numbers. That mapping is a judgement call and stays
visible in the notebook.

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

## Decided

Settled 2026-09-16. Recorded so they don't get re-litigated.

**Structured extraction is two notebooks, not one.** `enrich/` is about the model's output —
prompt and schema design, failure modes, confidence gating. `data-model/` is about the
document's shape — what one write produces and what it then enables. They share a corpus and
loader, which halves the expensive part. `data-model/` goes first with deliberately dumb
extraction; `enrich/` comes back and makes the fields good.

**No 5-minute tour.** It solves a navigation problem that doesn't exist below roughly eight
notebooks, and duplicates content that the README table and committed outputs already deliver
to a skimmer. Revisit at eight. `00_check_setup` is what was actually missing.

**Primitive vs. capstone is a label, not a directory.** See
[Level, not a fifth track](#level-not-a-fifth-track).

**Metrics come from `ir-measures`; judgement stays in the notebook.** See
[Don't write the metrics](#dont-write-the-metrics). Layers 2–4 deferred until `flows/` exists.

**`make retarget REPO=owner/name`.** Build it when the second notebook lands — two notebooks
to prove it against, ~20 lines. The repo URL is already duplicated per notebook (badge plus
`REPO_URL` in the setup cell), so this is worth having whether or not the repo ever moves. If
it does move to a work org, do it in the same pass as relocating notebook 01 into `enrich/` —
both change paths, both break shared links, so break them once. Also worth checking team
norms about the history being authored under a personal email.

## The corpus decision

*Settled 2026-09-16.* `flows/` and `data-model/` use **CUAD** — the Contract Understanding
Atticus Dataset, CC BY 4.0, 510 SEC-filed commercial contracts with lawyer-written
annotations for 41 clause categories, each a character span.

**Why not the obvious ones.** The canonical RAG benchmark is the TREC RAG track, built on MS
MARCO — and MS MARCO is *non-commercial research only*, which rules it out. That blocker
spreads: SciFact is CC BY-NC, NFCorpus and FiQA are non-commercial, and the HuggingFace BEIR
mirrors tag them CC BY-SA 4.0 in contradiction of the upstream terms, so the tag cannot be
trusted. RAGBench looks clean at CC BY 4.0 but is assembled from twelve datasets including
`msmarco` and `cuad`, and an aggregate tag cannot launder a non-commercial component.

HotpotQA (CC BY-SA 4.0) and Natural Questions (CC BY-SA 3.0) are usable and were the
runners-up. They lose on the second criterion below.

**What CUAD buys that Wikipedia QA does not.** The 41 clause categories are a ready-made
extraction schema — parties, agreement date, effective date, expiration date, governing law,
renewal term. That makes the same documents serve `data-model/` (extract structure on the
write path) and then `retrieval/` (filter on the extracted fields *and* vector search *and*
full text, in one query). One corpus, four tracks, where the later notebooks are more
interesting because the earlier ones enriched the data — which is the argument for a document
database, demonstrated rather than asserted.

**The property that makes it honest: 62% of the questions have no answer in their contract.**
Most contracts have no source-code-escrow clause, and the correct response is "not in this
document". A RAG system that always answers confidently is wrong most of the time on this
distribution, and no hand-picked demo query will ever show that. That is the spine of
`flows/01`.

**Known caveats.** The annotations are CC BY 4.0; the underlying contracts are EDGAR filings
whose licence status the CUAD authors explicitly do not warrant — worth an internal glance
before this repo goes anywhere official. Queries are expert-written rather than natural search
queries. And the domain is narrow: legal contracts are legible to an enterprise audience and
duller than Wikipedia to everyone else.

**On training-data contamination.** MS MARCO is in almost every embedding model's training
mixture, and so are NQ and HotpotQA (GTE and BGE both train on all three), which undercuts
BEIR's zero-shot framing. Contracts are not standard retrieval training data. This is worth
one aside in a notebook and is *not* the reason for the choice — these notebooks teach
approaches, they do not claim a recall breakthrough.

## Fixed along the way

**Numeric and datetime index fields.** *2026-09-16.* `vector_index_definition` emitted only
text and keyword fields, so `NumericRangeQuery` and `DateRangeQuery` had nothing to match —
and a range query against a field absent from the mapping matches **nothing and raises
nothing**. In `flows/01` that surfaced as empty retrieval and a model reporting "the excerpts
are empty", which reads as a bad model rather than a bad filter.

`numeric_fields=` and `datetime_fields=` now exist and are verified against a live cluster
(filtering chunks by `contract_id` and by character offset), including that re-running does
*not* force an index rebuild.

The silent half needed its own answer, because the fix does not stop anyone filtering on a
field they forgot to declare. `indexed_fields(cluster, ...)` reads back what a live index
actually covers, as `{field: type}` — the first thing to check when a filter returns zero rows.

An identifier is still better as a keyword than a number, so `flows/01` keeps its
`contract_key` filter; the gap mattered for `data-model/`, which filters on extracted dates
and amounts.

## Still open

- **A recall figure is meaningless without its ceiling.** WANDS judges a median of 125
  products relevant per query, so the best possible R@50 on this benchmark is 0.462 — the
  strategies reach 87% of that. Any future notebook reporting recall must report what was
  achievable, or it is quoting a number that looks like a failure and isn't.
- Which corpus serves `flows/` and `data-model/`? This is the gating decision for both
  tracks, and the most expensive one to get wrong.
- Does `agentc` merit a notebook at all, or a section inside the chat-with-memory one?
  Unanswerable until its current API is actually read.
