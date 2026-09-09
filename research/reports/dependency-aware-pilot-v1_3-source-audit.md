# v1.3 development source and question audit

Status: frozen before live model execution. All documents and questions below are development and
exploratory material. They are not eligible for independent final evaluation.

## Selection

The development set uses seven existing FinanceBench questions from three non-Boeing filings:

| Document | Question ID | Task | PDF evidence | Audited answer basis |
|---|---|---|---|---|
| AMCOR 2023 10-K | `financebench_id_00799` | calculation/comparison | p52 | quick ratio rose from 0.6690 to 0.6915 (about 3.36% relative) |
| AMCOR 2023 10-K | `financebench_id_00684` | calculation/comparison | p50 | gross margin fell from 19.389% to 18.545% (0.844 percentage points) |
| Best Buy 2023 10-K | `financebench_id_00685` | calculation/three-year consistency | p40 | 22.371%, 22.488%, 21.409%; adjacent changes remain below roughly 2 percentage points |
| Best Buy 2023 10-K | `financebench_id_01275` | extraction/signed comparison | p42 | operating +$1,824m exceeds investing -$962m and financing -$1,806m |
| AMD 2022 10-K | `financebench_id_00222` | calculation/threshold judgment | p56 | quick ratio `(4,835+1,020+4,126+2)/6,369=1.5674` |
| AMD 2022 10-K | `financebench_id_00563` | calculation/multi-option comparison | p48 | Data Center +63.59%, Gaming +21.37%, Client -9.96% |
| AMD 2022 10-K | `financebench_id_00757` | direct extraction | p12 | one customer accounted for 16% of FY2022 consolidated net revenue |

All cited pages were rendered at 2× and visually inspected against the PDFs. Row labels, period
columns, units, parentheses/signs, and totals were checked. The pipeline input remains pypdf page
text; visual inspection is evaluation-side validation and does not turn that extraction into a
layout-aware parser.

## Benchmark/task alignment findings

- AMCOR's reference says a 0.8% decline. The filing-derived difference is about 0.844
  **percentage points**. The conclusion is aligned; the evaluator accepts equivalent, correctly
  labeled calculations rather than requiring the exact reference wording.
- Best Buy asks about historical annual consistency, but its reference explanation mentions only
  FY2022–FY2023. The filing supplies three years and supports the conclusion. The item is retained
  to expose the mismatch, but unconditional overall correctness is excluded from the primary
  denominator until the necessary explanation scope is adjudicated.
- AMD's 1.57 ratio is source-derived. Calling it “reasonably healthy” uses FinanceBench's
  greater-than-one convention; that normative threshold is not directly stated in AMD's filing.
- The other four reference answers agree with the visually checked filing evidence.

No conflict is silently counted as model error. No answer, reference value, source page, repair
location, or downstream effect in this audit is available to the QA model beyond evidence it
retrieves/receives, and none is available to a selection policy.

## Predeclared repair case

The AMD quick-ratio page receives two controlled post-extraction digit deletions: FY2022 cash
`4,835→835` (A) and accounts receivable `4,126→126` (B). The direct-input ratios are 0.3114 when
both are damaged, 0.9394 after either single repair, and 1.5674 after both. Under the benchmark's
greater-than-one convention, only A+B changes the direct-route conclusion.

This page also preserves an alternate calculation:
`(total current assets 15,019 - inventories 3,771 - prepaid 1,265) / 6,369 = 1.5674`.
It is not removed. If the model uses it, damage may have no effect and the run must retain that
failure-to-induce. The case is intentional and controlled, not a natural parser-error example or
an estimate of error frequency.
