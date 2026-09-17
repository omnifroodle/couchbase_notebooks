# Roadmap

What exists, what comes next, how it's organised, and the traps already paid for.

A working document — edit it rather than re-deriving the plan. Nothing here is a commitment;
the backlog is deliberately longer than what will ever get built.

---

## The thesis

**Eval matters, and "it looks good on my machine with my queries" will not get you far.**

That is what the series is for. The audience is practitioners trying to understand these
approaches and how Couchbase serves them — not researchers, and there is no recall
breakthrough on offer. But every notebook that makes a claim measures it, and more than once
the measurement has contradicted the claim the notebook was designed around. Rewriting the
claim is the correct outcome, and the habit worth teaching.

## Tracks

Four tracks, each a directory. Numbers restart inside a track. The root `README.md` carries
reading order, because that is the page people land on.

```
notebooks/retrieval/    Recall mechanics: vector, hybrid, filtered, rerank, freshness
notebooks/flows/        AI-powered applications: RAG, chat with memory, agents
notebooks/enrich/       AI on the write path: classification, extraction, normalisation
notebooks/data-model/   One document, many views — Couchbase-specific data modelling
```

**On `data-model/`:** the "single write" track, pitched as *one document, many views*.
Structured fields, extracted entities, raw text and vectors on one document, written once — no
dual-write problem, no sync job between a document store and a vector store. That framing sells
itself; "single write capability" needs a paragraph of setup before anyone cares.

**Agent memory belongs in `flows/`, not `retrieval/`.** Mechanically it is vector recall, but a
reader looking for "how do I make my chatbot remember" will never look under vector search, and
the interesting part is the flow.

**Evaluation is not a track.** It runs through all four.

**`00_check_setup` is unfiled**, at `notebooks/` top level. It belongs to no track because it is
about the reader's machine. Track directories are created when their first notebook lands — git
cannot carry an empty directory, and placeholder files are worse than no tree.

## Built

