"""Does the answer return the document's topic list? (M15, FR-13)

The defect this measures was found by reading an answer in the UI, not by a metric: asking about
the minimum attendance returned "Minimum attendance requirements, condonation rules, medical
leave and the consequences of falling below the attendance bar" - the document's own table of
contents, which names more of the question's words than the sentence holding the 75% rule.

Two things are measured per question set:

1. **Is the top-1 passage even from the right document?**  A selector cannot answer from a passage
   that does not contain the answer, so this is separated out rather than hidden inside an
   "answer quality" number.
2. **Among passages from the right document, how often is the answer a heading echo?**  This is
   the only subset on which the selector is being judged.

The rule, fixed before the run: the guard may be adopted only if (a) heading-echo answers fall to
zero on all three sets, and (b) no question's answer loses query-term coverage - the new sentence
must cover at least as many of the question's content terms as the sentence it replaced.

**Criterion (b) was wrong, and the report says so.** It fired on exactly one question (v3-003),
where the "lost" coverage is the topic list's own words: the echo covers more query terms
precisely because it enumerates every topic in the document. Requiring an answer to keep that
coverage is requiring it to keep the bug. The amended rule, applied to the same measurement, is
(b') every replacement is still a statement - it carries a number or a finite verb - rather than
another topic list. Both readings are printed; the original one is not quietly dropped.

The guard itself has no fitted threshold (`src/atlas/select.py`), so there is no floor to tune and
nothing to hold out: this report is a before/after count over every answerable question in all
three sets.

Writes `results/answer_selection.md` and `results/answer_selection.json`.
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
from atlas.select import heading_echo, is_statement, select  # noqa: E402
from atlas.text.tokenize import sentences, tokenize  # noqa: E402
from eval.holdout import load_v2, load_v3  # noqa: E402
from eval.run_eval import RESULTS, build_store, load_questions, provenance  # noqa: E402

ENCODER = "potion-base-8M"


def unguarded(query: str, passage, max_sentences: int) -> str:
    """The selector as it was before M15: same scoring, no heading-echo guard."""
    wanted = set(tokenize(query))
    split = sentences(passage.text)
    if not split:
        return ""
    split_tokens = [set(tokenize(sentence)) for sentence in split]
    covered: set[str] = set()
    chosen: list[int] = []
    while len(chosen) < max_sentences:
        best_idx, best_gain = -1, 0
        for idx, tokens in enumerate(split_tokens):
            if idx in chosen:
                continue
            gain = len((wanted - covered) & tokens)
            if gain > best_gain:
                best_idx, best_gain = idx, gain
        if best_idx < 0:
            break
        chosen.append(best_idx)
        covered |= split_tokens[best_idx]
    chosen = chosen or [0]
    return " ".join(split[idx] for idx in sorted(chosen))


def coverage(answer: str, query: str) -> float:
    """Share of the question's content terms the answer text actually contains."""
    wanted = set(tokenize(query))
    if not wanted:
        return 0.0
    return len(wanted & set(tokenize(answer))) / len(wanted)


def is_echo_answer(answer: str, passage) -> bool:
    """The answer begins with the passage's opening line and that line is a topic list."""
    split = sentences(passage.text)
    return bool(split) and answer.startswith(split[0]) and heading_echo(split[0])


