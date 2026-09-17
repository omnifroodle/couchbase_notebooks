# Running on GitHub Codespaces

A codespace is this repository checked out in a cloud container, with VS Code in the
browser. Everything works as it does locally — the helpers, `make run`, `make ship`, the
notebook checks — with nothing to install on your machine.

[![Open in GitHub Codespaces](https://img.shields.io/badge/Open%20in%20Codespaces-2f363d?logo=github&logoColor=white)](https://codespaces.new/omnifroodle/couchbase_notebooks?quickstart=1)

## Before you start

- **A GitHub account.** Codespaces usage is billed to whoever creates the codespace. Personal
  accounts get 120 core-hours a month free — about 60 hours on the default 2-core machine.
- **A Capella cluster** that accepts connections from the codespace. Codespaces don't have a
  fixed IP, so this means `0.0.0.0/0` on the allowed-IP list, as with Colab. See
  [`capella-setup.md`](capella-setup.md), step 4.

## Secrets

The first time you create a codespace, GitHub lists this repository's recommended secrets:
the `CB_*` Couchbase settings, `CBNB_LLM_PROVIDER`, `CBNB_LLM_MODEL`, and an API key for each
supported provider. Fill in what you use and leave the rest blank. They are saved as *your*
Codespaces secrets, scoped to this repository, and reach the notebooks as ordinary
environment variables.

To change them later: **GitHub → Settings → Codespaces → Secrets**. A running codespace only
sees the change after it is stopped and started again.

Skipped them entirely? The notebooks prompt for anything missing, with passwords through a
masked input.

## First start

Creating a codespace takes a few minutes the first time. `.devcontainer/post-create.sh`:

1. creates `.venv` and installs the helpers, with the CPU build of PyTorch (a codespace has no
   GPU, and the default build brings several GB of CUDA libraries);
2. downloads the embedding model the notebooks use;
3. installs the notebook checks as a git pre-commit hook.

When that finishes, [`notebooks/00_check_setup.ipynb`](../notebooks/00_check_setup.ipynb)
opens. Run it first: it checks your credentials against the real services and tells you which
notebooks you can run, which is a much better first minute than discovering a rejected key
halfway through a demo. If VS Code asks for a kernel, choose `.venv`.

Reopening the same codespace later (the badge's *Resume* option) skips all of this.

## Prefer JupyterLab?

A codespace can open in JupyterLab instead of VS Code: at
[github.com/codespaces](https://github.com/codespaces), open the **⋯** menu next to the
codespace and choose the JupyterLab / Jupyter option (or make it your default editor in
GitHub → Settings → Codespaces). It's the same codespace — files, secrets and `.venv` — and
the notebooks' `python3` kernel is the same `.venv` Python VS Code uses.

Codespaces created before this was set up report that the Jupyter server can't be found.
Either rebuild the container (VS Code command palette → *Codespaces: Rebuild Container*), or
run this once in the codespace's terminal, from the repository root:

```bash
sudo ln -sfn "$PWD/.venv/bin" /usr/local/jupyter
```

## Keeping costs down

- **Stop it when you're done** — *Codespaces* menu (bottom-left) → *Stop Current Codespace*.
  Idle codespaces stop on their own after 30 minutes by default.
- **Resume rather than recreate.** Each new codespace repeats the setup and uses its own
  storage. Delete old ones at [github.com/codespaces](https://github.com/codespaces).
- The notebooks call your model provider, which bills separately. The LLM response cache
  lives inside the codespace, so re-running cells there is free.

## How it differs from local and Colab

| | Local | Codespaces | Colab |
| --- | --- | --- | --- |
| Settings from | `.env` | Codespaces secrets | Colab secrets |
| Repo available as | your checkout | a full checkout | cloned by the setup cell |
| `make run` / `make ship` | yes | yes | no |
| Cost | your machine | your GitHub quota | Google's free tier |

## A key or password was rejected

It happens: a value in the wrong box on the create page, a typo, a key you've since
regenerated. The error names the setting, where its value came from, and whether it looks
like it belongs to a different provider. Two ways out:

- **Keep going right now.** In a notebook cell, run
  `cbnb.update_setting("NANOGPT_API_KEY")` (or whichever name the error gave). It asks for
  the value with a masked prompt, so the key never lands in the notebook. Then re-run the
  cell that uses it — for an API key, the cell that creates `LLM()`.
- **Fix it for good.** Edit the secret at
  [github.com/settings/codespaces](https://github.com/settings/codespaces), then stop and
  restart the codespace. Running codespaces don't see secret changes.
