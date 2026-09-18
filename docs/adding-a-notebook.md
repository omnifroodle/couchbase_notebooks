# Adding a notebook

The rules below are the enforced ones. For what to build next, how notebooks are grouped,
and conventions still being settled, see [`roadmap.md`](roadmap.md).

## Layout

```
notebooks/<track>/NN_name.ipynb the notebook — track is retrieval, flows,
                                enrich or data-model; see docs/roadmap.md
cbnb/                           shared helpers — connection, indexes, LLM, embeddings
data/                           small, openly-licensed data committed to the repo
docs/                           setup and reference
```

Number notebooks so they sort. Keep each one self-contained: a reader should be
able to open exactly one file and get a result.

## The rules that keep these runnable

**Cell 1 is always the same bootstrap.** Copy it verbatim from an existing
notebook. It finds `cbnb` in a local checkout, `pip install`s from GitHub on
Colab, then installs missing dependencies and loads credentials. Tag it
**`cbnb-ephemeral`**: what it prints describes the machine that ran it, so
`make ship` empties it and the checker fails without the tag.

**Declare what the notebook needs, in both places.** The setup call is what
runs; the header line is what a reader sees on GitHub. `00_check_setup` reads
these to tell people which notebooks they can run, so a notebook that declares
nothing gets reported as runnable when it is not.

```python
settings = cbnb.bootstrap(requires=["couchbase", "llm", "local-embeddings"])
```

```markdown
**Requires.** couchbase · llm · local-embeddings
```

Names come from `cbnb.readiness.CAPABILITIES`. `check_notebooks.py` fails if the
two disagree. `extras=` is separate, and still means "just install this".

**Never hardcode credentials, and never leave them in an output.** Read
everything through `cbnb.config`. It resolves env → `.env` → Colab secrets →
`getpass` prompt.

**Commit outputs.** GitHub renders stored outputs, and that rendering is how
most people will read the notebook — treat it as the primary artifact. It also
means a stray `print(api_key)` gets committed, so check the diff.

**Unless the output describes the runner, not the technique.** A setup check
prints a cluster address, a provider and an amount of RAM: useless to a reader
and someone else's configuration in a public repo. Those notebooks set
`"cbnb": {"outputs": "cleared"}` in their notebook metadata; `make ship` runs
them to prove they work and then clears what they printed, and the checker fails
if outputs ever reappear. Tell the reader in the notebook that it is empty by
design.

**Verdicts go in a `cbnb.readout.Panel`.** Anything that reports ready/blocked or
pass/fail — a checklist, a gate, a readiness result — renders as a coloured panel with the
conclusion as its headline, rather than lines of `print`. `cbnb.bootstrap` and
`00_check_setup` both do. Measurements and model output are not verdicts; leave them as
tables and text.

**Every code cell opens with a one-line comment saying what it does.** Plain English,
short, about *this* cell: `# Build the Search index and wait until it's ready.` The
markdown above a cell is often about the problem, not the code, and a setup cell's
purpose is rarely obvious from its first import. The comment is for the reader about to
press Run. `check_notebooks.py` fails a cell without one. The ship stamp ignores a
cell's leading comment lines, so rewording one does not need a re-ship. Comments further
down the cell are still hashed.

**Don't show the reader how the notebook was made.** The reader is learning the technique,
not reviewing our work. The prose covers two things: the technique, and what the reader sees
when they run the cells. It never covers how the notebook came to be.

- **Hard violations: always cut.** Anything about how the notebook was written: drafts or earlier
  versions, runs the reader never saw, what we did or worried about while building it, and our
  tooling (ship, review, stamps). *"While writing this we ran it three times"*, *"this notebook
  was written twice"*, *"the first version of this notebook got that wrong"*.
- **Soft violations: a judgement call.** A section or aside that exists because *we* hit a
  problem, not because the reader needs it for this notebook's lesson. Would it be here if we
  hadn't run into that while building? Does it serve the core lesson? If the reader does need
  it, keep the smallest version, at the point where it matters. If it is a lesson in its own
  right, move it to the notebook that teaches that lesson, or to the roadmap if that notebook
  does not exist yet.
- **Not violations.** A failure the reader watches happen in the cells: that is the argument,
  not a confession. What the reader's *own* run will show (*"your scores will differ by a few
  thousandths"*). Something we learned while building, restated as a fact about the technique
  with the history removed. Being open about a choice that shapes what the reader sees, such as
  a deliberately thin corpus, so long as it says what the choice is and why it helps the lesson.

`make review` asks a model to flag these (the "audience review"). Like the claim review it is
advisory. It is reliable on the hard cases; the soft ones are yours to judge.

**Keep the technique in the notebook and the plumbing in `cbnb`.** If a cell is
twenty lines of index configuration, move it into `cbnb/couchbase_io.py` and
call it. The notebook should read as an argument, not a script.

**A tutor for live readers, if you want one.** `cbnb.review.commentary` asks a
model to interpret a fresh result for whoever is running the notebook — useful
where the result rewards interpretation and the reader may not know what to look
for. Tell it what you expected, honestly, including the uncertain parts: that is
what lets it tell the reader when the run disagreed with you.

```python
commentary(results, expectation="We expected the department gap to be large and "
                                "exact-path accuracy to be noisy at n=150.")
```

Tag that cell **`cbnb-ephemeral`** (JupyterLab: the property inspector's Cell
Tags box). `make ship` runs it and then empties it, and the checker fails if the
output ever survives. That is not optional politeness — in testing, the model
read a results table correctly and then invented a count to support its
strongest claim. It is a tutor for someone who can see the real output next to
it, never a claim this repo publishes.

**Make it idempotent.** Every `ensure_*` helper is safe to re-run. A reader who
runs cell 8 twice should not get an error.

**Clean up at the end.** Close with a cell that calls `drop_demo_data(...)`,
commented out, so it is obvious how to reset.

## Data

Prefer datasets with a clear open licence, and commit a small sample so the
notebook runs before anything is downloaded. `cbnb/datasets.py` shows the
pattern: committed sample by default, full download behind `full=True`, and the
citation in the module docstring.

Cite the source in the notebook itself as well as in code.

## Before committing

```bash
make ship NB=NN
```

Executes the notebook top to bottom in a fresh kernel, stores the outputs, and runs
`scripts/check_notebooks.py`. See [`local-development.md`](local-development.md).

It checks that cell 1 is the bootstrap cell, that no output contains something
that looks like a credential, and that the notebook is valid JSON.
