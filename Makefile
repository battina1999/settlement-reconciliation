PYTHON ?= python3
VENV := .venv
RUN := PYTHONPATH=src $(VENV)/bin/python

.PHONY: demo test serve

$(VENV)/.installed: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements.txt
	touch $@

demo: $(VENV)/.installed
	$(RUN) scripts/run_demo.py

test: $(VENV)/.installed
	$(RUN) -m pytest -q

serve:
	$(PYTHON) -m http.server 8000 --bind 127.0.0.1 --directory docs
