# Local development

Write and revise notebooks on your own machine against your real Capella cluster. Colab is
only for the final check that a stranger's runtime can run it.

## One-time setup

```bash
make setup     # .venv on Python 3.11, installs cbnb in editable mode, creates .env
```

Fill in `.env`: the `CB_*` values ([`capella-setup.md`](capella-setup.md)) and one model
provider key. Add your current IP to the Capella allow list.

Notebooks live under a track directory, so `NB=` takes a path like `retrieval/01`. A bare
`NB=01` now matches two notebooks and every target refuses it rather than guessing.

## Three modes, kept apart

Most accidental notebook edits happen while *testing*: a debug `print` that gets
saved, outputs from a half-finished session, editor metadata. So testing never opens
the real file.

| I want to… | Do | Touches `notebooks/`? |
| --- | --- | --- |
| Check it runs top to bottom | `make run NB=retrieval/01` | No — writes `build/` |
| Poke at it interactively | `make scratch NB=retrieval/01` | No — a copy in `build/scratch/` |
| Change the notebook | open `notebooks/<track>/NN_….ipynb` on purpose | Yes |
| Publish outputs for GitHub | `make ship NB=retrieval/01` | Yes — outputs + stamp |
| Present it | `make slides NB=retrieval/03` | No — a Marp deck in `build/slides/` |

### Test: `make run`

Executes every cell in a fresh kernel, headless, and writes the result to `build/`. It reads
only `.env`, never prompts, checks for missing settings before starting, and stops at the
first failing cell with its traceback. Interactive sessions hide ordering bugs — a variable
from a cell you deleted, a cell that only works the second time — and this doesn't.

Run just the first part, e.g. everything before the first LLM call:

```bash
make run-to NB=enrich/01 UNTIL='from cbnb.llm import'
```

### Explore: `make scratch`

Copies the notebook to `build/scratch/` and opens the copy in VS Code. Break it freely.
A second `make scratch` reopens the same copy so you don't lose work; `FRESH=1` recopies.
If you find a fix worth keeping, make it in the real notebook deliberately.

### Edit

Open the real notebook in VS Code or `make lab`. Two things make iterating quick:

- **Helpers reload themselves.** In a local checkout, `cbnb.bootstrap()` turns on
  autoreload, so an edit to `cbnb/*.py` applies to the next cell you run — no kernel
  restart. (`CBNB_AUTORELOAD=0` turns it off.) Kernels started before a helper was
  *added* still need one restart.
- **LLM calls are cached on disk.** Re-running a cell with the same prompt costs nothing.
  `CBNB_LLM_CACHE=0` or `LLM(cache=False)` to measure real cost and latency.

The Couchbase cells are idempotent, so re-running them is safe.

### Ship: `make ship`

Runs the notebook fresh with the LLM cache off, writes the outputs **into** the notebook so
GitHub renders them, strips editor metadata, and **stamps** the notebook with a hash of its
cell sources. Then it runs the checks. If any cell fails, the notebook is not modified — the
partial run goes to `build/`.

### Present it: `make slides NB=retrieval/03`

