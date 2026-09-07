# Experiment Plan

Status: `PROPOSED`

Depends on: `docs/RESEARCH_SPEC.md`

## 1. Experimental unit

The primary independent unit is a **source document**. Each document is evaluated
under multiple parser/configuration conditions. Repeated downstream generations are
nested observations used to estimate model variability; they are not additional
independent documents.

Recommended identifiers:

```text
dataset_version / document_id / parser_id / parser_config_hash /
task_version / model_version / generation_index / git_sha
```

## 2. Conditions

### Parser conditions

Use only parsers that can be run reproducibly during the study. Record exact version,
deployment mode, configuration, and any preprocessing. The repository currently has
adapters for Synap, Docling, MinerU, PaddleOCR, generic HTTP/command parsers, and mocks;
availability is an environment question, not an assumption.

### Document strata

Sample documents across structures that can plausibly alter analysis:

- prose-dominant;
- table-dominant;
- multi-column or complex layout;
- formula-bearing;
- mixed Korean/English or OCR-sensitive scans, if in scope.

Document type is a planned moderator, not merely a descriptive tag.

### Downstream tasks

Freeze a small task suite with objectively checkable outputs:

1. **Fact extraction:** recover named values and their source locations.
2. **Comparison:** compare two or more entities/periods using tabular evidence.
3. **Analytical conclusion:** answer a decision question and provide evidence-linked
   claims.

Avoid adding many loosely specified tasks. A small, audited suite is preferable.

## 3. Variables and outcomes

### Existing parser-local predictors (`IMPLEMENTED`)

- Text: `text_cer`, `text_accuracy`, `text_exact_match`.
- Layout: `layout_f1_iou50`, `layout_mean_iou`.
- Tables: `table_teds`, `table_teds_structure`, `table_structure_f1`,
  `table_content_accuracy`.
- Order/formula: `reading_order_accuracy`, `reading_order_coverage`,
  `formula_accuracy`, `formula_exact_match`.
- Operational: latency p50/p95, pages per minute, result size.
- Composite: `overall_quality` as an existing descriptive baseline, not ground truth
  for downstream consequence.

### Downstream primary outcomes (`PROPOSED`)

Choose and freeze no more than two primary outcomes after the pilot:

- **Task correctness:** exact or rubric-based correctness against an audited answer.
- **Conclusion shift:** whether the parser condition changes the task-level decision
  or categorical conclusion relative to the audited reference condition.

### Secondary outcomes (`PROPOSED`)

- numeric value error;
- claim precision/recall;
- evidence/source attribution correctness;
- unsupported claim rate;
- semantic dispersion across repeated generations;
- abstention or refusal rate;
- latency and estimated compute/verification cost.

Do not collapse these into one score until component behavior and weighting are
reported. Any composite consequence score must receive a sensitivity analysis.

## 4. Baselines

Evaluate against cost-matched, implementable alternatives:

- one globally selected parser (`single best parser`);
- fastest available parser;
- highest parser-local `overall_quality`;
- threshold on `overall_quality`;
- random verification at the same budget;
- oracle upper bound, clearly labeled unattainable.

## 5. Procedure

### Phase A — Instrument audit

1. Confirm every real parser can produce a valid canonical document.
2. Run existing unit tests for local metrics.
3. Hand-audit a small set of perfect and deliberately corrupted examples.
4. Confirm raw artifacts, configuration, and evaluator versions are retained.

Gate: do not begin downstream evaluation while metric direction, missing-value
behavior, or provenance is ambiguous.

### Phase B — Pilot

1. Select a deliberately heterogeneous pilot set.
2. Run every available parser/configuration on each pilot document.
3. Execute frozen draft downstream tasks with repeated generations.
4. Manually audit failure taxonomy and annotation feasibility.
5. Use the pilot to finalize primary outcomes, repetition count, and sample-size
   assumptions. Do not use pilot effect sizes as confirmed findings.

### Phase C — Confirmatory run

1. Freeze dataset, prompts, versions, metrics, exclusions, and analysis code.
2. Execute the full document-by-parser matrix.
3. Preserve failures and timeouts as outcomes; do not silently drop them.
4. Run the preregistered analysis before exploratory slicing.

### Phase D — Policy evaluation

1. Train/tune any consequence predictor without leaking documents across splits.
2. Evaluate on held-out documents or document-grouped cross-validation.
3. Sweep the verification/rerouting budget.
4. Plot the consequential-error versus cost frontier with uncertainty.

## 6. Statistical plan

- Report document-level distributions, not only parser means.
- Use paired comparisons because the same documents pass through each parser.
- Use document-clustered bootstrap confidence intervals for primary contrasts.
- If fitting a regression or mixed model, include document-level grouping and
  prespecified structural moderators.
- Keep all generations from a document/parser/task condition within the same data
  split.
- Correct or clearly scope multiple comparisons for secondary analyses.
- Report effect sizes and uncertainty even when significance thresholds are not met.

The final sample size must be justified after the pilot from feasible precision or
power. Do not select it solely because a round number looks publishable.

## 7. Required artifacts

Use machine-readable, append-only records where possible:

```text
research/
  manifests/
    dataset_manifest.jsonl
    run_manifest.jsonl
  prompts/
    task_<name>_v<version>.md
  annotations/
    annotation_schema.json
  raw/
    downstream_runs.jsonl
  derived/
    document_level_metrics.parquet
  reports/
    pilot_report.md
    confirmatory_report.md
```

Raw or private documents must not be committed. Manifests should contain stable IDs
and permitted metadata, not sensitive contents.

## 8. Reproducibility record

Every experiment report must include:

- date/time and operator;
- git commit SHA and dirty/clean status;
- dataset/prompt/evaluator versions;
- parser and model versions/configuration;
- environment summary;
- executed command;
- success, failure, timeout, and exclusion counts;
- paths or IDs for raw and derived results.

## 9. Immediate implementation backlog

Execute in this order:

1. Define the downstream run and evaluation schemas without changing existing parser
   benchmark semantics.
2. Add append-only run manifests and provenance capture.
3. Implement one fact-extraction task as the first vertical slice.
4. Add conclusion-shift and evidence-correctness evaluators with adversarial unit
   tests.
5. Add grouped export for document-level statistical analysis.
6. Only then implement triage/routing policies and dashboard views.
