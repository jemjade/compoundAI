# CompoundAI Agent Guidance

## Mission

Treat this repository as both a working parser-comparison system and a research
instrument. Preserve reproducibility, provenance, and the distinction between
implemented behavior and proposed research claims.

## Source of truth

Read these files before research-facing work:

1. `docs/RESEARCH_SPEC.md` for the current research question and claim status.
2. `docs/EXPERIMENT_PLAN.md` for experimental units, controls, metrics, and gates.
3. `README.md` and `docs/PROJECT_UNDERSTANDING_GUIDE.md` for implemented behavior.

If prose conflicts with executable code or tests, report the conflict. Do not
silently rewrite the research claim to fit an implementation shortcut.

## Evidence labels

Use exactly these labels in research notes and reports:

- `IMPLEMENTED`: present in code and covered by an executable path.
- `VERIFIED`: supported by a recorded experiment with configuration and raw output.
- `PROPOSED`: planned but not yet empirically supported.
- `BLOCKED`: cannot be evaluated with the currently available data or environment.

Never turn `PROPOSED` into `VERIFIED` from intuition, synthetic examples, or a
successful unit test. Never invent sample sizes, effect sizes, p-values, confidence
intervals, model versions, costs, or human-study results.

## Research constraints

- Keep parser-local quality separate from downstream consequence.
- Preserve the unit of analysis. Repeated model generations from one document are
  not independent documents.
- Record parser name/version/config, dataset version, prompt version, downstream
  model/version, decoding parameters, seed when supported, timestamp, and git SHA.
- Store raw per-run results before aggregates.
- Predeclare primary outcomes before confirmatory runs.
- Treat the proposed consequence score and routing policy as provisional until
  validated against downstream failures.
- Do not claim an HCI contribution solely from a benchmark dashboard. Tie claims to
  a human decision, oversight, verification, or cognitive-cost problem.

## Implementation rules

- Keep FastAPI routers thin; business rules belong in services and persistence in
  repositories.
- Keep parser-specific behavior inside adapters/normalizers.
- Extend schemas explicitly rather than passing unvalidated research payloads.
- Do not commit secrets, private documents, raw PII, credentials, or `.env` files.
- Prefer additive migrations and backward-compatible API changes.
- Add or update tests for every metric, state transition, and serialization change.
- Preserve raw artifacts and use stable identifiers to link document, parser run,
  downstream run, and evaluation.

## Verification commands

Run the smallest relevant checks first, followed by the full applicable suite:

```bash
cd backend
uv run ruff check .
uv run pytest tests/unit

cd ../frontend
npm run build
```

Integration tests may require PostgreSQL or external parser services. If they cannot
run, mark them `BLOCKED` and state the missing dependency.

## Working protocol

For each task:

1. State which research claim or system capability the change supports.
2. Identify the files and data contracts affected.
3. Implement the smallest testable vertical slice.
4. Run checks and save reproducible outputs.
5. Report implemented, verified, proposed, and blocked items separately.
