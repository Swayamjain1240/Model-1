# CI gate — the failure path, demonstrated (M10)

`make ci` ends with `python -m eval.run_eval --gate`, which re-runs hybrid retrieval and
fails the build when recall@10 drops by more than 0.02 or refusal accuracy falls below
0.90 against `results/baseline.json`. A checker that has only ever passed proves nothing,
so this records both paths.

## Run 1 — committed baseline (expected: pass)

```
$ python -m eval.run_eval --gate
gate: recall@10 0.8750 (baseline 0.8750)
gate: refusal accuracy 1.0000 (minimum 0.9)
gate ok
# exit code 0
```

## Run 2 — inflated baseline (expected: fail)

The baseline copy is the committed one with `recall_at_10` raised to `0.9550`. Nothing in `results/baseline.json` is touched,
and no retrieval code is sabotaged: to the gate this is indistinguishable from a
real regression, because it is the same comparison against a number the current
system no longer reaches.

```
$ python -m eval.run_eval --gate --baseline results/.baseline_inflated.json
gate: recall@10 0.8750 (baseline 0.9550)
gate: refusal accuracy 1.0000 (minimum 0.9)
FAILED: recall@10 dropped 0.0800 > 0.02
# exit code 1
```

## Verdict

- Passing run exit code: 0 (0 = gate ok).
- Failing run exit code: 1 (1 = build fails; CI marks the step red).
- The temporary baseline file is deleted after the run, so the repository's
  baseline is never the inflated one. `--baseline` exists only to make this demonstrable.
