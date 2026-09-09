# Dependency-aware v1.1 candidate/evidence diagnostic — run 002

Status: `IMPLEMENTED` development diagnostic; larger policy comparison stopped by the frozen D
condition rule. Research superiority claims remain `PROPOSED`.

## Preserved execution

- Spec frozen before execution: `research/specs/experiment_spec_v1_1.json`, commit `347c1b3`
- Executed code: commit `69c41756220e6ffc428f5422da899bb9483d2eb5`
- State-aware adjudication: commit `beb3f64`
- Run ID: `4a403b86-1095-43f2-91d4-d877f3764186`
- Raw directory: `research/work/preserved-dependency-aware-pilot-v1_1-diagnostic-run-002`
- Raw preservation inventory: `preservation_manifest_v2.json`, SHA-256
  `01760acb55a1aba46b06fa0c048c5550fe3e186f66d464997bedf8612776627e`
- First attempted directory `...run-001` is retained with a zero-call failure manifest. A parent-run
  provenance loading error stopped it before any model call; no output was overwritten or deleted.

The successful run contains the frozen input/spec/config, full-document candidates, actual and
estimated graph edges, selections, candidate diagnostics, all model inputs/raw outputs/prompts/
retrieval traces, model identity, blind judgments, original evaluation, and versioned state-aware
adjudication. All are Git-ignored raw artifacts, not replaced by this tracked summary.

## Model and resource boundary

The run used the same `llama3:latest` model and generation settings as v1: digest
`365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1`, 8.0B Q4_0,
Ollama 0.30.6, temperature 0, context 8192, passthrough synthesis, chunk size 3000/overlap 300,
and BM25 top-k 4 for general retrieval. Four fresh pipeline IDs completed eight QA calls, using
14,976 input and 704 output tokens. No external paid API was used.

## Data linkage verified before the run

Both repairs are on `BOEING_2022_10K:p55`, PDF page 55 / printed page 53, in a USD-millions table
whose columns are FY2022, FY2021, FY2020.

| Repair | Frozen corrupted span | Restored value | Direct question effect | Unaffected question |
|---|---|---|---|---|
| A | `[279,284)` = `6,608` | FY2022 total revenues `66,608` | Gross-margin denominator | Effective tax rate |
| B | `[458,463)` = `6,106`, inside parentheses | FY2022 total costs `(63,106)` | Gross-profit derivation/cross-check; explicit `3,502` row remains | Effective tax rate |

Exact `66,608` remains elsewhere on p24 twice, p49, p62, and p114; exact `63,106` remains on p28.
No alternate was removed. p28 independently reports cost of sales as 94.7%/95.2% of revenue and
can support 5.3%/4.8% gross margins.

The FinanceBench tax answer says +0.62%/-14.76%, while p24 and p77 directly report -0.6% and
+14.8/+14.7%. This sign conflict is reported under two answer standards and the tax item is not
used for an unqualified recovery claim.

## Four actual diagnostic conditions

Strict answer correctness requires the material values, fiscal years, signs/units, and conclusion.
Evidence correctness below means a cited block is sufficient for that source state; damaged p55 is
not treated as sufficient gross-margin evidence merely because its ID matches the gold block.

| Condition | Gross answer | Gross A/E/O | Tax answer | Tax A/E/O (FinanceBench) |
|---|---|---|---|---|
| A: damaged + general | `Insufficient evidence` | 0/0/0 | `Insufficient evidence` | 0/0/0 |
| B: repaired + general | `Insufficient evidence to determine...` | 0/0/0 | `Insufficient evidence` | 0/0/0 |
| C: damaged + oracle p55 | `The evidence is insufficient...` | 0/0/0 | `The evidence is insufficient...` | 0/1/0 |
| D: repaired + oracle p55 | `Yes, Boeing has an improving gross margin profile as of FY2022.` | 0/1/0 | `The evidence is insufficient...` | 0/1/0 |

