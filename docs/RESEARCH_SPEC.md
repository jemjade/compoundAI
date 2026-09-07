# Research Specification

Status: `PROPOSED`

Working title: **Beyond Parser Ranking: Consequence-Aware Evaluation of Document
Parsing for LLM-Supported Analytical Work**

> 이 문서는 GPT에서 합의한 연구 논리를 Codex가 구현 가능한 계약으로 읽도록 만드는
> 연결 문서다. 결과가 나오기 전에는 모든 연구 가설을 `PROPOSED`로 취급한다.

## 1. Problem

Document parsers are commonly ranked with local extraction metrics such as character
error, layout overlap, table reconstruction, and reading order. These metrics are
important, but they do not establish whether a parsing difference changes the claims,
evidence, or conclusion produced by a downstream analytical system.

The research problem is therefore not merely **which parser is best on average**, but:

> Which parser differences become consequential for a downstream analytical task,
> and can a system identify when human verification or an alternative parse is worth
> the cost?

## 2. Current system boundary

The following capabilities are `IMPLEMENTED` in ParseLab:

- Run the same document through multiple parser adapters.
- Normalize heterogeneous outputs into a canonical document representation.
- Compare text, Markdown, tables, layout-derived summaries, artifacts, latency, and
  manually entered evaluations.
- Evaluate against versioned ground truth with parser-local metrics including
  `text_cer`, `text_accuracy`, `layout_f1_iou50`, `table_teds`,
  `table_structure_f1`, `reading_order_accuracy`, `formula_accuracy`, `pii_f1`, and
  `overall_quality`.
- Aggregate parser/configuration results with 95% confidence intervals and latency
  summaries.

The following are not yet established and remain `PROPOSED`:

- A standardized downstream analytical task suite.
- Claim-, evidence-, and conclusion-level consequence metrics.
- A validated relationship between parser-local quality and downstream failure.
- A routing or verification policy that reduces consequential error under a cost
  budget.

## 3. Research questions

### RQ1 — Propagation

How often and under which document structures do parser differences propagate into
changes in downstream claims, cited evidence, numerical values, or conclusions?

### RQ2 — Predictive validity

How well do conventional parser-local metrics predict downstream consequential
failures? Which structural error features add predictive value beyond aggregate
quality?

### RQ3 — Decision support

Can a consequence-aware verification or parser-routing policy reduce consequential
failures at a fixed verification/compute budget compared with simple alternatives?

### Optional RQ4 — Human oversight

Does a consequence-aware presentation help analysts identify what to verify with
less effort or higher accuracy than parser-local scores alone?

RQ4 requires a defensible human evaluation. It must not be claimed from computational
experiments alone.

## 4. Hypotheses

- **H1:** Downstream failure is heterogeneous: similar aggregate parser quality can
  conceal materially different claim or conclusion outcomes.
- **H2:** Structure-specific signals (for example table, formula, or reading-order
  errors) predict consequential downstream failure better than `overall_quality`
  alone for tasks that depend on those structures.
- **H3:** A consequence-aware policy achieves a better error-cost trade-off than
  `single best parser`, `lowest latency`, `overall quality threshold`, and random
  verification baselines.

These hypotheses are falsifiable. Null or contrary results must be retained and
reported.

## 5. Conceptual model

```text
source document
  -> parser + configuration
  -> canonical representation
  -> parser-local error features
  -> downstream analytical task
  -> claims + evidence + conclusion
  -> consequential outcome
  -> verify / reroute / accept decision
```

The key distinction is:

- **Local error:** difference between parsed output and document ground truth.
- **Downstream variation:** difference among generated analytical outputs.
- **Consequence:** a variation that changes a task-relevant fact, evidence link,
  recommendation, or conclusion.

Semantic variation without task impact is not automatically consequential.

## 6. Intended contributions

The strongest supportable contribution set would be:

1. An operational definition and reproducible measurement protocol for consequential
   parser error in LLM-supported analytical work.
2. Empirical evidence describing when parser-local errors do and do not propagate.
3. A consequence-aware triage/routing method evaluated against cost-matched baselines.
4. Design implications for human oversight of document-to-LLM pipelines.

Contribution 4 must be phrased as design implications unless a human study directly
tests the interface or workflow.

## 7. Novelty boundary

The paper must not present the following as sufficient novelty by themselves:

- another parser leaderboard;
- a dashboard that displays existing metrics;
- a new weighted average without predictive or decision value;
- pairwise text differences without task-level consequence;
- repeated LLM sampling treated as independent empirical units.

The novelty claim should rest on the transition from **component quality ranking** to
**task-consequence-aware oversight and allocation**.

## 8. Claim ledger

Maintain one row per paper claim in the eventual experiment artifacts.

| Claim | Required evidence | Current status |
|---|---|---|
| Parsers differ on local structural quality | Ground-truth benchmark across documents | `IMPLEMENTED`, not yet `VERIFIED` for the study dataset |
| Local quality incompletely predicts consequence | Document-level downstream runs and predictive comparison | `PROPOSED` |
| Structure-specific signals improve prediction | Held-out or cross-validated model comparison | `PROPOSED` |
| Triage improves the error-cost frontier | Cost-matched policy evaluation with uncertainty | `PROPOSED` |
| Interface improves human verification | Human evaluation | `BLOCKED` until a study is designed and run |

## 9. Freeze policy

Before confirmatory execution, freeze and version:

- dataset inclusion/exclusion rules;
- task templates and prompt text;
- parser/model versions and configurations;
- primary outcomes and aggregation rules;
- baselines and ablations;
- statistical analysis plan.

Exploratory changes remain allowed, but their outputs must be labeled exploratory and
must not be mixed silently into confirmatory results.
