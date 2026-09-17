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
`local-embeddings`, `api-embeddings`, `dataset-download`, `ram-8gb`. Adding a *new*
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
which claims the new outputs no longer support. Advisory only; verify before editing.

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

## Before committing

```bash
make check
```

Never commit a notebook whose outputs came from a failed run — `scripts/run_notebook.py`
writes those to `build/` for exactly this reason.
