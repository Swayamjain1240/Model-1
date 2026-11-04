# Atlas — one-command local engineering targets (ATL-EDD-001 s.2)
# setup / eval / serve land with code in M2, M3 and M5; absent targets are not
# pretended here.

PY ?= python3

.PHONY: corpus limits test check ci

corpus:
	$(PY) scripts/check_corpus.py

limits:
	$(PY) scripts/check_limits.py

test:
	$(PY) -m pytest

check: limits corpus test

ci: check

# the eval-gate stage lands in M3 together with results/baseline.json.
