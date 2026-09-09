# Dependency-aware upstream pilot v1 — run 001

Status: `IMPLEMENTED` end-to-end exploratory wiring result; research claims remain `PROPOSED`.

## Execution identity

- Frozen spec: `research/specs/experiment_spec_v1.json`
- Spec commit: `ea8f01a`
- Executed code commit: `388edb6597921c26ffb9dba19e775dd397be5767`
- Run ID: `9387c6c1-0317-4758-9797-e5db41c08721`
- Raw artifact directory: `research/work/dependency-aware-pilot-v1-run-001` (intentionally Git-ignored)
- Tracked result summary: `research/results/dependency-aware-pilot-v1-run-001-summary.json`
- Run period: 2026-09-08 02:59:46–03:06:19 UTC

The live runner's tracked worktree was clean. The frozen spec, case, configuration, policy inputs,
selections, model responses, judgments, and aggregate are content-addressed in the result summary.
Raw artifacts remain local because they contain the full extracted PDF text, prompts, retrieved
chunks, and model responses.

## Preflight and actual resource use

Preflight fixed 13 independent pipeline executions: baseline, no-op, A, B, AB, plus four policies
at budgets 1 and 2. Passthrough synthesis made each pipeline use two QA calls. The estimate was 26
model calls and at most 10,400 output tokens. The run completed exactly 26 model calls across 13
unique pipeline execution IDs, using 78,476 input tokens and 2,790 output tokens.

The actual local model was `llama3:latest`, digest
`365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1`, 8.0B parameters, Q4_0,
through Ollama 0.30.6. Settings were temperature 0, context 8192, QA output limit 400,
retrieval top-k 4, and deterministic source passthrough. These are actual model outputs, not mocks.

## What ran end to end

The baseline and no-op runs were distinct executions with the same input hash but different
pipeline IDs and output hashes. A, B, and AB each used their own fresh execution; AB applied both
source-span corrections simultaneously before chunking, retrieval, and QA. Policy input contained
only the fixed questions, corrupted blocks, and baseline/no-op traces. It did not contain repair
labels, gold answers, gold evidence, A/B/AB outputs, or post-repair effects. Selections were written
before the evaluation-only repair map was joined.

The common candidate universe contained 323 numeric spans, all charged at cost one. The graph had
1,441 nodes and 1,919 edges. Random, Uncertainty, Individual impact, and Graph-aware each spent
their exact budget at budgets 1 and 2 and each launched a new downstream execution. The blind
template contained 26 answer judgments and excluded condition, policy, budget, repeat, and repair
status.

## Observed results

Strict correctness required both the referenced numeric answer and supporting evidence. Every
targeted condition scored 0/2: baseline 0, no-op 0, A 0, B 0, and AB 0. Thus recovered answers,
newly wrong answers, net recovery, no-op correctness change, and the measured A+B interaction were
all zero.

The no-op did nevertheless show model-output variation. For the gross-margin question, baseline
returned `Insufficient evidence` with four cited blocks, while no-op returned a longer insufficient-
evidence answer with no citation. Its frozen instability feature was 1.0. The tax-rate answer and
cited block set were stable, giving instability 0.0. Correctness stayed unchanged, so this output
variation is not counted as recovery or regression.

All eight policy-budget executions also scored 0/2 and net recovery 0. Every selected candidate was
a normal candidate and was logged as `inspected_no_change`; the model still reran and the cost was
charged. Individual impact and Graph-aware happened to choose the same sets at both budgets. The
Graph-aware second-choice marginal score was discounted for shared descendants, but the discount
did not change the rank. This run therefore does not provide a policy ordering.

## Failure analysis

Neither controlled corruption was present in the policy candidate universe. Both A (`6,608`) and B
(`6,106`) live on `BOEING_2022_10K:p55`, but the union of baseline/no-op BM25 top-4 retrieved
chunks contained zero p55 candidates. The provenance graph retained the p55 source and chunk
lineage, but v1 created no candidate node or candidate-to-chunk edge there because candidates come
only from retrieved chunks. Direct A/B/AB oracle-location plumbing could apply
the repairs, but fresh retrieval again failed to surface p55, so the QA outputs did not improve.

This is a substantive negative result: the intervention and rerun path works, but the v1 candidate
recall gate made both injected errors unreachable to all selectable policies. Graph structural
overlap versus actual recovery overlap is therefore `null`, not zero; there were no repair-matched
candidates and no recovered-set union to compare.

The deterministic judge is intentionally strict and is not a validated general FinanceBench
evaluator. In this run every answer was explicitly insufficient and failed evidence support, so the
0/2 judgments do not hinge on borderline paraphrase or alternate-evidence treatment.

## Versioned design consequence

Do not alter v1 or reuse this inspected run as independent final evaluation. A future v1.1 must be
pre-registered under a new spec ID and explain its candidate-recall change. At minimum it should
enumerate verification candidates independently of QA top-k retrieval, or add a frozen structural/
lexical candidate-retrieval route whose recall is measured before policy comparison. It should
include an explicit candidate-recall gate and keep the same repair-label separation. Hyperparameters
chosen after seeing run 001 must be fixed using development documents, then evaluated on untouched
documents.

## Abstract requirement ledger

| Requirement | Status after run 001 | Evidence or blocker |
|---|---|---|
| Upstream candidate generation and verification unit | `IMPLEMENTED` | 323 numeric spans, normal candidates included, unit cost charged |
| Random, Uncertainty, Individual impact, Graph-aware | `IMPLEMENTED` | Eight policy-budget selections and fresh executions |
| Actual repair join and downstream rerun | `IMPLEMENTED` | Targeted A/B/AB plus policy-selected repair/no-change path |
| Recovery/regression/net/no-op/interaction aggregate | `IMPLEMENTED` | 26 blind judgments and `summary.json`; all observed values zero |
| General graph-aware policy benefit | `PROPOSED` | Error candidates absent; one document and one repeat |
| Diverse real parser outputs | `PROPOSED` | One pypdf output only |
| VLM/image/layout multimodal evaluation | `PROPOSED` | Text-only passthrough and QA |
| Natural parser errors and grounded corruption taxonomy | `PROPOSED` | Two controlled digit deletions only |
| Allocation across multiple pipeline stages | `PROPOSED` | Parsing-text candidates only |
| Fair output-only comparison | `PROPOSED` | No cost-matched output correction unit |
| Multiple independent documents | `PROPOSED` | One Boeing document |
| Provenance-aware verification interface | `PROPOSED` | Machine-readable trace/graph only; no user interface study |
| Paper tables, uncertainty, and limitation analysis | `PROPOSED` | No independent sample, repeats, interval, or inferential result |

## Abstract wording proposal (not applied)

The existing abstract text was not edited. Until confirmatory evidence exists, any completion claim
should be narrowed to: a controlled, one-document text pilot implemented four upstream selection
policies and fresh repair/rerun accounting; its first run exposed a candidate-recall failure and did
not establish recovery or policy superiority. Multimodal, natural-error, cross-stage, output-only,
human, and population-level claims remain future work.
