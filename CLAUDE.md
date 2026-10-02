# Working in this repo

Runnable Couchbase demo notebooks. They must work for a stranger on Colab with no local
setup, and read well on GitHub without being run at all.

Plan and conventions: [`docs/roadmap.md`](docs/roadmap.md).
Enforced rules: [`docs/adding-a-notebook.md`](docs/adding-a-notebook.md).

## Every notebook declares what it needs

This is the rule most easily forgotten, because nothing breaks immediately when it is.
`00_check_setup` tells a reader which notebooks they can run by reading these declarations
out of the notebook files. **A notebook that declares nothing is invisible to that report**,
so a reader is told they are ready for it when they are not.

Declare in both places. They are for different audiences and
`scripts/check_notebooks.py` holds them to agreeing:

```python
settings = cbnb.bootstrap(requires=["couchbase", "llm", "local-embeddings"])
```

```markdown
**Requires.** couchbase · llm · local-embeddings
```

Capability names come from `cbnb.readiness.CAPABILITIES` — currently `couchbase`, `llm`,
`local-embeddings`, `api-embeddings`, `dataset-download`, `decision-model`, `ram-8gb`. Adding a *new*
capability means adding a probe there; keep them coarse and few. They exist to give a
reader a legible verdict, not to resolve dependencies.

`extras=` is separate and still means "just install this" (e.g. `plots`).

## Don't let the two readiness modules learn about each other

- `cbnb/readiness.py` — what the *environment* can do. Knows nothing about notebooks.
- `cbnb/inventory.py` — what each *notebook* asks for. Reads notebooks as files; never
  imports or executes them. Knows nothing about what a capability means.

They meet in `00_check_setup` and nowhere else. If one starts importing the other, the
coupling has moved somewhere it cannot be seen.

## Notebook outputs are committed

GitHub's rendering of stored outputs is the primary artifact — most people will read these
without running them. Consequences:

- A stray `print(api_key)` gets committed. `make ship` runs the leak checks; read the diff.
- Cluster hostnames get masked (`cbnb.config.mask_host`). Capella hostnames identify a
  specific cluster.
- `make ship NB=NN` is what produces outputs: fresh kernel, top to bottom, then checks.
  Editing outputs by hand desynchronises the ship stamp.

The ship stamp hashes **code cells only**, so prose can be fixed without a re-run. Editing a
code cell means re-shipping, which means a working cluster and a working API key.

**A re-ship invalidates prose, and nothing enforces that.** Statements naming specifics from
the run — the lowest-scoring row, a particular product, the shape of the failures — go stale
while every check still passes. After re-shipping, run `make review NB=NN`: it asks a model
which claims the new outputs no longer support, and which passages are about how the
notebook was made. Advisory only; verify before editing.

### Unless the output isn't about the technique

Commit outputs when **the output is the argument** — a measurement, a ranking, a model's
answer. Clear them when the output only describes *whoever ran it last*: a cluster address, a
provider name, an amount of RAM. That is noise to a reader and someone else's configuration
leaking into a public repo.

Declare it in the notebook's own metadata and `make ship` does the rest — it runs the
notebook to prove it works, then clears what it printed:

```json
"metadata": { "cbnb": { "outputs": "cleared" } }
```

`check_notebooks.py` then *fails* if that notebook ever has stored outputs. Say so in the
notebook too, so a reader on GitHub knows it is empty on purpose rather than broken.
`00_check_setup` is the only one of these so far.

**Every setup cell** is one of these. `cbnb.bootstrap` reports where it ran, the masked
cluster, the provider and model — true of the last person to ship, and nothing to do with
the lesson. Tag cell 1 `cbnb-ephemeral`; `check_notebooks.py` fails if it isn't.

**Per cell**, tag a cell `cbnb-ephemeral` and `make ship` runs it and empties just that one,
in a notebook that otherwise commits everything. For output worth seeing live and wrong to
publish — `cbnb.review.commentary`, which is unreviewed, differs every run, and is not one
of the notebook's claims.

