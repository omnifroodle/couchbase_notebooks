# Local development loop. `make help` for the list.
PY := .venv/bin/python
NB ?= retrieval/01

.PHONY: help setup lab run run-to scratch ship check review slides hooks

help:
	@echo "make setup            create .venv and install everything"
	@echo "make lab              open Jupyter Lab on the notebooks"
	@echo "make run NB=retrieval/01     execute a notebook headless -> build/ (committed file untouched)"
	@echo "make run-to NB=retrieval/01 UNTIL='regex'  run only the cells before the first match"
	@echo "make scratch NB=retrieval/01 copy a notebook to build/scratch/ to explore without editing it"
	@echo "make ship NB=retrieval/01    execute fresh (no LLM cache), store outputs in the notebook, run checks"
	@echo "make check            lint + notebook checks"
	@echo "make review NB=retrieval/01  ask a model which claims the stored outputs no longer support"
	@echo "make slides NB=retrieval/03  a Marp deck walking through the notebook -> build/slides/"
	@echo "make slides NB=all     every deck, plus the index page GitHub Pages publishes"
	@echo "make hooks            run the notebook checks before every git commit"

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

# Interactive exploration on a throwaway copy. Keeps an existing scratch copy
# (it may have work in it) unless FRESH=1.
scratch:
	@n=$$(find notebooks -path "*/$(NB)*.ipynb" | wc -l); \
	if [ "$$n" -gt 1 ]; then echo "NB=$(NB) matches more than one notebook:"; \
	  find notebooks -path "*/$(NB)*.ipynb" | sort | sed 's|^notebooks/|  |'; exit 1; fi; \
	src=$$(find notebooks -path "*/$(NB)*.ipynb" | head -1); \
	if [ -z "$$src" ]; then echo "No notebook matches NB=$(NB)"; exit 1; fi; \
	dst=build/scratch/$$(basename $$src); \
	mkdir -p build/scratch; \
	if [ -f "$$dst" ] && [ -z "$(FRESH)" ]; then echo "Reusing $$dst (FRESH=1 to recopy)"; \
	else cp "$$src" "$$dst" && echo "Copied $$src -> $$dst"; fi; \
	if command -v code >/dev/null; then code "$$dst"; else echo "Open $$dst"; fi

ship:
	$(PY) scripts/run_notebook.py $(NB) --inplace --no-cache
	$(PY) scripts/check_notebooks.py

# Advisory, and not part of `check` on purpose: a model's opinion should never
# gate a commit, and this needs an API key that `check` does not.
review:
	$(PY) scripts/review_notebook.py $(NB)

# Built from the stored outputs; nothing is re-run. See the script's docstring for the rules.
slides:
	$(PY) scripts/make_slides.py $(NB)

check:
	.venv/bin/ruff check cbnb scripts
	$(PY) scripts/check_notebooks.py

hooks:
	@printf '#!/bin/sh\n# Installed by `make hooks`. Remove this file to disable.\nexec .venv/bin/python scripts/check_notebooks.py\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed: notebook checks run before every commit"
