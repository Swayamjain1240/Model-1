# Atlas — one-command local engineering targets (ATL-EDD-001 s.2)
# setup / eval / serve land with code in M2, M3 and M5; absent targets are not
# pretended here.

PY ?= python3
VENV_PY ?= $(PY)
# on a Windows checkout the venv interpreter is .venv/Scripts/python.exe;
# on Unix .venv/bin/python - set VENV_PY accordingly when using venv targets.

.PHONY: corpus limits test eval embed ablation holdout support answer-selection safety bench soak soak-interactive dashboard trace gate-demo check ci setup ingest serve handover

corpus:
	$(PY) scripts/check_corpus.py

limits:
	$(PY) scripts/check_limits.py

test:
	$(PY) -m pytest

eval:
	$(PY) -m eval.run_eval

# stage-2 layer 1 (M7): the measured delta of a real encoder vs the hashed stand-in
embed:
	$(PY) -m eval.embeddings

# M10: five configurations x two encoders, with control arm and confidence intervals
ablation:
	$(PY) -m eval.ablation

# M11: out-of-sample set; fit on v1, decide on v2 (never the reverse)
holdout:
	$(PY) -m eval.holdout

# M14: second refusal signal; floor fitted on v1, adopted only if v3 improves with no lost answers
support:
	$(PY) -m eval.support

# M15: answer selection - is the returned sentence the document's topic list instead of its rule?
answer-selection:
	$(PY) -m eval.answer_selection

# stage-2 layer 2 (M9): injection suite, tenant probes, log audit, degraded mode
safety:
	$(PY) -m eval.safety

# M10: latency curve at 1/10/50 users, then a 30-minute soak at the NFR-01 operating point
bench:
	$(PY) -m bench.sweep

soak:
	$(PY) -m bench.sweep --soak-seconds 1800 --users 10

# M11: the same 10 users with 100 ms think time, i.e. people rather than a saturation test
soak-interactive:
	$(PY) -m bench.sweep --soak-seconds 900 --users 10 --think-ms 100

# M10: the dashboard is generated from results/*.json, so it cannot drift from the reports
dashboard:
	$(PY) scripts/dashboard.py

trace:
	$(PY) scripts/trace_sample.py

gate-demo:
	$(PY) scripts/ci_gate_demo.py

check: limits corpus test

# the CI gate also runs the safety suite: a guard regression must fail the build
ci: check safety

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
