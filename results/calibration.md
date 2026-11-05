# Theta calibration on observed hybrid scores (M4)

Command: `python -m eval.calibrate` · commit `54ffd79` · platform: Windows-11-10.0.26300-SP0

## Score distributions (hybrid top passage)

- answerable n=24: min 0.0338, max 0.1499
- unanswerable n=6: min 0.0750, max 0.1226

## Sweep over the observed range

| theta | answer rate | refusal accuracy | false accepts | false refusals |
|---|---|---|---|---|
| 0.01 | 1.00 | 0.00 | 6 | 0 |
| 0.03 | 1.00 | 0.00 | 6 | 0 |
| 0.05 | 0.88 | 0.00 | 6 | 3 |
| 0.07 | 0.54 | 0.00 | 6 | 11 |
| 0.09 | 0.46 | 0.67 | 2 | 13 |
| 0.11 | 0.29 | 0.83 | 1 | 17 |
| 0.13 | 0.04 | 1.00 | 0 | 23 |
| 0.15 | 0.00 | 1.00 | 0 | 24 |

**Chosen theta: 0.13** - safety-first rule: the lowest theta with zero false accepts (a wrong citation is the dangerous error class; a refusal is safe). Answer rate recovers at stage 2 with real embeddings.

Alternative shown: balanced knee would be theta 0.09 (answer rate 0.46, refusal accuracy 0.67) - rejected because it lets 2 unanswerable queries through as answers.

This is in-sample calibration on the frozen set (no held-out split at MVP); stage 2 re-checks on the expanded v2 set. No value was tuned toward a target.
