# FR-11 diagnosis: hybrid vs sparse, query by query (M4)

Command: `python -m eval.fr11` · commit `54ffd79`

Hybrid loses on **9 of 24** answerable queries; wins on 3, ties on 12.

## Losing queries (the stage-2 targets)

| id | sparse recall/mrr | hybrid recall/mrr | sparse top-3 | hybrid top-3 | note |
|---|---|---|---|---|---|
| a001 | 1.00/0.33 | 0.00/0.00 | medical-and-counseling, scholarship-merit, attendance-policy | medical-and-counseling, examination-rules, scholarship-need-based | multi_fact: 75% bar + medical condonation |
| a002 | 1.00/1.00 | 1.00/0.20 | attendance-policy, scholarship-merit, course-withdrawal | medical-and-counseling, grading-system, course-withdrawal | kw_mismatch: percentage in words; detention |
| a010 | 1.00/1.00 | 1.00/0.50 | supplementary-exams, examination-rules, backlog-and-attempts | examination-rules, supplementary-exams, backlog-and-attempts | multi_fact: Rs 1,000 + max 2 |
| a012 | 1.00/1.00 | 1.00/0.33 | branch-transfer, scholarship-need-based, code-of-conduct-discipline | backlog-and-attempts, code-of-conduct-discipline, branch-transfer | 7.5 CGPA, end of first year |
| a017 | 1.00/1.00 | 1.00/0.50 | placement-policy, attendance-policy, examination-rules | attendance-policy, placement-policy, hostel-rules | kw_mismatch: dream offer rule 1.5x |
| a019 | 1.00/1.00 | 1.00/0.50 | minor-and-honors, grading-system, branch-transfer | grading-system, minor-and-honors, supplementary-exams | kw_mismatch: marks-credits; 18 credits |
| a020 | 1.00/0.50 | 1.00/0.33 | backlog-and-attempts, grading-system, supplementary-exams | backlog-and-attempts, supplementary-exams, grading-system | AA=10, DD=4 pass |
| a021 | 1.00/0.11 | 0.00/0.00 | admission-policy, branch-transfer, supplementary-exams | branch-transfer, placement-policy, library-rules | paraphrase: re-verify vs revaluation; Rs 800, 10 days |
| a024 | 1.00/0.33 | 0.00/0.00 | library-rules, attendance-policy, medical-and-counseling | attendance-policy, admission-policy, examination-rules | kw_mismatch: counsellor vs counselling centre; Tue/Fri 2-5 PM |

Reading: where hybrid loses, the relevant doc is usually pushed below rank 10 by
fused noise from the hashed-TF-IDF list or out-scored by the coverage feature on a
longer neighbor chunk. The M3 ablation (k=10/60/100) already showed fusion alone
cannot fix this - the fix is a meaningful dense vote (stage 2 embeddings) and a
trained reranker that resists partial-coverage neighbors.