`A/E/O` means answer correct / evidence sufficient / both. D's gross direction is correct, but the
answer omits 3,017, 3,502, 4.8%, 5.3%, and the FY2021 comparison, so it fails the pre-frozen answer
rule. Under the filing-reported tax standard, A retrieved and cited p77, so its tax evidence is
sufficient but its answer remains wrong; B retrieved p77 but cited nothing. C/D tax evidence is
sufficient for performing the p55 arithmetic, but the model did not do it.

## Failure localization

1. **Candidate inclusion passes.** Whole-document enumeration produced 6,777 numeric spans and
   included both controlled errors: 2/2, 100% conditional candidate recall. The accounting-parentheses
   span bug found in the pre-run dry check was fixed and regression-tested before model execution.
2. **Candidate selection remains non-functional for these errors.** A and B have observed reach 0
   because p55 was outside the parent baseline/no-op top-k traces. They share the same feature tuple
   with 6,451 normal candidates. None of the eight budgeted diagnostic selections chose A or B.
3. **General gross retrieval fails.** Neither A nor B returned p28 or a state-sufficient p55. Repairs
   therefore cannot affect general QA even though correct duplicates remain elsewhere.
4. **General tax retrieval is not the only failure.** p77 was retrieved in A and B and is sufficient
   for the filing-reported tax comparison, but the model still answered insufficient. It is not
   sufficient for the conflicting FinanceBench signs.
5. **Oracle transport and truncation pass.** C received one complete 1,287-character damaged p55
   chunk; D received one complete 1,289-character repaired chunk. Both retained title, units, year
   headers, material rows, and expected source values. No answer fields were provided.
6. **Representation/QA remains the priority failure.** The flattened pypdf text loses the label for
   the `3,502 3,017 (5,685)` gross-profit row. D nevertheless recognized the improving direction,
   but it did not expose the required arithmetic. Tax required cross-row arithmetic and remained
   unanswered. One run cannot fully separate flattened-table semantics from model reasoning/output
   compliance.
7. **Evaluator mechanics pass, benchmark semantics do not.** Four explicitly tagged authored
   fixtures—two reference conventions, one correct gross answer, and one incorrect answer—were
   classified as intended. They are not model outputs. The tax sign conflict still needs human
   adjudication.

The D gross failure triggers the pre-frozen stop rule, so no larger policy comparison was started.

## Score distinguishability

- Unique feature tuples: 5 across 6,777 candidates
- Unique policy-score tuples: 4
- Candidates belonging to a non-singleton score tie: 6,777 / 6,777 (100%)
- Candidate-ID tie-break decisions: 9 / 9 scored-policy choices; Random uses its seeded permutation
- Individual impact vs Graph-aware: identical sets at budgets 1 and 2; Jaccard 1.0, symmetric
  difference 0
- Observed reach zero: 6,454 / 6,777 (95.23%)
- Reach zero but positive lexical-estimated relevance: 6,453
- Both errors receive estimated lexical edges to both questions, even though neither affects the tax
  question. This confirms that the current positive-BM25 estimate is too coarse to distinguish
  question-specific causal relevance and is correctly excluded from selection.

The baseline/no-op instability proxy is not an error probability. Candidates with the same observed
question descendants receive the same proxy. `ideal_repair_given_detection=1` means only that a
detected controlled error receives its exact evaluation correction; it does not estimate downstream
recovery.

## Claim boundary and next gate

This run verifies full-document candidate inclusion, separate actual/estimated edges, oracle-evidence
routing, state-aware evidence checks, and failure localization. It does not verify policy benefit,
conditional recovery, actual deployment performance, natural errors, multimodality, model synthesis,
multi-stage allocation, output-only comparison, or statistical uncertainty.

The next single task is to make the QA evidence representation/output contract explicitly preserve
table row labels, columns, units, and required calculations while holding the model and evidence
route fixed. It must pass D on the non-conflicted gross question before policy comparisons resume.
