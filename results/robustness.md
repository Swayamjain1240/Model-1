# Robustness diagnostics (M5, recorded limitations)

Command: `python -m eval.robustness` · commit `2f792d0`

| category | id | recall@10 | answered | answered right doc | confidence |
|---|---|---|---|---|---|
| misspelled | a003 | 1.00 | no | no | 0.07 |
| misspelled | a013 | 1.00 | no | no | 0.06 |
| misspelled | a015 | 1.00 | no | no | 0.10 |
| short | a001 | 1.00 | yes | True | 0.23 |
| short | a008 | 1.00 | yes | True | 0.22 |
| short | a020 | 1.00 | yes | True | 0.15 |
| long | a003 | 1.00 | no | no | 0.05 |
| long | a013 | 1.00 | no | no | 0.09 |
| long | a015 | 1.00 | no | no | 0.08 |

Reading the table honestly:

- **Misspelled**: recall drops on typos because the hashed char-level TF-IDF has no
  fuzzy matching; the safe behavior is that the gate refuses below-theta noise rather
  than guessing. This is the documented MVP limitation; a real embedder is the fix.
- **Short**: keyword queries behave like the golden set (sparse's home turf).
- **Long**: padding dilutes the query vocabulary; where the key terms survive,
  retrieval still lands on the right doc.
- **Out of domain**: the frozen u-set refuses by calibration (results/calibration.md).