| | Notebook | Notes |
| --- | --- | --- |
| 2026-09-14 | `enrich/01` hypothetical classification | The first one. Started as `notebooks/01_`, moved to `enrich/` on 09-16. |
| 2026-09-16 | `00_check_setup` | Not a demo — a readiness report. See [Readiness](#readiness). |
| 2026-09-16 | `retrieval/01` building hybrid search | The mechanics, measuring nothing. |
| 2026-09-16 | `retrieval/02` which parts helped | The measurement, reusing `01`'s index. |
| 2026-09-16 | `flows/01` RAG you can trust | The thesis in full: a demo that works, then 820 judged questions. |
| 2026-09-16 | `data-model/01` documents that learn | Extract, attach (embedded *and* referenced), query with SQL++. |
| 2026-09-16 | `data-model/02` adding retrieval | Chunks as derived documents; what a search index's inability to join forces. |
| 2026-09-17 | `enrich/02` scoring the extraction | Closes the gap `data-model/01` left. Four fields, four scoring rules, and two self-checks that both fall short. |
| 2026-09-17 | `retrieval/03` retrieve wide, rerank narrow | A cross-encoder over the shortlist. The first attempt failed — see below — and that became the notebook's argument. |

### What the retrieval split taught

`retrieval` was originally one notebook, and that was a mistake worth recording: it benchmarked
four strategies and therefore assumed you already knew how to build them, so the repo had no
answer to *"how do I do hybrid search on Couchbase?"* — the question a practitioner actually
arrives with. Two of the three notebooks at the time were evaluation notebooks.

**The rule that falls out:** a notebook that evaluates something needs a notebook that builds
it, and they are usually not the same notebook. `flows/01` is the deliberate exception — its
build is thin and its argument *is* the contrast between demo and measurement, so splitting it
would leave a build with no point and a test with no setup.

## Next up

Nothing is scheduled. In rough order of value:

1. **`flows/03` — agentic search.** Search, judge the results, search again. The sceptical
   framing is the useful one: an agent loop is a bet that fixed classifiers and fixed `k` are
   too rigid, and it is expensive, so it has to beat single-shot retrieval and rerank on the
   same judgements to earn its place. Lands in `flows/` for the same reason agent memory does —
   the loop is the subject, not the recall mechanics. Its baseline now exists (`retrieval/03`),
   and it needs evaluation layers 4 (trajectory) and 5 (stability), neither of which
   any notebook has yet. Plain vector search already drifts ~0.005 nDCG between runs; an agent
   deciding when to stop will drift further, so one run of it proves nothing.
2. **`flows/02` — chat with memory.** Working vs. durable memory, recall over past turns, what
   to forget. Needs a conversation corpus, which is the usual blocker.
3. **`data-model/03` — schema evolution.** Re-extract with a better prompt; the interesting
   question is which documents *changed*, which is a diff rather than a rebuild. `extracted_at`
   is already on every derived document for this.

## Backlog

### `retrieval/`

| Idea | Note |
| --- | --- |
| Retrieve wide, rerank narrow | Shipped as `retrieval/03`. |
| Freshness — a document changes, its embedding is now a lie | The most Couchbase-native story after single-write, and almost nobody demos it. Eventing is the natural trigger but is **paid-tier on Capella**, so a runnable version needs an SDK-side `needs_embedding` flag. |
| SQL++ and vector search in one query | `data-model/01` uses SQL++ and `/02` uses filtered vector search, but nothing yet joins vector hits to structured data in a single statement. A real differentiator against standalone vector stores. |
| Cost and latency engineering | Quantisation, dimension choice, `vector_index_optimized_for`. |
| **Couchbase has more than one vector index** | Search-service vector fields (what every notebook here uses), and 8.0's Composite and Hyperscale vector indexes on the Index service, queried by SQL++ with different defaults — Hyperscale quantises by default, the Search index at `recall` does not. Worth its own notebook: which index for which job, and what each costs in memory, QPS and accuracy. Until then no notebook may imply there is only one. |
| Multi-tenancy | Scopes and collections as tenant boundaries. Boring to build, disproportionately convincing to enterprise readers. |
| Chunking strategies, compared | `flows/01` has the ground truth to score them against — fixed 1,200-character windows are a guess nobody has checked. |

### `flows/`

| Idea | Note |
| --- | --- |
| Chat with memory | See Next up. |
| Agent memory with `agentc` | **Read the current API before planning it.** Do not design from recollection. |
| Agentic retrieval / query planning | Promoted to Next up as `flows/03`. Still includes the second-pass "fitting" idea from `enrich/01`: use Couchbase indexes to build a short candidate list, then a narrow refining prompt. |
| Text-to-SQL++ with a safety net | Tool-calling over the query service with guardrails. |

### `enrich/`

| Idea | Note |
| --- | --- |
| Scoring the extraction | Shipped as `enrich/02`. |
| Language normalisation | Units, sizes, colours, brand variants — unglamorous and extremely real. |
| Translation / multilingual retrieval | **Blocked on a corpus with a usable licence.** See warnings. |
| Enrichment quality gates | When to accept the model's answer and when to route to a human. |

### `data-model/`

| Idea | Note |
| --- | --- |
| Schema evolution | See Next up. |
| Time-travel / versioned enrichment | `::terms::v2` beside `::terms`, and queries that pick a version. Falls out of the referencing pattern `01` establishes. |

---

## Evaluation

The spine. Build it bottom-up — each layer only means something if the one beneath it holds:

1. **Retrieval quality.** recall@k, nDCG@k, MRR against judgements. Everything else rests here:
   a system cannot be right about documents it never retrieved. *Done in `retrieval/02`.*
2. **Groundedness / faithfulness.** Does the answer follow from the retrieved context, or did
   the model fill the gap? (*Faithfulness* is the standard term for answer-follows-from-context;
   "did it obey the format I gave it" is *instruction-following*.) *Done in `flows/01`.*
3. **Answer correctness.** Separate from groundedness: an answer can be faithful to a passage
   that was itself wrong.
4. **Trajectory / task completion.** Did the agent do what was asked, and how often?
5. **Stability.** Same input, same result across runs and model versions. Cheap to measure, and
   the thing that actually breaks in production.

Layer 4 is where Couchbase's agent tracking is interesting as *infrastructure* rather than as a
feature demo. See [the AIDP rule](#couchbase-ai-data-plane).

### Don't write the metrics

Layer 1 uses [`ir-measures`](https://ir-measur.es/) → `pytrec_eval` → `trec_eval`, the
reference implementation the IR literature reports against. It removes the
silently-wrong-nDCG risk, and "our numbers come from `trec_eval`" is a credibility argument
with exactly this audience.

Verified 2026-09-16: `ir-measures` is pure Python; its only hard dependency,
`pytrec-eval-terrier`, ships binary wheels for macOS, manylinux, musllinux and win_amd64 and
needs only numpy and scipy. No compiler, no Java. The dragons are all in optional extras nobody
installs.

**Using a standard library makes the teaching easier, not harder.** Metric *implementation* is
plumbing; metric *choice* is the technique. Recall@10 and nDCG@10 disagree about which system is
better, and the disagreement is the lesson — `retrieval/02` makes it a result rather than an
aside.

### Layers 2–4: prefer deterministic grading

`flows/01` grades without a judge at all: the model must return a verbatim quote, and the quote
either lands inside a lawyer's annotated span or it does not. Five deterministic outcomes, no
second model's opinion. **Do that wherever the data allows it** — it is cheaper, reproducible,
and immune to the failure mode below.

Where a judge is unavoidable: [Unitxt](https://github.com/IBM/unitxt) (IBM, Apache 2.0) and
[Ragas](https://pypi.org/project/ragas/) are the serious options, and both want to own more of
the pipeline than is worth handing over. Ragas alone pulls `datasets`, `instructor`, `tiktoken`,
`typer`, `rich` and its own `openai` usage, which collides with `cbnb.llm`.

**The failure mode, observed.** Asked to interpret a results table,
[`cbnb.review`](../cbnb/review.py)'s first live run correctly pushed back on two wrong
expectations and then **invented a count** — "73 vs 73" where the table implied 73 vs 107 — in
the sentence claiming to identify the *solid* comparison. Tightening the prompt against derived
arithmetic removed it, but that is evidence about one prompt and one model. LLM output about
numbers is not a measurement.

## Readiness

Every notebook declares what it needs. One library checks those declarations. Two things consume
it, and neither needs editing when a notebook is added.

**Declaration**, riding on the bootstrap cell that every notebook already copies verbatim:

```python
cbnb.bootstrap(requires=["couchbase", "llm", "local-embeddings"])
```

**Consumer one — the notebook.** `bootstrap()` checks and fails immediately with a specific
message, instead of dying in cell 12 with a `KeyError`.

**Consumer two — `00_check_setup`.** Reads every notebook's declaration statically (`ast` over
the bootstrap cell — never by executing them), probes the environment once, prints the matrix. A
new notebook appears because it declared, not because anyone registered it.

**Capabilities are named, coarse and few:** `couchbase`, `llm`, `local-embeddings`,
`api-embeddings`, `dataset-download`, `ram-8gb`. Resist making them fine-grained — the point is a
reader-legible verdict, not a dependency solver.

**Probes must be real.** `llm` means a live call succeeded, not that a key is present. The
NanoGPT key that was silently rejected for a whole debugging session is the motivating case: a
key-is-set check would have reported green.

**Both copies stay honest.** The header's `Requires` line is for readers; the
`bootstrap(requires=...)` call is what executes. `check_notebooks.py` fails if they disagree.

### Two modules, not one

A library that notebooks import, which also knows about those notebooks, is an uncomfortable
coupling — not a cycle, but the kind of thing that rots.

| Module | Answers | Knows about |
| --- | --- | --- |
| `cbnb.readiness` | "What can this environment do?" | Capabilities. Nothing about notebooks. |
| `cbnb.inventory` | "What does each notebook ask for?" | Notebook *files* — read as data, never imported or executed. |

**`00_check_setup` is the only place the two meet.** Couplings belong at the top of the stack
where they are visible, not buried in a library everything imports. It also keeps
`cbnb.readiness` — which ships to every Colab reader — free of any knowledge of repo layout.

### Reranking means a second model. Nothing else gets the word

Researched 2026-09-17, before `retrieval/03` exists, because Couchbase's docs use `rerank` for
something else and a notebook that repeats that usage would teach the confusion.

**Reranking, as the field uses it:** a second model — usually a cross-encoder — re-scores the
top candidates by reading query and document *together*, instead of comparing two independently
produced vectors. Couchbase does not do this for you: it is your model, run over the candidates
a Couchbase search returned. A small cross-encoder on `sentence-transformers` keeps `03` free
and offline. Its usual training corpus is MS MARCO; WANDS is not, so the contamination footnote
does not apply here.

**What the `rerank` argument in
[the Hyperscale docs](https://docs.couchbase.com/server/current/vector-index/hyperscale-reranking.html)
does** is re-score with full-precision vectors, undoing quantisation error. Same model, same
embedding, better arithmetic — no second opinion about relevance anywhere in it. Write it as
*full-precision re-scoring*, and if the argument's name has to appear, say plainly that what
this flag calls reranking is not what the term means elsewhere. Cost: QPS, and index size
(269KiB → 1.17MiB in their example).

**Why that flag exists — and what it says about defaults.** A **Hyperscale Vector index**
(Index service, SQL++, Couchbase 8.0) defaults to `IVF,SQ8`: inverted file, scalar quantisation
at 8 bits per dimension. **It searches the quantised vectors by default**, which is what the
flag is there to walk back.

**These notebooks are not affected — measured, 2026-09-17, not inferred.** They use a
**Search-service** index with `vector_index_optimized_for: "recall"`, where the docs confine
quantisation to the `memory-efficient` option (7.6.4+, inverted file with scalar quantisation).
On a live cluster, `products_hybrid` reports no quantisation setting at all, and its returned
scores match a float32 dot product computed locally to ~1e-7 — float32 rounding. SQ8 would err
around 1e-3. So scoring there is full precision.

**That is about scoring, not candidate selection.** Exact arithmetic on an approximately chosen
candidate set is still approximate retrieval, and the graph traversal that picks the candidates
is the likelier source of `retrieval/02`'s run-to-run drift. Do not let one get written as
evidence for the other.

**Capella's Model Service is Enterprise Support only**, so a hosted reranking model — if it
offers one, which the docs do not say — is an aside, not a dependency.

## Couchbase AI Data Plane

**The rule:** every notebook runs free on Capella's free tier or Couchbase Enterprise. Where a
managed capability would replace hand-rolled code, name it in an aside rather than requiring it.

**Format**, so it is greppable and readers learn to recognise it — a blockquote at the end of
the relevant section, always with this exact heading:

```markdown
> **On Couchbase AI Data Plane** — <what the managed service does instead, in two or three
> sentences, and when it's worth it.>
```

**The same rule caught Eventing.** It is the natural trigger for write-path enrichment and it
can call a model through a cURL binding — but it is **paid-tier on Capella**, so it gets an
aside, not a notebook. Two details worth keeping if one is ever written: a multi-second model
call belongs in a **Timer callback** that `OnUpdate` enqueues, because a slow handler builds a
backlog; and a handler writing back to the collection it watches **re-triggers itself**, which
is what `data-model/01`'s `enriched_at` marker guards against.

**The known exception:** agent tracking for evaluation (layer 4) may have no hand-rolled
equivalent worth teaching. If a notebook genuinely requires AIDP, mark it in its header and in
the README so nobody starts it expecting the free path. One such notebook is fine. Three means
the rule has quietly died.

## Conventions

The enforced ones live in [`adding-a-notebook.md`](adding-a-notebook.md). These are the ones
that shape what gets written.

**Introduce the well-known concept in Couchbase's terms first, then build on it.** Extraction
with an LLM needs no selling; what happens to the *document* afterwards does. A notebook that
opens on the novel technique skips the audience that came for the mechanics. This is why
`retrieval` splits build-then-test and why `data-model/01` stops before vectors.

**Start simple and build across a series.** The first draft of `data-model/01` went from raw text
to a four-field-type polyglot query in one notebook. Split at the natural seam.

**Fixed header on every notebook:**

```markdown
**Claim.** One sentence: what this notebook demonstrates.
**Result.** The measured number, from the run stored in this file.
**Requires.** couchbase · llm · local-embeddings
**Read** ~N min · **Run** ~N min · **Cost** ~$N.NN
```

**Write the claim after the run, not before.** Three notebooks so far have shipped with a claim
different from the one they were designed around, because the measurement disagreed.
`make review` exists to catch the cases where the prose and the stored outputs drift apart.

**The README is a results table.** One row per notebook with its headline metric — the entire
experience for a reader who will never run anything.

**`<details>` for the gnarly parts.** Index JSON, search DSL, failure analysis. Practitioners
open them; everyone else scrolls past.

**"Where to take this" close**, and link to the notebook that continues the thread.

**The `cbnb` boundary:**

> `cbnb` owns plumbing: connections, credentials, caching, progress, dataset loading, metric
> arithmetic. If a reader would want to copy it into their own project, it stays visible in the
> notebook.

**A black-box metric undermines you with exactly this audience.** Whatever lives in `cbnb.eval`
carries the formula in its docstring, and the notebook states it next to the number. Relevance
mapping — how WANDS' Exact / Partial / Irrelevant become gains — is never plumbing.

**Keep *Where to take this* short.** At most five bullets, two or three lines each. The section
exists to leave a reader with somewhere to go, not to prove the author thought of everything, and
every extra suggestion competes with the notebook's one argument for the attention left at the
end. An idea that needs a paragraph is a backlog entry in this file, with a sentence in the
notebook pointing at the idea rather than explaining it. Current lengths, 2026-09-17: three to
six bullets, 154–402 words; `enrich/01` (six) and `data-model/01` (402 words) are the ones to cut
first.

### Proposed, not built

Honest about the difference:

- **`docs/concepts.md`** — one place to explain dot_product vs. cosine, so notebook 07 does not
  re-teach notebook 02. Seven notebooks in, the duplication has not yet hurt.
- **`make retarget REPO=owner/name`** — the repo URL is duplicated per notebook (badge plus
  `REPO_URL`), so a move means editing every one. ~20 lines. Worth building before any move to a
  work org, along with checking team norms about history authored under a personal email.
- **primitive vs. capstone labels** — proposed as a way to separate "teaches one mechanism" from
  "assembles several". Not applied, because seven notebooks in it is still not obvious which are
  which. Revisit if the collection gets hard to navigate.

## Warnings

Things already known to hurt.

**Datasets are the real cost.** Every new corpus is licence review + loader + committed sample +
citation before a single cell of technique gets written. WANDS and CUAD now cover all four
tracks, which makes the current position look easier than it is — the next track-widening idea
(conversations, multilingual) pays that cost again in full.

**Translation and multilingual data: licence risk.** Many obvious corpora are share-alike,
research-only, or of murky provenance. This repo is public and Apache 2.0. Check the actual
licence file, not the README's claim about it — the HuggingFace BEIR mirrors demonstrably
contradict their upstream terms.

**Committed outputs go stale.** Providers deprecate models and change behaviour under a fixed
name. Every stored result is a claim about one run with one model, and `make ship` needs running
more often than feels necessary.

**Notebook run cost compounds.** Caching helps during development and does nothing for a fresh
reader. Keep default sample sizes small, make the full run opt-in.

**Scope creep per notebook.** Every backlog idea wants to be three notebooks. One that
demonstrates two things demonstrates neither.

**Reusing scope names across drafts corrupts runs.** Twice, documents from a deleted draft
survived in a scope a rewrite reused — producing doubled `COUNT(*)` results once and an id-parse
crash the next time, both of which looked like code bugs for a while. Version the scope while
iterating, or drop it between drafts.

**A checker that passes because it checked nothing.** Moving notebooks into track directories
left two globs matching `notebooks/*.ipynb` instead of `notebooks/**/*.ipynb`. They would have
reported success having examined zero notebooks. Structural changes need the tools tested, not
just the tests run.

## Decisions

Settled. Recorded so they do not get re-litigated.

**The indexed text is thin on purpose.** `retrieval/*` indexes `product_name + product_class` and
nothing else, though the committed sample now carries `product_features` too. Short documents are
what make the keyword/vector trade-off *visible*: *nautical platters* returning a nautical
headboard is obvious in a five-word document and invisible in a five-hundred-word one where every
product mentions everything. Richer text would mask the mechanism these notebooks exist to show.
Any notebook relying on that must say so rather than let a reader infer that Couchbase can only
index a title — `retrieval/03` says it in section 2, and uses the full document at rerank time
through a key lookup.

**Corpora: WANDS and CUAD.** The canonical RAG benchmark is the TREC RAG track over MS MARCO,
and **MS MARCO is non-commercial research only**. That blocker spreads: SciFact is CC BY-NC,
NFCorpus and FiQA are non-commercial, and RAGBench's clean CC BY 4.0 tag sits on twelve
components including `msmarco`. HotpotQA (CC BY-SA 4.0) and Natural Questions (CC BY-SA 3.0)
were the usable runners-up; CUAD won because its 41 clause categories are a ready-made extraction
schema, so one corpus serves `flows/`, `data-model/` and eventually `enrich/`.

*Contamination is a footnote, not the reason.* MS MARCO, NQ and HotpotQA are all in GTE's and
BGE's training mixtures, which undercuts BEIR's zero-shot framing — worth one aside in a
notebook. These notebooks teach approaches; they do not claim a recall breakthrough.

*Caveat to clear internally:* CUAD's annotations are CC BY 4.0, but the underlying contracts are
EDGAR filings whose licence status the authors explicitly do not warrant.

**Structured extraction is two notebooks.** `enrich/` is about the model's output — prompt and
schema design, failure modes, confidence gating. `data-model/` is about the document's shape.
They share a corpus, which halves the expensive part.

**Metrics come from `ir-measures`; judgement stays in the notebook.**

**Embedding vs. referencing**, not "decoration" — and a separate document holding attributes
derived from a source is a **derived document** (Data Vault calls the shape a *satellite*).
Borrowing a plausible-sounding word without checking is how a repo teaches the wrong vocabulary.

**Derived documents go in their own collection.** Beside their sources, every query needs a
`type` discriminator — and the first draft of `data-model/01` duly reported `COUNT(*) = 40` for
20 contracts with every tally doubled. Collections are cheap.

**No 5-minute tour.** It solves a navigation problem that does not exist below roughly eight
notebooks. `00_check_setup` was what was actually missing.

## Fixed along the way

**Numeric and datetime index fields.** *2026-09-16.* `vector_index_definition` emitted only text
and keyword fields, so `NumericRangeQuery` and `DateRangeQuery` had nothing to match — and a
range query against a field absent from the mapping matches **nothing and raises nothing**. In
`flows/01` that surfaced as empty retrieval and a model reporting "the excerpts are empty",
which reads as a bad model rather than a bad filter.

`numeric_fields=` and `datetime_fields=` now exist, verified against a live cluster, including
that re-running does *not* force an index rebuild.

The silent half needed its own answer, since the fix does not stop anyone filtering on a field
they forgot to declare. **`indexed_fields(cluster, ...)`** reads back what a live index actually
covers — the first thing to check when a filter returns zero rows. It reports `text (keyword)`
versus `text (en)`, because a keyword field *is* type `text` and hiding the analyzer made the
diagnostic misleading in the exact case it exists for.

## Codespaces friction

Found reviewing the notebooks in a fresh codespace, 2026-09-17. Getting to a running notebook
currently takes knowledge a stranger doesn't have. Causes below are suspected, not confirmed.

- **Slow first start.** Measured from one creation log: **3m26s** before VS Code gets the
  codespace, then extension installs on top.

  | Phase | Time |
  | --- | --- |
  | Pull `devcontainers/python:1-3.11-bookworm` (download ~5s, extracting ~60s) | 67s |
  | `post-create.sh`: venv, CPU PyTorch, `.[all]` | ~130s |
  | Embedding model download, pre-commit hook | ~6s |

  A pre-cached image (GitHub's `universal`) addresses the smaller third at best, and it ships
  several Python runtimes and conda, which makes the kernel problem below worse unless the
  interpreter is pinned. **Prebuilds** remove both phases, at a storage cost billed to the repo
  owner; a published image with the environment baked in does the same without prebuild
  quotas. Cheaper wins to try first: `uv` instead of `pip` for the install, and questioning
  whether a codespace needs `.[all]` up front.
- **The notebook opens as raw JSON.** `openFiles` opens `00_check_setup.ipynb` before the
  Jupyter extension is active, and possibly before the folder is trusted. The creation log ends
  at "Finished configuring" with no extension installs in it, so the extensions go in *after*
  the file is already open — consistent with this, not proof of it. Candidates: set
  `workbench.editorAssociations` for `*.ipynb` in the devcontainer's VS Code settings, and/or
  open the README first and link to the notebook from it.
- **Kernel choice is a guess.** The picker offers `.venv` alongside several system Pythons from
  the base image, and the docs' "choose `.venv`" is easy to miss. Candidate: set
  `python.defaultInterpreterPath` to `${containerWorkspaceFolder}/.venv/bin/python` so it is
  preselected.
- **NanoGPT flags the key from codespace IPs.** `00_check_setup` reported the key rejected in a
  codespace while the same key works locally. Datacenter addresses are a common trigger for
  provider abuse checks. Nothing in the repo can fix that, but the readiness failure could say
  it, and `docs/codespaces.md` could suggest another provider if calls are rejected there but
  work locally.
- **`00_check_setup` took a patient technical reader.** Fixed: both results are now coloured
  panels (`cbnb/readout.py`, no dependencies, plain-text fallback), headed by the verdict —
  "You can run 3 of 7 notebooks" — and the one fix that unlocks the most.

### Found by the new readout

- **It calls `data-model/02` ready when `01` can't run.** `02` reads what `01` wrote, and
  nothing declares that, so with `llm` blocked the panel offers a notebook that will fail.
  Needs a way to declare notebook-to-notebook order, which `inventory` doesn't have.
- **Every notebook was publishing its runner's setup.** The bootstrap cell's stored output
  named the environment, the masked cluster, and the provider and model of whoever shipped last
  — the exact category `00_check_setup` clears, one cell at a time. Found when the panel change
  made those outputs look stale. Fixed: setup cells are tagged `cbnb-ephemeral`, and the checker
  requires it. No re-ship needed, since the stamp hashes code, not tags.
- **Whether GitHub keeps a panel's inline styles is untested.** No committed output contains a
  panel yet; check when one first does.
- **Titles disagree.** `retrieval/02` is "Recall, precision, and the price of a filter" in the
  notebook and "Which parts of that were worth it?" in the README.

## Still open

- **`enrich/01` classifies from a bare product name, and that flatters it.** Measured
  2026-09-17 on its own 150-product sample, outside the notebook: adding `product_features` to
  the prompt moves exact-path accuracy 24.0% → 28.0% and department 71.3% → 72.7%. The larger
  effect is on the *baseline* it is compared against — embedding title plus specs, no LLM at
  all, lifts department accuracy 48.7% → 61.3% while *dropping* exact path 18.0% → 14.7%. So
  part of the headline gap is the title being thin rather than the hallucination step working.
  Left as a suggestion in the notebook's *Where to take this* rather than re-shipped, because
  the fair comparison is a 2×2 and a rewrite of the argument.
- **`enrich/01`'s stored numbers predate the current model.** The same title-only pipeline
  scored 24.0% exact in that side experiment against 28.7% stored, with nothing changed but the
  model `.env` points at. Any re-ship moves the headline whether or not features are added.
- **Description, ratings and reviews are still dropped.** `product_description` (86% present),
  `rating_count`, `average_rating` and `review_count` are in WANDS upstream and not in `data/`.
  Features beat description when measured together, so this is not obviously worth the size; the
  ratings fields are untested as ranking signals.
- **Vector scores drift between runs.** Three runs of `retrieval/02` against one index gave
  vector nDCG@10 of 0.776, 0.779 and 0.781, and flipped which strategy led that column. BM25 is
  identical every time, so it is the approximate nearest-neighbour search. The notebook's prose
  now states what holds across runs rather than one run's decimals, but nothing *reports* the
  spread: `cbnb.eval` could score repeated runs and show a range, which is Evaluation layer 5
  (stability) arriving early. Until then, any claim resting on a gap of about 0.01 is suspect.
  Not quantisation — the Search index scores in full precision (see
  [Reranking means a second model](#reranking-means-a-second-model-nothing-else-gets-the-word));
  approximate candidate selection is the open suspect, and nobody has confirmed it.
- **A recall figure is meaningless without its ceiling.** WANDS judges a median of 125 relevant
  products per query, so the best possible R@50 is 0.462 and the strategies reach 87% of it. Any
  notebook reporting recall must report what was achievable.
- **Does `agentc` merit a notebook**, or a section inside chat-with-memory? Unanswerable until
  its current API is read.
- **A second model as a quality signal.** `enrich/02` shows two prompts to *one* model mostly
  agree, because they share its blind spots — the flag fires on 18 of 241 extractions and catches
  5 of 21 errors. Two different models disagreeing should be a stronger signal, and `cbnb.llm`
  already points at either. Worth measuring before believing.
- **`parties` is the weakest extracted field at 80%**, which nobody would have guessed. Whatever
  makes multi-value extraction harder than single-value extraction is unexamined.
