"""The second refusal signal, measured (M14, FR-16).

One question, asked before the numbers were produced: does adding a *corpus-vocabulary* signal to
the confidence gate refuse more unanswerable questions without refusing answerable ones?

The rules, written down before the run:

1. **Fit on v1.** The only tuned quantity is `floor`, the share of a question's *content* terms
   (question words excluded) that the corpus must have never seen for the request to be refused
   regardless of confidence. The fitted value is the smallest floor in the grid strictly above
   the highest novelty observed among v1's answerable questions - the most aggressive floor that
   still leaves every tuned-set answer untouched. Nothing else is tuned, and theta does not move.
   The floor only ever *adds* a refusal, and only when at least `MIN_UNSEEN` (2) content terms are
   unseen: one unused modifier is not a missing topic. Both rules are fixed before the run - the
   first version of this measurement counted "what" and "how" as unknown words, which produced a
   novelty score that was partly a count of pronouns; the report says so rather than hiding it.
2. **Decide on v3.** v2 is reported as a replication; v3 is the set the decision is read from.
3. **Adopt only if all four hold:** v3 refusal accuracy improves over the confidence-only
   baseline, v3 answer rate does not fall, v2 answer rate does not fall, and v1 answer rate stays
   at 1.0000. A signal that buys refusals with answers is not a signal, it is a threshold raise
   with extra steps - which `results/holdout.md` already shows does not work.

The signal itself is in `src/atlas/support.py`; this file only measures it, and it does so from
confidences computed once, so every row of the floor grid is the same measurement re-bucketed.

Writes `results/support.md` and `results/support.json`.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.config import SETTINGS  # noqa: E402
from atlas.retrieval import HybridIndex  # noqa: E402
from atlas.support import MIN_UNSEEN, novelty, refuses, unseen_terms  # noqa: E402
from eval import metrics  # noqa: E402
from eval.holdout import load_v2, load_v3  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

ENCODER = "potion-base-8M"
FLOORS = (0.33, 0.40, 0.50, 0.60, 0.67, 0.75, 1.0)


def score_set(index: HybridIndex, questions: list[dict], vocabulary: frozenset[str]) -> list[dict]:
    """Confidence and novelty per question, measured once."""
    tenant = SETTINGS.default_tenant
    rows = []
    for question in questions:
        report = index.diagnostics(question["query"], tenant_id=tenant)
        confidence = 0.0 if report is None else round(report[1]["confidence"], 4)
        rows.append(
            {
                "id": question["id"],
                "answerable": question["answerable"],
                "confidence": confidence,
                "novelty": novelty(question["query"], vocabulary),
                "unseen": unseen_terms(question["query"], vocabulary),
            }
        )
    return rows


def accuracy(rows: list[dict], *columns: str) -> tuple[float, float]:
    """Answer rate over answerable rows, refusal accuracy over unanswerable ones."""
    theta = SETTINGS_THETA
    answered = [row for row in rows if row["answerable"] and row["confidence"] >= theta]
    refused = [
        row for row in rows if not row["answerable"] and row["confidence"] < theta
    ]
    total_answerable = sum(1 for row in rows if row["answerable"])
    total_unanswerable = sum(1 for row in rows if not row["answerable"])
    answer_rate = metrics.rate_with_ci(
        [1.0] * len(answered) + [0.0] * (total_answerable - len(answered))
    )["mean"]
    refusal = metrics.rate_with_ci(
        [1.0] * len(refused) + [0.0] * (total_unanswerable - len(refused))
    )["mean"]
    return answer_rate, refusal


def with_floor(rows: list[dict], floor: float) -> tuple[float, float]:
    """Answer rate and refusal accuracy for the combined rule at one floor."""
    theta = SETTINGS_THETA
    passes = [
        row
        for row in rows
        if not refuses(
            confidence=row["confidence"],
            theta=theta,
            novel=row["novelty"],
            unseen=len(row["unseen"]),
            floor=floor,
        )
    ]
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    answered = sum(1 for row in passes if row["answerable"])
    refused = sum(1 for row in unanswerable if row not in passes)
    answer_rate = metrics.rate_with_ci(
        [1.0] * answered + [0.0] * (len(answerable) - answered)
    )["mean"]
    refusal = metrics.rate_with_ci(
        [1.0] * refused + [0.0] * (len(unanswerable) - refused)
    )["mean"]
    return answer_rate, refusal


def spread(rows: list[dict]) -> dict:
    values = [row["novelty"] for row in rows]
    return {"min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 4)}


SETTINGS_THETA = dataclasses.replace(SETTINGS, embedder_kind=ENCODER).theta


def main() -> int:
    v1_answerable, v1_unanswerable = load_questions()
    v2_answerable, v2_unanswerable = load_v2()
    v3_answerable, v3_unanswerable = load_v3()
    store = build_store(SETTINGS.default_tenant)
    try:
        settings = dataclasses.replace(SETTINGS, embedder_kind=ENCODER)
        index = HybridIndex(store, settings=settings)
        view = index.view(SETTINGS.default_tenant)
        assert view is not None, "no corpus ingested: run the ingest target first"
        vocabulary = frozenset(view.idf)
        measured = {
            "v1": score_set(index, v1_answerable, vocabulary)
            + score_set(index, v1_unanswerable, vocabulary),
            "v2": score_set(index, v2_answerable, vocabulary)
            + score_set(index, v2_unanswerable, vocabulary),
            "v3": score_set(index, v3_answerable, vocabulary)
            + score_set(index, v3_unanswerable, vocabulary),
        }
    finally:
        store.close()

    baseline = {label: accuracy(rows) for label, rows in measured.items()}
    v1_answerable_rows = [row for row in measured["v1"] if row["answerable"]]
    worst_on_v1 = max(row["novelty"] for row in v1_answerable_rows)
    eligible = [floor for floor in FLOORS if floor > worst_on_v1]
    floor = min(eligible) if eligible else 1.0

    grid = [
        {
            "floor": candidate,
            **{
                label: with_floor(rows, candidate)
                for label, rows in measured.items()
            },
        }
        for candidate in FLOORS
    ]
    adopted_result = {label: (answer, refusal) for label, (answer, refusal) in
                      ((label, with_floor(rows, floor)) for label, rows in measured.items())}

    improves_v3 = adopted_result["v3"][1] > baseline["v3"][1]
    keeps_answers = (
        adopted_result["v3"][0] >= baseline["v3"][0]
        and adopted_result["v2"][0] >= baseline["v2"][0]
        and adopted_result["v1"][0] >= baseline["v1"][0]
    )
    adopted = improves_v3 and keeps_answers

    payload = {
        "provenance": provenance(),
        "method": (__doc__ or "").strip(),
        "encoder": ENCODER,
        "theta": SETTINGS_THETA,
        "vocabulary_size": len(vocabulary),
        "fitted_floor": floor,
        "fit": {
            "rule": "smallest grid floor strictly above the highest novelty among v1 answerables",
            "worst_v1_answerable_novelty": worst_on_v1,
            "eligible_floors": eligible,
        },
        "baseline": {label: {"answer_rate": pair[0], "refusal_accuracy": pair[1]}
                     for label, pair in baseline.items()},
        "adopted": {label: {"answer_rate": pair[0], "refusal_accuracy": pair[1]}
                    for label, pair in adopted_result.items()},
        "grid": [
            {"floor": row["floor"],
             **{label: {"answer_rate": row[label][0], "refusal_accuracy": row[label][1]}
                for label in measured}}
            for row in grid
        ],
        "decision": {
            "adopted": adopted,
            "improves_v3_refusal": improves_v3,
            "keeps_answer_rate": keeps_answers,
        },
        "novelty": {
            label: {
                "answerable": spread([row for row in rows if row["answerable"]]),
                "unanswerable": spread([row for row in rows if not row["answerable"]]),
            }
            for label, rows in measured.items()
        },
        "unseen_terms": {
            label: {row["id"]: list(row["unseen"]) for row in rows if row["unseen"]}
            for label, rows in measured.items()
        },
        "unanswerable_detail": {
            label: [
                {
                    "id": row["id"],
                    "confidence": row["confidence"],
                    "novelty": row["novelty"],
                    "unseen": list(row["unseen"]),
                    "refused_by_confidence": row["confidence"] < SETTINGS_THETA,
                    "refused_after": refuses(
                        confidence=row["confidence"],
                        theta=SETTINGS_THETA,
                        novel=row["novelty"],
                        unseen=len(row["unseen"]),
                        floor=floor,
                    ),
                }
                for row in rows
                if not row["answerable"]
            ]
            for label, rows in measured.items()
        },
    }
    (RESULTS / "support.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# The second refusal signal — does the corpus know the question's words? (M14)",
        "",
        f"Encoder `{ENCODER}`, theta fixed at {SETTINGS_THETA:.2f}, vocabulary "
        f"{len(vocabulary)} terms. Baseline is the confidence gate alone; `floor` adds one rule:",
        "refuse when at least that share of the question's content terms occurs nowhere in the",
        f"corpus *and* at least {MIN_UNSEEN} such terms exist. Confidence and novelty are measured",
        "once per question, so every grid row below",
        "is the same measurement re-bucketed - there is no second chance to make the signal look",
        "good by re-running something.",
        "",
        "## What the signal sees that confidence cannot",
        "",
        "| set | class | novelty min | max | mean |",
        "|---|---|---|---|---|",
    ]
    for label, groups in payload["novelty"].items():
        for group in ("answerable", "unanswerable"):
            stats = groups[group]
            lines.append(
                f"| {label} | {group} | {stats['min']:.2f} | {stats['max']:.2f} "
                f"| {stats['mean']:.4f} |"
            )
    lines += [
        "",
        "## Before and after the fitted floor",
        "",
        f"Fitted floor: **{floor:.2f}** - {payload['fit']['rule']}, and the worst v1 answerable",
        f"question has novelty {worst_on_v1:.4f}. theta does not move.",
        "",
        "| set | baseline answer | baseline refusal | + floor answer | + floor refusal |",
        "|---|---|---|---|---|",
    ]
    for label in ("v1", "v2", "v3"):
        before, after = payload["baseline"][label], payload["adopted"][label]
        lines.append(
            f"| {label} | {before['answer_rate']:.4f} | {before['refusal_accuracy']:.4f} "
            f"| {after['answer_rate']:.4f} | {after['refusal_accuracy']:.4f} |"
        )
    lines += [
        "",
        "## Every floor, all three sets",
        "",
        "| floor | v1 answer | v1 refusal | v2 answer | v2 refusal | v3 answer | v3 refusal |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in payload["grid"]:
        marker = " (fitted)" if row["floor"] == floor else ""
        lines.append(
            f"| {row['floor']:.2f}{marker} | {row['v1']['answer_rate']:.4f} "
            f"| {row['v1']['refusal_accuracy']:.4f} | {row['v2']['answer_rate']:.4f} "
            f"| {row['v2']['refusal_accuracy']:.4f} | {row['v3']['answer_rate']:.4f} "
            f"| {row['v3']['refusal_accuracy']:.4f} |"
        )
    lines += ["", "## Decision", ""]
    if adopted:
        lines += [
            f"- **Adopted** at floor {floor:.2f}: v3 refusal "
            f"{payload['baseline']['v3']['refusal_accuracy']:.4f} → "
            f"{payload['adopted']['v3']['refusal_accuracy']:.4f} while the answer rate stays at "
            f"{payload['adopted']['v3']['answer_rate']:.4f} on v3 and does not fall on v1 or v2.",
        ]
    else:
        reasons = []
        if not improves_v3:
            reasons.append(
                f"v3 refusal did not improve "
                f"({payload['baseline']['v3']['refusal_accuracy']:.4f} → "
                f"{payload['adopted']['v3']['refusal_accuracy']:.4f})"
            )
        if not keeps_answers:
            reasons.append(
                f"it costs answers (v1 {payload['baseline']['v1']['answer_rate']:.4f} → "
                f"{payload['adopted']['v1']['answer_rate']:.4f}, v2 "
                f"{payload['baseline']['v2']['answer_rate']:.4f} → "
                f"{payload['adopted']['v2']['answer_rate']:.4f}, v3 "
                f"{payload['baseline']['v3']['answer_rate']:.4f} → "
                f"{payload['adopted']['v3']['answer_rate']:.4f})"
            )
        lines += [
            f"- **Not adopted** at floor {floor:.2f}: {' and '.join(reasons)}.",
            "- The rule, not the number, is the result: a signal that only helps at a floor that",
            "  the corpus' own questions cannot clear is a threshold with extra vocabulary.",
        ]
    lines += [
        "",
        "## Every unanswerable question, before and after",
        "",
        "This is the whole evidence for the numbers above - six questions per appended set, so one",
        "row is worth 0.1667 of refusal accuracy. Read it that way.",
        "",
        "| set | id | confidence | novelty | unseen terms | refused before | refused after |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, rows in payload["unanswerable_detail"].items():
        for row in rows:
            terms = ", ".join(row["unseen"]) or "-"
            lines.append(
                f"| {label} | {row['id']} | {row['confidence']:.3f} | {row['novelty']:.3f} "
                f"| {terms} | {'yes' if row['refused_by_confidence'] else 'no'} "
                f"| {'yes' if row['refused_after'] else 'no'} |"
            )
    lines += [
        "",
        "## What this signal still cannot see",
        "",
        "- **Dilution.** v3-014 fails because three unknown words sit beside four known ones:",
        "  0.429 is below the floor, so a question about parking is answered from hostel rules;",
        "  A share cannot tell a missing topic from a wordy question; only a weighting could.",
        "- **All-attested topics.** v3-018 asks about a sports scholarship using words the corpus",
        "  does use (\"sports\", \"scholarship\", \"attendance\") and scores 0.000 novelty with",
        "  confidence",
        "  0.497. Vocabulary cannot refute a question whose words all exist; that needs meaning.",
        "- **Corpus size.** The floor was fitted on 18 documents and 1027 terms. A tenant with",
        "  far fewer documents has almost no vocabulary, so the floor must be re-fitted per",
        "  corpus - the mini test fixture refuses everything at 0.50 for exactly this reason.",
        "",
        "## Questions the signal cannot see",
        "",
    ]
    unseen = payload["unseen_terms"]
    for label in ("v2", "v3"):
        listed = ", ".join(
            f"`{qid}` ({', '.join(terms)})" for qid, terms in unseen[label].items()
        ) or "none"
        lines.append(f"- {label}: {listed}")
    lines.append("")
    (RESULTS / "support.md").write_text("\n".join(lines), encoding="utf-8")

    print("written: results/support.md, results/support.json")
    print(f"  fitted floor {floor:.2f} (worst v1 answerable novelty {worst_on_v1:.4f})")
    for label in ("v1", "v2", "v3"):
        before, after = payload["baseline"][label], payload["adopted"][label]
        print(f"  {label}: answer {before['answer_rate']:.4f} -> {after['answer_rate']:.4f} "
              f"| refusal {before['refusal_accuracy']:.4f} -> {after['refusal_accuracy']:.4f}")
    print(f"  adopted: {adopted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
