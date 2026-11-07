# 13 — Handover Runbook (M6)

What to run, what it proves, and where every number lives. Written for the
person who inherits this repository cold.

## 0. The 60-second demo

```bash
python -m atlas.cli --db data/atlas.db ingest corpus/campus   # once
python -m atlas.cli --db data/atlas.db serve                  # then open http://127.0.0.1:8070/
```

The demo page answers **with citations** or refuses **below the calibrated
gate** (θ = 0.13). With `ATLAS_API_TOKEN` set, unauthenticated requests get
`401 AUTH_REQUIRED`. On the make side: `make setup && make ingest && make serve`
(FR-28; on Unix set `VENV_PY=.venv/bin/python`, on Windows it is
`.venv/Scripts/python.exe`).

## 1. The FR-28 clean-clone proof

The one number I could not fake, because the script runs it live every time:

```
python scripts/repro_clone.py          # receipt: results/handover.{md,json}
```

`git archive HEAD` → brand-new venv → `pip install -e .` → ingest → eval gate →
serve smoke test, then the clone's own `eval_report.json` is compared to the
committed `results/baseline.json`. Latest receipt: **recall@10 0.8750 vs
0.8750, refusal accuracy 1.0000 vs 1.0000 — PASS**. If someone claims the
repository is not reproducible, this receipt is the answer.

## 2. Evidence index (every number points at a committed file)

| Claim | Receipt |
|---|---|
| retrieval baseline + ablations | `results/eval_report.md`, `results/baseline.json` |
| refusal gate θ = 0.13 calibration story | `results/calibration.md` |
| fr-11 diagnosis: what hybrid loses, why | `results/fr11_diagnosis.md` |
| in-process latency (hybrid 0.60 ms mean) | `results/latency.md` |
| NFR-01: burst PASS 43.25 ms; saturation soak 58.40 ms (miss); interactive soak 19.56 ms (pass) at 10 users | `results/bench.md`, `results/soak.md`, `results/soak-interactive.md` |
| robustness (gate, not retrieval, is the bottleneck) | `results/robustness.md` |
| handover proof (this runbook, §1) | `results/handover.md` |
| stage-2 encoder delta (dense 0.75 → 1.00, answer rate 0.29 → 0.96) | `results/embeddings.md` |
| stage-2 reranker, held out by document (0.90, not adopted) | `results/rerank.md` |
| safety suite: injections, tenant probes, log audit, degraded mode | `results/safety.md` |
| out-of-sample set: retrieval generalises, the refusal gate does not | `results/holdout.md` |

## 3. Known limitations (state them, do not hide them)

- **Answer rate is low by design**: the safety-first gate θ = 0.13 refuses
  reworded/misspelled variants even when retrieval found the right document
  (see `results/robustness.md`). The fix is real embeddings, not gate tuning.
- **recall@10 is 0.875, not the 0.90 target (NFR-04)**: nine queries lost by
  hybrid RRF-k, diagnosed in `results/fr11_diagnosis.md`.
- **The refusal gate does not generalise**: theta was fitted to six unanswerable
  questions, where it scored 1.0000. On the six written afterwards (v2) it scores
  **0.1667** - the classes overlap, and no theta in the grid separates them
  (`results/holdout.md`). Clients should read the `confidence` field rather than
  treat "answered" as "supported". The fix is a second signal, not a new threshold
  (ADR-0007).
- **Single-node, single-process**: stdlib `ThreadingHTTPServer`, SQLite storage.
  No containers, no cloud, per project constraint. The documented scale limit
  is ~10k chunks (NFR-03); beyond that, ANN storage.
- **Not deployed**: the API has no deployment I/O here; the deepening work
  (stage 2) replaces the hashed-TF-IDF embedder seed with a real model.

## 4. Stage-2 roadmap in one paragraph

1. ~~replace the TF-IDF embedder with a real sentence model~~ **done (M7)**: dense
   recall@10 0.75 → 1.00, gate answer rate 0.29 → 0.96 at refusal 1.00 with theta
   re-calibrated to 0.31 for the new score scale (`results/embeddings.md`). The delta
   was reported against the frozen set and nothing was tuned to it;
2. train the reranker on a document-held-out split — **attempted in M8 and not adopted**:
   pointwise and pairwise fits both reached 0.90 on the ten held-out questions against
   dense-only 1.00, so the blend still ships and FR-11 stays open (`results/rerank.md`).
   The next honest attempt needs a larger labelled set, not more feature engineering on
   twenty-four questions;
3. generative synthesis behind a source-verification gate, one paragraph max,
   refusal preserved end-to-end;
4. the M6 answer-rate and θ story re-measured and re-reported against the
   stage-2 numbers, with a widened golden set only as an appended v2.
