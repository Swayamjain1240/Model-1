# Atlas — one-command local engineering targets (ATL-EDD-001 s.2)
# setup / eval / serve land with code in M2, M3 and M5; absent targets are not
# pretended here.

PY ?= python3
VENV_PY ?= $(PY)
# on a Windows checkout the venv interpreter is .venv/Scripts/python.exe;
# on Unix .venv/bin/python - set VENV_PY accordingly when using venv targets.

.PHONY: corpus limits test eval check ci setup ingest serve handover

corpus:
	$(PY) scripts/check_corpus.py

limits:
	$(PY) scripts/check_limits.py

test:
	$(PY) -m pytest

eval:
	$(PY) -m eval.run_eval

check: limits corpus test

ci: check

# FR-28 one-command path (the clean-clone proof in M5 of the plan / our M6):
setup:
	$(PY) -m venv .venv
	$(VENV_PY) -m pip install -e .

ingest:
	$(VENV_PY) -m atlas.cli --db data/atlas.db ingest corpus/campus

serve:
	$(VENV_PY) -m atlas.cli --db data/atlas.db serve

handover:
	$(PY) scripts/repro_clone.py

# the eval gate runs in CI against results/baseline.json (ATL-EDD-001 s.7);
# product-side theta calibration lands in M4 with the answer path.