## Every code cell says what it does

The first line of every code cell is a short plain-English comment describing that cell,
setup and clean-up included. The markdown above it is often about the problem, not the
code. `check_notebooks.py` enforces it. The ship stamp skips a cell's leading comment
lines, so fixing the wording needs no re-ship.

## Show the problem running, then solve it

Not a paragraph describing what goes wrong — the reader's own kernel producing the bad
output. Then the fix. A reader who never felt the problem cannot judge whether the solution
was worth its cost, and the solutions here are rarely free. This costs every notebook some
code it then abandons; pay it. Full rule and why:
[`docs/roadmap.md`](docs/roadmap.md#conventions).

## Don't show the reader how the notebook was made

The audience is someone learning the technique, not the author. Prose covers the technique
and what the reader's run will show. Never cover drafts, earlier versions, runs the reader
never saw, or our tooling ("ship", "review"). Cut an aside that only exists because we hit a
problem while building. If the concern is real, move it to the notebook whose lesson it is,
or to the roadmap. Full rule and the not-violations:
[`docs/adding-a-notebook.md`](docs/adding-a-notebook.md). `make review` flags candidates;
the soft cases need your judgement.

## A deck is built from a committed plan

`make slides NB=…` turns a notebook into a Marp deck, published to GitHub Pages from
`main`. What survives onto a slide is decided by `slides/<track>/<name>.yml`: which sections
are only setup, each section's idea, which paragraphs and which code appear, which output is
the evidence. `make review-slides NB=…` drafts that plan with a model and **writes it to a
file** — committing it is how a person approves it. Re-running it replans only the sections
whose source hash changed, so hand edits survive.

A slide's prose is the notebook's prose. The plan's `idea` and `summary` lines are the one
exception, and they reach a reader only after someone has read and committed them.

## Verdicts go in a panel, not a print

Output whose job is a verdict — ready or blocked, pass or fail, a checklist of what is
missing — uses `cbnb.readout.Panel`, not `print`. A reader should get the answer from the
colour and the headline, without reading every line. Put the conclusion in the headline
("You can run 3 of 7 notebooks"), and the fix under the row it fixes.

```python
from cbnb.readout import Item, Panel

Panel("2 of 3 checks passed",
      [("Checks", [Item("ok", "index built"), Item("blocked", "llm", detail, fix)])],
      status="blocked")        # last expression in a cell; call .show() anywhere else
```

Only verdicts. Measurements stay DataFrames, model answers stay text — a coloured pill on a
number implies a threshold nobody chose. `readout` knows nothing about what its rows mean, so
it can be used from either side of the readiness/inventory boundary without joining them.

## Every notebook names the models behind its numbers

A stored result is only as meaningful as the model that produced it, and a provider can
serve the same model name differently from one day to the next. So a notebook that declares
`llm`, `local-embeddings`, `api-embeddings` or `decision-model` ends — before the optional
clean-up cell — with a short "What produced these results" heading and:

```python
# Name the models that produced the results above.
cbnb.run_card()
```

The card lists what was actually called, recorded by `LLM`, `Embedder`, `Reranker` and
`decide()` as they run, so nothing has to be declared twice. It names the provider, and says
when the provider routes requests to another host (NanoGPT, OpenRouter: what answered may be a
modified build). It is Markdown, not a `Panel` — a model name is not a verdict, and GitHub keeps
Markdown outputs but strips inline styles.

`check_notebooks.py` fails a shipped notebook that uses a model and stores no card. `make ship`
copies the card's models into the stamp and **warns** when they differ from the last ship:
re-shipping on a new model is legitimate, but it is exactly when `make review` matters most.

## Before committing

```bash
make check
```

Never commit a notebook whose outputs came from a failed run — `scripts/run_notebook.py`
writes those to `build/` for exactly this reason.
