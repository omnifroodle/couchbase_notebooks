# Local development loop. `make help` for the list.
PY := .venv/bin/python
NB ?= 01

.PHONY: help setup lab run run-to ship check

help:
	@echo "make setup            create .venv and install everything"
	@echo "make lab              open Jupyter Lab on the notebooks"
	@echo "make run NB=01        execute a notebook headless -> build/ (committed file untouched)"
	@echo "make run-to NB=01 UNTIL='regex'   run only the cells before the first match"
	@echo "make ship NB=01       execute fresh (no LLM cache), store outputs in the notebook, run checks"
	@echo "make check            lint + notebook checks"

setup:
	python3.11 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[all]"
	@test -f .env || (cp .env.example .env && echo "Created .env - fill it in.")

lab:
	.venv/bin/jupyter lab notebooks/

run:
	$(PY) scripts/run_notebook.py $(NB)

run-to:
	$(PY) scripts/run_notebook.py $(NB) --stop-before '$(UNTIL)'

ship:
	$(PY) scripts/run_notebook.py $(NB) --inplace --no-cache
	$(PY) scripts/check_notebooks.py

check:
	.venv/bin/ruff check cbnb scripts
	$(PY) scripts/check_notebooks.py
