# v1.2 intervention-validity and source-structure audit

Status: `FROZEN BEFORE LIVE RUN`; researcher-side development analysis only.

This document records evaluation facts used to interpret the v1.2 diagnostic. None of the
calculations, correct values, repair labels, condition names, or expected conclusions below are
available to a selection policy or included in a model prompt.

## Direct PDF inspection

The source is `BOEING_2022_10K.pdf`, SHA-256
`09285ff7ee737d3302977104aa05cc53c9dfb0161f3461a89b583dc38b9f2ab6`. PDF pages 24, 28,
55, and 77 were rendered at 2× and inspected directly before the v1.2 live run.

PDF page 55 (printed page 53) is titled “The Boeing Company and Subsidiaries — Consolidated
Statements of Operations.” It states “Dollars in millions, except per share data” and has columns
2022, 2021, and 2020. The source PDF itself leaves the row containing `3,502`, `3,017`, and
`(5,685)` blank. It is therefore incorrect to say that pypdf lost a source `gross profit` label.
Treating this unlabeled subtotal as revenue minus total costs is an evaluation-side interpretation.
The human-authored structured representation keeps the label blank and is an oracle
representation diagnostic, not an automatic parser or VLM result.

PDF page 28 (printed page 26) directly labels `Cost of sales` as `63,106`/`59,269` and `Cost of
sales as a % of Revenues` as `94.7%`/`95.2%` for 2022/2021. PDF pages 24 and 77 directly report
effective income tax rates with the filing's sign convention; see Tax conflict below.

## Four source states before model calls

FY2021 is unchanged: revenue `62,286`, total costs `59,269`, subtotal `3,017`, and margin
`3,017 / 62,286 = 4.843785%` (4.8%). The table separates two FY2022 calculation routes:

- Implied subtotal route: `(revenue - total costs) / revenue`.
- Unlabeled reported-subtotal route: `3,502 / revenue`.

| State | FY2022 revenue | FY2022 costs | Implied subtotal | Implied margin | 3,502/revenue | Direction vs 2021 |
|---|---:|---:|---:|---:|---:|---|
| damaged | 6,608 | 6,106 | 502 | 7.5969% | 52.9964% | improving on both routes, but numerically wrong |
| A only | 66,608 | 6,106 | 60,502 | 90.8329% | 5.2576% | improving on both routes; cost consistency remains broken |
| B only | 6,608 | 63,106 | -56,498 | -854.9939% | 52.9964% | routes conflict; denominator remains broken |
| A+B | 66,608 | 63,106 | 3,502 | 5.2576% | 5.2576% | improving and internally consistent |

Thus A+B is not required to preserve the binary “improving” conclusion. A is needed for the
correct p55 FY2022 margin denominator; B is needed for revenue-minus-cost consistency, but not
for a route that uses the unlabeled subtotal. Neither repair affects FY2022/FY2021 tax inputs.

## Alternate evidence and necessity

No alternate evidence is removed. Exact `66,608` remains on p24 (twice), p49, p62, and p114;
exact `63,106` remains on p28. Page 28's 94.7% and 95.2% cost shares independently imply 5.3%
and 4.8% gross margins. Consequently:

- A is necessary only for an exact p55-based denominator, not for every valid full-document path.
- B is an optional consistency repair for answers using the p55 subtotal/revenue route.
- The case is useful for execution, output-contract, evidence-representation, and non-effect
  diagnostics, but unsuitable for a general interaction or policy-superiority claim.

## Tax conflict

FinanceBench preserves `+0.62%` for FY2022 and `-14.76%` for FY2021, derived from the p55
amounts. Boeing directly reports `(0.6)%`/`14.8%` on p24 and `(0.6)%`/`14.7%` on p77.
Parentheses denote negative rates/amounts. Both references are retained and scored separately;
the tax item cannot support an unconditional recovery claim before its answer convention is
adjudicated. Since A/B touch only revenue/cost values, they have no direct tax effect.

## Frozen comparison and claim boundary

The live comparison is fixed at six fresh executions (two questions each, 12 local model calls):
flat text + old prompt, flat text + quantitative prompt, and human-verified table + the same
quantitative prompt, each in damaged and A+B states. Every run receives the full p55 oracle
evidence. No prompt is added after results are seen. The result can diagnose an output-contract
or representation effect under this controlled setup; it cannot validate retrieval, automatic
table parsing, selection allocation, or general policy performance.
