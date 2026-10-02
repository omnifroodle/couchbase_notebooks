# Running on Google Colab

Colab runs one notebook at a time in a Google-hosted runtime, in the browser, for free.
Nothing to install, nothing to clone: every notebook carries an **Open in Colab** badge, and
its first cell fetches everything else.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/omnifroodle/couchbase_notebooks/blob/main/notebooks/00_check_setup.ipynb)
— start with [`00_check_setup`](../notebooks/00_check_setup.ipynb).

It is the quickest way to run a notebook, and the least suited to changing one: there is no
`make`, no `.env`, and the runtime forgets everything when it shuts down. To write or edit
notebooks, use a [local checkout](local-development.md) or [Codespaces](codespaces.md).

## Before you start

- **A Google account.** The free runtime is enough for every notebook here; none needs a GPU.
- **A Capella cluster** that accepts connections from Colab. Colab runtimes don't have a
  fixed IP, so this means `0.0.0.0/0` on the allowed-IP list. See
  [`capella-setup.md`](capella-setup.md), step 4.
- **A model API key**, unless you are only running the notebooks that need no model — all
  three `retrieval/` ones and `data-model/02`.

## Settings

Every notebook reads the same names as [`.env.example`](../.env.example). On Colab there are
two ways to supply them, and you can mix them.

### Answer the prompts

Run the setup cell (the first code cell). If the notebook needs a setting nothing has
supplied, it lists them — the same list, with the same descriptions, that GitHub shows when
you create a codespace — and then asks for each one in turn, under the cell:

1. the Couchbase settings the notebook needs;
2. which model provider to use, if you haven't said — `openai` unless you type another;
3. that provider's API key;
4. which model to use — Enter accepts the provider's default.

The model is asked for whenever `CBNB_LLM_MODEL` is unset, even when everything else is
already there. It is optional, but it decides every answer the notebook prints, and the
results stored in a notebook came from one particular model; a default you never chose is easy
to miss.

Passwords and keys are typed into a masked box, so they never appear in the notebook.
Leave an answer blank to skip it; the setup cell then says which capability that costs you.

Answers last until the runtime shuts down. Fine for one notebook; tedious for a second.

### Colab secrets

To be asked nothing, store the settings once as **Colab secrets**: the **key icon** in the
left sidebar → **Add new secret**. Use exactly these names:

| Name | Value |
| --- | --- |
| `CB_CONNECTION_STRING` | Capella public connection string, e.g. `couchbases://cb.xxxxxxxx.cloud.couchbase.com` |
| `CB_USERNAME` | Capella database access username — *not* your Capella login |
| `CB_PASSWORD` | Capella database access password |
| `CB_BUCKET` | Optional. The bucket the notebooks write to; default `demos` |
| `CBNB_LLM_PROVIDER` | `openai`, `nanogpt`, `openrouter`, `groq`, `anthropic` or `custom`; default `openai` |
| `CBNB_LLM_MODEL` | Optional, but asked for on every run until set. Enter at the prompt accepts the provider's default |
| `OPENAI_API_KEY`, `NANOGPT_API_KEY`, … | The key for the provider you chose. Only that one |

Anything else in [`.env.example`](../.env.example) works the same way — `CBNB_LLM_BASE_URL`
and `CBNB_LLM_API_KEY` for a `custom` endpoint, `OPENROUTER_API_KEY` for the decision-model
experiment, `CBNB_EMBEDDING_BACKEND` to embed through your provider instead of locally.

Secrets belong to your Google account, not to a notebook, so you add them once and every
notebook here can use them. Each notebook still needs **notebook access** switched on for
each secret: either the toggle next to it in the panel, or the *Grant access* dialog Colab
shows the first time a notebook reads one. The setup cell lists the names it loaded.

## First run

Opening a notebook from GitHub, Colab warns that it was not authored by Google. Choose
**Run anyway**: the code is this repository's, and the first cell is the same in every
notebook.

That first cell, the first time on a fresh runtime:

1. clones this repository into `cbnb-repo/`, which brings the helpers and the committed
   datasets with it;
2. installs what Colab lacks — the Couchbase SDK, sentence-transformers, and so on. About a
   minute;
3. copies your Colab secrets into the environment, and asks for anything still missing;
4. checks that what the notebook needs is there, and stops with a fix if it isn't.

Then **Runtime → Run all**, or run cell by cell. A notebook that needs an embedding model
downloads it the first time it is used, about 90 MB.

## What Colab forgets

A Colab runtime is disposable. When it disconnects — idle for a while, or after a few
hours — it takes with it:

- the clone and the installed packages, so the first cell repeats its setup;
- anything you typed at a prompt (secrets survive; that is what they are for);
- the cache of model responses, so re-running a model cell calls the provider again.

Your cluster forgets nothing. Data a notebook loaded stays in Capella, which is why
`data-model/02` still finds what `data-model/01` wrote in an earlier session. The last cell
of each notebook drops what it created.

Edits to the notebook are not saved back here. **File → Save a copy in Drive** keeps your own.

## A key or password was rejected

The error names the setting, where its value came from — a Colab secret, or a prompt — and
whether it looks like it belongs to a different provider.

- **Keep going right now.** In a new cell, run `cbnb.update_setting("NANOGPT_API_KEY")` (or
  whichever name the error gave). It asks for the value in a masked box. Then re-run the
  cell that uses it — for an API key, the cell that creates `LLM()`.
- **Fix it for good.** Correct the secret in the key-icon panel, then **Runtime →
  Disconnect and delete runtime** and run from the top. A running session doesn't re-read a
  secret it has already loaded. (*Restart session* is not enough here, and its re-run of the
  setup cell fails on the clone it left behind.)

## Running a fork

The setup cell clones `omnifroodle/couchbase_notebooks`. To run your own fork's helpers
instead, set `CBNB_REPO_URL` before the first cell runs — in a cell above it:

```python
import os
os.environ["CBNB_REPO_URL"] = "https://github.com/you/couchbase_notebooks"
```

## How it differs from local and Codespaces

| | Local | Codespaces | Colab |
| --- | --- | --- | --- |
| Settings from | `.env` | Codespaces secrets | Colab secrets, or prompts |
| Repo available as | your checkout | a full checkout | cloned by the setup cell |
| `make run` / `make ship` | yes | yes | no |
| Survives a restart | yes | yes, until deleted | secrets only |
| Cost | your machine | your GitHub quota | Google's free tier |
