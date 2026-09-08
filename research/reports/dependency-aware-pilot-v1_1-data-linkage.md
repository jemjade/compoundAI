# v1.1 development data linkage audit

Status: `VERIFIED` for the frozen local source bytes and arithmetic; development evidence only.

This audit was written before the v1.1 live diagnostic. Values below are researcher-side
evaluation facts, not model outputs and not policy-visible features.

## Question, evidence, and repair correspondence

| Question | Required source facts | Calculation / judgment | A effect | B effect |
|---|---|---|---|---|
| `financebench_id_00678`, gross margin | p55, USD millions, FY2022/FY2021: revenues 66,608/62,286; total costs 63,106/59,269; gross profit 3,502/3,017 | 3,502 / 66,608 = 5.2576% → 5.3%; 3,017 / 62,286 = 4.8438% → 4.8%; improving | Directly corrupts the FY2022 revenue denominator at `[279,284)` | Corrupts the FY2022 total-cost input to the revenue-minus-cost derivation; the explicit 3,502 row remains |
| `financebench_id_00585`, effective tax rate | p55, FY2022/FY2021 loss before tax `(5,022)/(5,033)` and income tax expense/benefit `(31)/743` | FinanceBench reference arithmetic yields +0.6173% and -14.7626%; see sign conflict below | None | None |

Both repairs are in `BOEING_2022_10K:p55`, PDF page 55, printed page 53. The table header
states “Dollars in millions, except per share data” and orders columns 2022, 2021, 2020. A maps
corrupted `6,608` to `66,608`. B maps corrupted parenthesized `(6,106)` to `(63,106)`; the repair
span excludes and preserves the parentheses. Repairs are applied from the later span backwards so
A's one-character length change cannot shift B's frozen source coordinate.

## Alternate exact values retained

The clean exact revenue token `66,608` occurs six times: p55 plus p24 twice, p49, p62, and p114.
After corruption, all five non-p55 occurrences remain. The clean exact cost token `63,106` occurs
on p55 and p28; p28 remains after corruption. No alternate was removed to manufacture an effect.
Counts use exact numeric tokens, not substring matching (`6,608` is a substring of `66,608`).

p28 directly reports cost of sales as 94.7% of revenue in FY2022 and 95.2% in FY2021, which can
independently support gross margins of 5.3% and 4.8%. Therefore general retrieval must be judged by
whether it surfaces any sufficient evidence, not by p55 membership alone.

## Tax reference conflict

The frozen FinanceBench answer says FY2022 `+0.62%` versus FY2021 `-14.76%`, derived from the p55
presentation signs. The filing directly reports effective income tax rate as FY2022 `(0.6)%` and
FY2021 `14.8%` on p24, and `(0.6)%`/`14.7%` on p77. The signs are opposite. Consequently v1.1
reports FinanceBench-reference accuracy separately from document-reported accuracy and does not
use this question for an unqualified recovery claim. Resolving the benchmark label is outside the
selection policy and must not be hidden by changing model evidence.

## Oracle-evidence segment integrity requirement

Conditions C and D pass the entire p55 passthrough block, not a hand-cut row. The corrupted block
is 1,287 characters and the repaired block 1,289 characters, both below the unchanged 3,000-
character chunk size. The saved QA input must contain the table title, units, year header, revenue,
cost, unlabeled gross-profit, loss-before-tax, and income-tax rows. It contains no separately
provided answer or formula.

## Evaluator sanity fixtures

Written correct examples will cite p55 and include every frozen FinanceBench reference number and
direction; written incorrect examples will omit a required value or supporting evidence. These are
tagged `AUTHORED_EVALUATOR_FIXTURE`. Passing those fixtures validates evaluator mechanics only—it
is not a model result and does not validate the disputed tax label.
