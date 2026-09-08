# v1.3 multi-document development feasibility result

Status: implementation and local diagnostic complete; research/policy claim not validated.

## Scope and execution

The frozen development set contains seven FinanceBench questions from AMCOR 2023, Best Buy
2023, and AMD 2022. Five require numerical calculation or a quantitative comparison; two are
direct extraction/signed-selection questions. All seven source pages were rendered and checked
against the filings before execution. These documents are development material and cannot become
independent final evaluation.

The only installed completion model was local `llama3:latest`, immutable digest
`365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1` (8.0B, Q4_0) on
Ollama 0.30.6. The installed `nomic-embed-text` is embedding-only and was not misrepresented as a
second QA model. The fixed pipeline used passthrough, document-isolated BM25 top-k 6,
`quantitative_v2`, temperature 0, context 8192, and 700 maximum output tokens. Run-005 completed
14 fresh pipeline executions and 18 model calls with no paid external calls.

## Clean QA result

| Condition | Conclusion correct | Numeric claims | Required explanation | Valid evidence | Overall task correct |
|---|---:|---|---|---:|---:|
| General BM25 | 3/7 | 2 correct, 0 wrong, 5 omitted | 2 complete, 1 direct/not needed, 4 missing | 2/7 | 2/7 (2/6 primary) |
| Oracle full page | 3/7 | 2 correct, 4 wrong, 1 omitted | 1 complete, 1 direct/not needed, 5 present but invalid | 7/7 available; 2/7 supported output | 2/7 (2/6 primary) |

General BM25 retrieved a valid required source for only Best Buy cash flow and AMD segment sales.
Those were the only two fully correct general answers. The Best Buy gross-margin conclusion also
happened to be correct, but it had neither the relevant page nor a quantitative explanation, so it
is not an evidence-grounded success.

Oracle evidence improved nonempty contract-field completion from 1/7 to 5/7, but did not improve
overall correctness. The model miscomputed AMCOR quick ratio, contradicted its own declining
AMCOR margin sequence, used false displayed formulas for Best Buy margins, chose investing despite
the correct signed cash-flow totals, and reported an invalid AMD quick-ratio formula/value. Exact
evidence access is therefore necessary but not sufficient for this pipeline.

Best Buy's “historically consistent” item is retained, but excluded from the six-item primary
denominator: the question calls for annual history while its released reference explanation only
describes FY2022–FY2023. AMD's “reasonably healthy” label is also explicitly benchmark-normative;
the filing supplies the inputs but does not define that threshold.

## Controlled repair result

AMD p56 received `4,835→835` (A) and `4,126→126` (B). The frozen direct-route quick ratios are
0.3114 damaged, 0.9394 after either individual repair, and 1.5674 after A+B. The unchanged page
also permits `(15,019-3,771-1,265)/6,369=1.5674`; this alternate route was retained.

| State | Conclusion | Numeric explanation | Full task result |
|---|---|---|---|
| separate clean oracle | healthy/correct | wrong 0.93 and wrong inputs/arithmetic | incorrect |
| damaged | healthy/correct | current ratio mislabeled quick ratio; 2.38 also arithmetically off | incorrect |
| A only | healthy/correct | substituted sum and claimed 0.83 disagree | incorrect |
| B only | healthy/correct | current ratio mislabeled quick ratio | incorrect |
| A+B | healthy/correct | ratio and calculation omitted | incorrect |

No state produced a correct quantitative answer, so A, B, and A+B recovered zero full answers.
The stable qualitative conclusion is not counted as human verification or repair success. The
case remains useful as a controlled negative result showing alternate-path bypass and QA
non-recovery, not as natural-error or interaction evidence.

## Observable feature and policy-behavior probe

The damaged full documents yielded 11,870 numeric candidates, including both injected errors.
Actual policy-visible observations were: pypdf/PyMuPDF per-page normalized numeric-token count
disagreement, PyMuPDF word geometry for matched values, and a human-configured AMD balance-sheet
component identity residual. The injected values each had disagreement 1, residual 0.5327, and
anomaly score 0.8598, but BM25 assigned their page no question descendant, so reach and individual
impact were zero.

Only 8 feature vectors and 3 Individual-impact scores existed for 11,870 candidates; every
candidate tied with at least one other. Both policies used ID tie-breaking for both budget-2
choices. They selected different sets but neither selected A/B. Individual chose two AMCOR p86
values; Graph-aware chose the shared first AMCOR candidate and then an AMD p102 value linked to a
different question. This confirms marginal-overlap logic changes set behavior, not performance.

The selected disagreements reveal low specificity: they came from tokenizer boundaries such as
`12-month`, `€300`, and `Exhibit 10.16(a)`, not verified parser errors. The secondary parser also
reads the clean PDF while errors are injected after primary extraction. Thus the feature path is
real and non-gold, but its natural-error discrimination is not established.

## Failure preservation and independent evaluation

Run-004 failed on its first local response because an empty explanation was rejected before raw
serialization. The failed directory and a correction manifest are retained; that one response is
irrecoverable and explicitly not claimed preserved. The parser now retains blank string fields as
contract violations instead of turning them into success or discarding the response. Cumulative
attempted calls were 19: one failed run-004 call and 18 completed run-005 calls.

Run-005 raw inputs, prompts, retrievals, outputs, configuration, model inventory, judgments,
policy inputs/selections, and checksums are preserved under
`research/work/dependency-aware-pilot-v1_3-development-run-005`. Its preservation manifest covers
13 files and 47,497,716 bytes; SHA-256 is
`935dc06a73d19eabd24fe4e5c87be5f01e863e5ef72ca726049ff91f825c18bf`. There is no independently
verified second physical backup.

The independent protocol is frozen before performance execution. It deterministically selected
Pfizer 2021, PepsiCo 2022, and AES 2022, three questions each, and fixed error generation,
unit-cost budgets 3/6, policies, and overall/conditional reporting. Its 903-block source snapshot
is prepared, but the evaluation is not ready to run: all nine source/reference pairs still need
audit, injection/candidate manifests must be frozen, and the observed dependency graph must have
nonzero varied structure. No independent QA or policy score has been observed.

## Decision

The largest blocker is base QA rather than candidate enumeration: with the exact sufficient page,
only 2/7 answers are fully correct. The next single task should be a separately versioned,
deterministic table-value/arithmetic operator for the new development documents, followed by the
same frozen clean-oracle checks. Further Boeing prompt/model tuning remains closed.

The broader abstract remains incomplete: two PDF text extractors here are not diverse production
parser outputs; VLM/image/layout evaluation, natural parser errors, model synthesis, multi-stage
budget allocation, fair cost-matched output-only comparison, completed independent-document
evaluation, a provenance-aware verification interface, and paper-scale results/uncertainty/limits
analysis have not been completed.
