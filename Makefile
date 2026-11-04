# Atlas — one-command local engineering targets (ATL-EDD-001 s.2)
# setup / eval / serve land with code in M2, M3 and M5; absent targets are not
# pretended here.

PY ?= python3

.PHONY: corpus limits check ci

corpus:
	$(PY) scripts/check_corpus.py

limits:
	$(PY) scripts/check_limits.py

check: limits corpus

ci: check

# unit / integration / eval-gate stages land in M2 and M3 once code exists.
