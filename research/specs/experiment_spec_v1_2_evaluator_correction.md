# v1.2 evaluator correction: adjudication v1.2.1

The 12-call live run completed before this correction. No model input, prompt, evidence
representation, output, or condition is changed or rerun.

The first `separated-qa-evidence-contract-v1.2` evaluation had three deterministic parsing bugs:

1. It checked the substring `improv` before the phrase `not improving`, so a negative conclusion
   could be labeled correct.
2. It interpreted parenthesized years such as `(2022)` as negative numeric claims.
3. It interpreted the `10` in `10-K` as a quantitative claim and did not allow correctly copied
   product/service component values.

The original evaluation files remain in the raw run root. Adjudication v1.2.1 fixes only those
predefined dimension mechanics, adds regression tests, and writes to a new append-only
`adjudication-v1_2_1/` directory. This correction is disclosed because it was made after observing
the first evaluation output. The raw live outputs are unchanged and no favorable cases are added,
removed, or rerun.
