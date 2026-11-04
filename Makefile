# Atlas — one-command local engineering targets (ATL-EDD-001 s.2)
# setup / eval / serve land with code in M2, M3 and M5; absent targets are not
# pretended here.

PY ?= python3

.PHONY: corpus limits test eval check ci

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

# the eval gate runs in CI against results/baseline.json (ATL-EDD-001 s.7);
# product-side theta calibration lands in M4 with the answer path.
