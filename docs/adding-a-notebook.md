# Adding a notebook

The rules below are the enforced ones. For what to build next, how notebooks are grouped,
and conventions still being settled, see [`roadmap.md`](roadmap.md).

## Layout

```
notebooks/NN_short_name.ipynb   the notebook
cbnb/                           shared helpers — connection, indexes, LLM, embeddings
data/                           small, openly-licensed data committed to the repo
docs/                           setup and reference
```

Number notebooks so they sort. Keep each one self-contained: a reader should be
able to open exactly one file and get a result.

## The rules that keep these runnable

**Cell 1 is always the same bootstrap.** Copy it verbatim from an existing
notebook. It finds `cbnb` in a local checkout, `pip install`s from GitHub on
Colab, then installs missing dependencies and loads credentials.

**Never hardcode credentials, and never leave them in an output.** Read
everything through `cbnb.config`. It resolves env → `.env` → Colab secrets →
`getpass` prompt.

**Commit outputs.** GitHub renders stored outputs, and that rendering is how
most people will read the notebook — treat it as the primary artifact. It also
means a stray `print(api_key)` gets committed, so check the diff.

**Keep the technique in the notebook and the plumbing in `cbnb`.** If a cell is
twenty lines of index configuration, move it into `cbnb/couchbase_io.py` and
call it. The notebook should read as an argument, not a script.

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
