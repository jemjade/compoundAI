# v1.2 QA evidence/output-contract diagnostic — run 003

Status: `COMPLETE DEVELOPMENT DIAGNOSTIC`; policy comparison remains `NOT_READY`.

The live run used commit `f770db02f56e21dcaedd11ae897bb4a7f978b463`. It made 12 local
QA calls in six fresh pipeline executions. The final deterministic adjudication is v1.2.2 at
commit `23d349b`; the two earlier evaluator outputs are retained because their negation parsing
was corrected after the run. No model condition was rerun.

## Model and raw preservation

- Ollama `0.30.6`, `llama3:latest`, digest
  `365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1`, 8.0B Q4_0.
- Temperature 0, context 8192, passthrough synthesis, full p55 forced oracle evidence.
- Six executions × two questions = 12 calls; preflight maximum output was 7,200 tokens.
- Persistent raw directory:
  `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/preserved-dependency-aware-pilot-v1_2-qa-contract-run-003`
- The directory contains the six full payloads, six full responses and traces, both evidence
  representations, frozen spec/config/case, original and corrected evaluations, manifests, and
  checksums: 20 files, 18,200,333 bytes. `preservation_manifest.json` SHA-256 is
  `db336316da7524dc101543868f9a78934b67238c085635adbf0f345bf6ff89ff`.

## Old strict score versus separated evaluation

The v1.1 strict evaluator and report are unchanged. It required the gross reference conclusion,
all four dollar/percentage values, unit cues, and evidence. Every A-D gross and tax answer was
false overall; D gross had correct evidence but failed answer accuracy because it stated only the
correct direction.

Applying the new dimensions to all v1.1 conditions is explicitly post-hoc exploratory:

| v1.1 condition | Gross conclusion | Stated numbers | Required explanation | Evidence |
|---|---|---|---|---|
| A damaged/general | missing | no numbers stated | incomplete | insufficient |
| B repaired/general | missing | no numbers stated | incomplete | insufficient |
| C damaged/oracle | missing | no numbers stated | incomplete | insufficient |
| D repaired/oracle | **correct** | no numbers stated, not “wrong numbers” | incomplete | sufficient |

The new evaluator does not require every FinanceBench reference number. A valid explanation can
show both periods' margins and their calculation basis without repeating both subtotal dollar
amounts. It still requires enough two-period numbers and calculation detail to explain the
comparison.

## New six-condition gross result

| Evidence / instruction / state | Conclusion | Stated numbers | Explanation | Evidence | Overall |
|---|---|---|---|---|---|
| flat / old / damaged | correct | none | incomplete | insufficient | fail |
| flat / old / repaired | incorrect (“not improving”) | none | incomplete | sufficient | fail |
| flat / quantitative / damaged | incorrect | incorrect | incomplete | insufficient | fail |
| flat / quantitative / repaired | correct | incorrect | incomplete | sufficient | fail |
| table / quantitative / damaged | correct | incorrect | incomplete | insufficient | fail |
| table / quantitative / repaired | correct | incorrect | incomplete | sufficient | fail |

The explicit output contract caused the model to emit values and calculations, but did not yield a
complete correct explanation. In repaired flat text it concluded “improving” but produced the
incorrect expression/result `... = 0.144` and omitted the FY2021 margin comparison. In repaired
table text it correctly repeated the unlabeled subtotals `3,502`/`3,017`, then incorrectly computed
product-only differences `12,639`/`12,332` and again omitted the two gross-margin percentages.

The table representation changed the damaged-state conclusion from incorrect to correct, but that
answer hallucinated clean `66,608` although the saved damaged table contains `6,608`, and computed
an incomplete product-only subtotal. In the repaired state, table structure changed none of the
four evaluated dimensions. Thus neither output instructions nor the human-authored table solved
the QA reasoning failure in this run.

Because each cell is one independent local-model execution, changed conclusions can include run
variation. The result is a diagnostic observation, not a causal estimate of prompt or
representation quality.

## Intervention validity

The directly rendered p55 source has title, USD-million unit, and 2022/2021/2020 columns, but the
`3,502`/`3,017` subtotal row is unlabeled in the PDF itself. The structured representation retains
that blank label. Calling it `gross profit` is evaluation-side interpretation, not recovered
parser text.

For FY2021, `3,017 / 62,286 = 4.8438%`. Under the four FY2022 source states:

| State | `(revenue-cost)/revenue` | `3,502/revenue` | Direction |
|---|---:|---:|---|
| damaged | 7.5969% | 52.9964% | improving on both routes, numerically wrong |
| A only | 90.8329% | 5.2576% | improving; inconsistent costs remain |
| B only | -854.9939% | 52.9964% | routes conflict |
| A+B | 5.2576% | 5.2576% | improving and consistent |

A repairs the exact p55 denominator. B repairs revenue-minus-cost consistency, but is optional for
the subtotal/revenue route. Page 28's cost shares independently imply 5.3%/4.8%, and identical
values remain elsewhere. Neither A nor B affects the tax rows. This case therefore remains useful
for execution, output-contract, oracle-representation, consistency, and negative-control checks,
but not for combination-effect or policy-superiority evidence.

## Tax conflict

The old prompt returned insufficient evidence in both states. Each quantitative run produced a
calculation, but none matched either complete signed reference pair. FinanceBench keeps
`+0.62%`/`-14.76%`; Boeing directly reports `-0.6%`/`+14.8%` on p24 and
`-0.6%`/`+14.7%` on p77. The model often mixed conventions (for example positive 0.62% with
positive 14.7%) or used 14.6%. Unconditional tax correctness and repair claims remain withheld.

## Policy-comparison gate

Passing one repaired oracle-evidence cell would not open the gate. A future comparison must use a
common frozen candidate universe that contains real errors, policy-visible non-gold features that
distinguish some errors from normal candidates, multiple downstream dependency structures,
repairs capable of changing a frozen final metric, and identical information/cost/budget rules.
Equal Individual/Graph selections and candidate/retrieval failures must remain in the final data.

The most important next work is to freeze independent cases satisfying those conditions. The
current Boeing example should not be tuned further and then relabeled as independent evaluation.
