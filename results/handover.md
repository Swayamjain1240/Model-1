# Handover proof (M6, FR-28): clean clone -> same commands -> same numbers

HEAD `43b2eb1cd6af` · generator `scripts/repro_clone.py`

| step | exit | seconds | tail |
|---|---|---|---|
| archive HEAD (tracked files only, like a fresh clone) | 0 | 1.42 | ok |
| unpack into clean-clone/ | 0 | 0.13 | ok |
| setup: fresh virtualenv from the host interpreter | 0 | 13.32 | ok |
| setup: pip install -e . (numpy only, per NFR-20 budget) | 0 | 36.75 | ok |
| ingest: 18 policy documents | 0 | 2.25 | ingested 34 new chunks from 18 files into tenant 'campus' |
| eval gate in the clean clone | 0 | 0.8 | gate: refusal accuracy 1.0000 (minimum 0.9) / gate ok |
| serve smoke: /v1/healthz + one /v1/ask | 0 | - | ok |

Fresh-clone eval vs committed baseline: recall@10 **0.8750** (expected 0.8750), refusal accuracy **1.0000** (expected 1.0000) — verdict: **PASS**

Steps above are the actual operator commands from the README, run in a fresh
`git archive HEAD` clone (tracked files only — no working-tree drift, no old DB)
with a brand-new virtualenv. Single node, no containers.
