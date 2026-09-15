#!/usr/bin/env bash
# Runs once when a codespace (or any dev container) is created.
# Mirrors `make setup`, minus creating .env: in a codespace, settings arrive as
# Codespaces secrets, and a .env copied from the example would shadow unset
# ones with placeholder values.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip

# CPU-only PyTorch first. Otherwise sentence-transformers pulls the CUDA build:
# several GB of GPU libraries a codespace has no GPU for.
.venv/bin/pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install --quiet -e ".[all]"

# Fetch the embedding model now, so the first notebook run doesn't stall on it.
HF_HUB_DISABLE_PROGRESS_BARS=1 .venv/bin/python -c \
  "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# "Open in JupyterLab" (github.com/codespaces) looks for Jupyter in
# /usr/local/jupyter, which the base image already has on PATH but leaves empty.
# Point it at .venv, so JupyterLab and its default python3 kernel are the same
# environment VS Code uses -- not a second, package-less Python.
SUDO=$([ "$(id -u)" -eq 0 ] && echo "" || echo "sudo")
if [ -d /usr/local/jupyter ] && [ ! -L /usr/local/jupyter ]; then
  $SUDO ln -sf "$PWD"/.venv/bin/jupyter* /usr/local/jupyter/
else
  $SUDO ln -sfn "$PWD/.venv/bin" /usr/local/jupyter
fi

# Same notebook checks as local development, for anyone committing from here.
if command -v make >/dev/null && [ -d .git ]; then
  make -s hooks
fi

echo "Ready. Open notebooks/ and pick the .venv kernel if VS Code asks."
