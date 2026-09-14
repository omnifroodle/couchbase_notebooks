# Local development

Write and revise notebooks on your own machine against your real Capella cluster. Colab is
only for the final check that a stranger's runtime can run it.

## One-time setup

```bash
make setup     # .venv on Python 3.11, installs cbnb in editable mode, creates .env
```

Fill in `.env`: the `CB_*` values ([`capella-setup.md`](capella-setup.md)) and one model
provider key. Add your current IP to the Capella allow list.

## The editing loop

Open the notebook in **VS Code** (the repo's `.vscode/settings.json` already points at
`.venv`) or run `make lab` for Jupyter Lab.

Run cells as normal. Three things make this quicker than it sounds:

- **Helpers reload themselves.** `cbnb.bootstrap()` turns on autoreload in a local checkout,
  so an edit to `cbnb/*.py` applies to the next cell you run — no kernel restart.
  (`CBNB_AUTORELOAD=0` turns it off.)
- **LLM calls are cached on disk.** Re-running a cell with the same prompt costs nothing and
  returns instantly. Change the prompt and only the changed calls hit the API. Use
  `CBNB_LLM_CACHE=0` or `LLM(cache=False)` to measure real cost and latency.
- **Couchbase setup is idempotent.** Re-running the load and index cells updates in place.

## Top-to-bottom runs

Interactive sessions hide ordering bugs: a variable defined in a cell you later deleted, a
cell that only works the second time. Before shipping, run it the way a reader will:

```bash
make run NB=01
```

Executes every cell in a fresh kernel, headless, and writes the result to `build/`
(gitignored) — the committed notebook is not touched. It reads only `.env`, never prompts,
checks for missing settings before starting, and stops at the first failing cell with its
traceback.

Run just the first part, e.g. everything before the first LLM call:

```bash
make run-to NB=01 UNTIL='from cbnb.llm import'
```

## Shipping

```bash
make ship NB=01
```

Runs fresh with the LLM cache off, writes the outputs **into** the notebook so GitHub
renders them, then runs the notebook checks (bootstrap cell present, nothing that looks
like a credential in any output). Review the diff, commit.

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