Writes a [Marp](https://marp.app) deck to `build/slides/<track>/<name>.md`, built from the
notebook's own prose and its stored outputs. Nothing runs, no credential is needed, and **no
model writes a word of it**. Open a deck with the Marp extension for VS Code, or
`npx @marp-team/marp-cli@4.5.1 <deck> --html` to export HTML or PDF yourself.
`make slides NB=all` builds every deck plus the `index.html` that fronts the published site.

### What goes on a slide: `slides/<track>/<name>.yml`

A notebook is far too long to project. The plan says what survives, one entry per `##`
section:

```yaml
- heading: 3. One query, before and after
  setup: false            # true drops the section: it only makes the notebook run
  idea: On one query, reranking pulls six of the new top ten from deep in the list.
  paragraphs: [0, 1]      # which of the section's paragraphs reach the slide
  code:
    - {cell: 8, mode: summarize}   # show | summarize (to its comment) | hide
  evidence: {cell: 8, explain: true}   # whose output is the result; false for none
  hash: 74f52ff4de1f      # the section this entry was written against
```

`idea` and the deck's `summary` are the only text on a slide that is not the notebook's own
prose, and both are committed by a person before they can be published.

Without a plan the deck falls back to rules — first paragraph, a line per code cell, the last
table in the section — and says so. That keeps a new notebook presentable the day it lands.

### Drafting a plan: `make review-slides NB=retrieval/03`

Asks a model to work through the notebook section by section: is this only setup, what is the
section's main idea, which paragraphs carry it, which code is worth reading on a slide and
which is just its comment, which output is the evidence, and does that evidence need
explaining. It writes the plan to `slides/` for you to read, edit and commit.

**Run it again after editing a notebook and it updates rather than overwrites.** Each entry
carries a hash of the section it was planned against: unchanged sections keep your edits
untouched, and only changed or new sections are replanned. The run prints which were which.

Advisory in the same sense as `make review` — a model proposes, committing is how you approve.

### After a re-ship: `make review NB=enrich/01`

The thing a re-ship breaks that nothing else catches. Prose naming specifics from the run —
the lowest-scoring row, a product that resolved wrongly, the shape of the failures — quietly
stops being true when those move. The notebook still executes; the checks still pass.

`make review` hands a model the committed prose and the committed outputs and asks which
statements the outputs no longer support:

```
cell 17 [contradicted] an over-the-door towel *rack* resolves to *Bath Towels*, and it has
                       the lowest score in the table
    In the cell 16 table the towel rack resolves to 'Countertop Bath Accessories', and its
    score (0.762705) is not the lowest — the fire pit table's 0.759138 is.
```

**Advisory, and deliberately toothless.** It never edits a notebook, never appears to a
reader, is not part of `make check`, and cannot fail a commit or CI. It skips cleanly when
no model is configured. A model's opinion is worth a minute of your attention and nothing
more — verify each finding against the outputs before editing.

Set `CBNB_REVIEW_MODEL` to judge with something better than the model a notebook is
demonstrating.

## Guard rails

`scripts/check_notebooks.py` (run by `make check`, CI, and the git hook) fails a notebook
when:

- **its sources changed since the last ship** — the stored outputs no longer describe the
  code, or something was edited by accident; or
- **it has outputs that didn't come from a ship** — an interactive session got saved.

Both come with the fix: `make ship`, or `git restore notebooks/<file>` to throw the change
away. A notebook with no outputs and no stamp is fine — that's a notebook in progress.

It also fails when a notebook contains anything that would identify or unlock your
setup: credential-shaped strings, a Capella cluster hostname, or — when run locally — any
password, API key or cluster host from your `.env`. The setup cell's status line masks the
hostname (`cb.***.cloud.couchbase.com`) for this reason. It warns about the `OWNER/REPO`
placeholder.

Install the check as a pre-commit hook once per clone:

```bash
make hooks
```

Delete `.git/hooks/pre-commit` to remove it, or `git commit --no-verify` to skip it once.

### Getting back to a good state

```bash
git restore notebooks/enrich/01_hypothetical_classification.ipynb   # discard all uncommitted changes
git diff --stat                                                # see what else moved
```

## What local runs don't cover

Local and Colab share every line of code except two paths in the setup cell:

| Colab-only path | Tested locally? |
| --- | --- |
| `git clone` of the repo when `cbnb` isn't importable | No — needs the real repo URL, and it clones what's *pushed* |
| Reading Colab secrets (`google.colab.userdata`) | No — locally the same names come from `.env` |

So once the repo exists, one run on Colab from the badge is worth doing. It should be the
only one.

## Reset

The last cell of each notebook drops what it created. Or from a shell:

```bash
.venv/bin/python -c "import cbnb; s=cbnb.bootstrap(quiet=True); from cbnb.couchbase_io import connect, drop_demo_data; drop_demo_data(connect(s), s.cb_bucket, 'hypothetical_classification')"
```