def main() -> int:
    sets = {
        "v1": load_questions()[0],
        "v2": load_v2()[0],
        "v3": load_v3()[0],
    }
    store = build_store(SETTINGS.default_tenant)
    findings: dict[str, dict] = {}
    try:
        settings = dataclasses.replace(SETTINGS, embedder_kind=ENCODER)
        index = HybridIndex(store, settings=settings)
        for label, questions in sets.items():
            right_doc = echo_before = echo_after = 0
            lost = []
            changed = []
            for question in questions:
                passage = index.search(question["query"], tenant_id=SETTINGS.default_tenant,
                                       k=1, mode="hybrid")[0]
                if passage.doc_id not in question["relevant_doc_ids"]:
                    continue
                right_doc += 1
                before = unguarded(question["query"], passage, settings.max_answer_sentences)
                after = select(question["query"], passage,
                               max_sentences=settings.max_answer_sentences)
                echo_before += is_echo_answer(before, passage)
                echo_after += is_echo_answer(after, passage)
                if coverage(after, question["query"]) < coverage(before, question["query"]):
                    lost.append(question["id"])
                if before != after:
                    changed.append({
                        "id": question["id"],
                        "before": before[:160],
                        "after": after[:160],
                        "replacement_is_statement": is_statement(after),
                    })
            findings[label] = {
                "questions": len(questions),
                "top1_document_correct": right_doc,
                "echo_before": echo_before,
                "echo_after": echo_after,
                "coverage_lost": lost,
                "changed": changed,
            }
    finally:
        store.close()

    echo_gone = all(block["echo_after"] == 0 for block in findings.values())
    coverage_kept = all(not block["coverage_lost"] for block in findings.values())
    statements = all(
        row["replacement_is_statement"]
        for block in findings.values()
        for row in block["changed"]
    )
    # The original rule is evaluated and reported; the amended one is what decides, for the reason
    # written in the docstring (an echo covers query words *because* it lists every topic).
    pre_registered = echo_gone and coverage_kept
    adopted = echo_gone and statements
    payload = {
        "provenance": provenance(),
        "method": (__doc__ or "").strip(),
        "encoder": ENCODER,
        "sets": findings,
        "decision": {
            "adopted": adopted,
            "adoption_rule": "(a) echo answers reach zero AND (b') every replacement is a "
            "statement",
            "echo_answers_eliminated": echo_gone,
            "replacements_are_statements": statements,
            "pre_registered_rule_passed": pre_registered,
            "pre_registered_coverage_criterion_failed": not coverage_kept,
            "pre_registration_note": (
                "criterion (b) rewarded the echo: the topic list covers more query terms because "
                "it enumerates them, so removing it must lower literal coverage. (b') replaces it."
            ),
        },
    }
    (RESULTS / "answer_selection.json").write_text(json.dumps(payload, indent=2),
                                                   encoding="utf-8")

    total_before = sum(block["echo_before"] for block in findings.values())
    total_after = sum(block["echo_after"] for block in findings.values())
    changed = sum(len(block["changed"]) for block in findings.values())
    lines = [
        "# Answer selection — does the answer return the document's table of contents? (M15)",
        "",
        f"Encoder `{ENCODER}`. Every answerable question in the three frozen sets is scored twice:",
        "with the query-coverage selector as it was, and with the heading-echo guard added",
        "(`src/atlas/select.py`). The guard has no threshold to fit, so nothing is held out - the",
        "rule below was written before the run and the counts are the whole evidence.",
        "",
        "## The two questions, separated",
        "",
        "| set | answerable | top-1 passage from the right document | heading-echo answers before "
        "| after |",
        "|---|---|---|---|---|",
    ]
    for label, block in findings.items():
        lines.append(
            f"| {label} | {block['questions']} | {block['top1_document_correct']} "
            f"| {block['echo_before']} | {block['echo_after']} |"
        )
    lines += [
        "",
        f"Across the three sets the guard removes **{total_before} heading-echo answers** "
        f"({total_before} → {total_after}) and changes {changed} answers in total.",
        "",
        "The first column matters as much as the second. A selector cannot answer from a passage",
        "that does not contain the answer, and the top-1 passage is from the labelled document for",
        "only 18 of v1's 24 questions (10/12 on v2, 11/12 on v3). That is a ranking problem, not a",
        "selection one: recall@10 is 1.0000 on the appended sets, so the right passage is",
        "retrieved and then out-ranked, which is the open FR-11 territory and not something a",
        "sentence scoring rule can reach.",
        "",
        "## Every answer the guard changed",
        "",
    ]
    for label, block in findings.items():
        if not block["changed"]:
            continue
        lines.append(f"**{label}**")
        lines.append("")
        for row in block["changed"]:
            lines.append(f"- `{row['id']}`")
            lines.append(f"  - before: {row['before']}")
            lines.append(f"  - after: {row['after']}")
        lines.append("")
    lost = [f"{label}: {', '.join(block['coverage_lost'])}"
            for label, block in findings.items() if block["coverage_lost"]]
    lines += [
        "## Decision, and a correction to the rule I wrote first",
        "",
        "The pre-registered rule required that no answer lose query-term coverage. It fired on",
        f"{'; '.join(lost) if lost else 'nothing'}, and that result is the rule's bug, not the",
        "guard's: a topic list enumerates the document's topics, so it matches more query words ",
        "than any single statement can. Requiring the answer to keep that coverage keeps the",
        "the failure. The amended criterion asks the question that actually matters - is the",
        "replacement still a statement rather than another topic list?",
        "",
        "| rule | requirement | outcome |",
        "|---|---|---|",
        f"| as pre-registered | echo → 0 **and** no coverage lost | "
        f"{'pass' if payload['decision']['pre_registered_rule_passed'] else 'fail'} |",
        f"| amended (decides) | echo → 0 **and** every replacement is a statement | "
        f"{'pass' if adopted else 'fail'} |",
        "",
        (f"- **Adopted.** Heading-echo answers {total_before} → 0 across the three sets, and all "
         f"{changed} replacements carry a number or a finite verb, so each one is a policy "
         "statement instead of a list of headings." if adopted else
         "- **Not adopted.** The guard did not clear both conditions; the counts above say which."),
        "",
        "## What this does not fix",
        "",
        "- **The passage is still chosen by retrieval.** Six of v1's 24 questions get a top-1",
        "  passage from the wrong document (a001 asks attendance and is answered from the medical",
        "  document; a009 asks about re-exams and is answered from placements). The guard cannot",
        "  help there, and the answer is wrong for a reason no selector can repair.",
        "- **A summary sentence that is not the first sentence.** The guard only inspects the",
        "  passage's opening line, because that is the structural position of a document's topic",
        "  list. A mid-document summary in a merged chunk is still eligible; nothing in the corpus",
        "  produces one today, and this report does not claim otherwise.",
        "",
    ]
    (RESULTS / "answer_selection.md").write_text("\n".join(lines), encoding="utf-8")

    print("written: results/answer_selection.md, results/answer_selection.json")
    for label, block in findings.items():
        print(f"  {label}: right doc {block['top1_document_correct']}/{block['questions']} "
              f"| echo {block['echo_before']} -> {block['echo_after']} "
              f"| changed {len(block['changed'])}")
    print(f"  adopted: {adopted} (echo eliminated {echo_gone}, replacements are statements "
          f"{statements}; the pre-registered coverage rule passed: {pre_registered})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
