"""Run and score the frozen dependency-aware upstream verification pilot.

Selection is deliberately separated from evaluation-only repair labels.  The live ``run`` command
first serializes policy inputs and selections, then joins selected source spans to the hidden repair
map and performs a fresh downstream execution for every policy-budget pair.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from research.allocation import (
    POLICIES,
    build_policy_input,
    graph_overlap,
    select_candidates,
)
from research.pilot import (
    CONDITIONS,
    digest,
    judgment_id,
    load_complete_run,
    read_jsonl,
    run_case,
    runner_payload,
    sha256,
    validate_case,
    validate_response,
    write_json,
    write_jsonl,
)
from research.pipeline_runner import RunnerConfig, synthesis_batches

LIVE_EXECUTION_MODES = {"live_model", "live_local_model"}
REQUIRED_METADATA = {
    "applied_generation_settings",
    "call_count",
    "code_sha256",
    "finished_at",
    "input_sha256",
    "pipeline_execution_id",
    "prompt_versions",
    "provider",
    "requested_model",
    "runner_config",
    "started_at",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _git_state() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    tracked_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    spec_path = root / "research/specs/experiment_spec_v1.json"
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(spec_path.relative_to(root))],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if tracked_status:
        raise ValueError("Live runs require a clean tracked worktree")
    return {"git_commit": commit, "git_tracked_files_dirty": False}


def _validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != 1:
        raise ValueError("Only experiment spec schema_version=1 is supported")
    if spec.get("status") != "FROZEN_EXPLORATORY_PILOT":
        raise ValueError("The experiment spec must be frozen before execution")
    if spec.get("frozen_before_live_run") is not True:
        raise ValueError("The experiment spec does not attest pre-run freezing")
    if spec["initial_runs"]["policy_visible_conditions"] != ["baseline", "no_op"]:
        raise ValueError("v1 policies may see only baseline and no_op")
    if spec["policies"]["budgets"] != [1, 2]:
        raise ValueError("v1 implementation is frozen to budgets 1 and 2")


def _subset_case(case: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    question_ids = spec["dataset"]["question_ids"]
    subset = {
        **case,
        "questions": [
            row for row in case["questions"] if row["question_id"] in question_ids
        ],
    }
    if [row["question_id"] for row in subset["questions"]] != question_ids:
        by_id = {row["question_id"]: row for row in subset["questions"]}
        subset["questions"] = [by_id[question_id] for question_id in question_ids]
    validate_case(subset)
    if [row["question_id"] for row in subset["questions"]] != question_ids:
        raise ValueError("The case does not contain the frozen ordered question set")
    return subset


def _call_plan(case: dict[str, Any], spec: dict[str, Any], config: RunnerConfig) -> dict[str, Any]:
    repeats = spec["initial_runs"]["repeats"]
    budgets = spec["policies"]["budgets"]
    question_count = len(case["questions"])
    synthesis_calls = (
        len(synthesis_batches(case["blocks"], config.synthesis_batch_chars))
        if config.synthesis_mode == "model"
        else 0
    )
    per_pipeline = synthesis_calls + question_count
    targeted_executions = repeats * len(CONDITIONS)
    policy_executions = repeats * len(POLICIES) * len(budgets)
    total_executions = targeted_executions + policy_executions
    return {
        "schema_version": 1,
        "execution_mode": "preflight_no_model_calls",
        "spec_id": spec["spec_id"],
        "repeats": repeats,
        "question_count": question_count,
        "synthesis_mode": config.synthesis_mode,
        "model": config.model,
        "targeted_pipeline_executions": targeted_executions,
        "policy_pipeline_executions": policy_executions,
        "total_pipeline_executions": total_executions,
        "model_calls_per_pipeline": per_pipeline,
        "estimated_model_calls": total_executions * per_pipeline,
        "max_output_tokens_if_every_call_hits_limit": total_executions
        * (
            synthesis_calls * config.synthesis_max_output_tokens
            + question_count * config.qa_max_output_tokens
        ),
        "budgets": budgets,
        "policies": list(POLICIES),
        "config": config.public_dict(),
    }


def preflight(
    case_path: Path, spec_path: Path, config_path: Path, max_total_calls: int | None
) -> dict[str, Any]:
    spec = _load_json(spec_path)
    _validate_spec(spec)
    case = _subset_case(_load_json(case_path), spec)
    config = RunnerConfig.load(config_path)
    if config.synthesis_mode != "passthrough":
        raise ValueError("experiment_spec_v1 requires synthesis_mode=passthrough")
    report = _call_plan(case, spec, config)
    report["max_total_calls"] = max_total_calls
    report["within_call_budget"] = (
        max_total_calls is None or report["estimated_model_calls"] <= max_total_calls
    )
    return report


def _validate_live_response(response: dict[str, Any]) -> None:
    metadata = response.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Live result metadata is required")
    if metadata.get("execution_mode") not in LIVE_EXECUTION_MODES:
        raise ValueError("Research result must come from a live model execution")
    missing = REQUIRED_METADATA - set(metadata)
    if missing:
        raise ValueError(f"Live result metadata is missing: {sorted(missing)}")
    if metadata.get("status") != "completed":
        raise ValueError("Live result metadata is not completed")
    if not str(metadata.get("pipeline_execution_id", "")).strip():
        raise ValueError("Live result needs a pipeline_execution_id")
    if type(metadata.get("call_count")) is not int or metadata["call_count"] < 1:
        raise ValueError("Live result needs a positive model call count")


def _run_payload(
    command: list[str], payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    result = subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1:] or ["no stderr"]
        raise RuntimeError(
            f"Runner exited with code {result.returncode}: {detail[0][:500]}"
        )
    response = json.loads(result.stdout)
    validate_response(response, payload)
    _validate_live_response(response)
    return response


def _repair_matches(
    case: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    repairs = {
        (row["block_id"], row["start"], row["end"], row["before"]): row
        for row in case["repairs"]
    }
    matches = {}
    for candidate in candidates:
        key = (
            candidate["block_id"],
            candidate["start"],
            candidate["end"],
            candidate["observed_text"],
        )
        if key in repairs:
            matches[candidate["candidate_id"]] = repairs[key]
    return matches


def _condition_record(
    *,
    selection: dict[str, Any],
    policy_input: dict[str, Any],
    case: dict[str, Any],
    command: list[str],
    timeout: float,
) -> dict[str, Any]:
    matches = _repair_matches(case, policy_input["candidates"])
    selected_ids = selection["selected_candidate_ids"]
    applied_repair_ids = sorted(
        {
            matches[candidate_id]["candidate_id"]
            for candidate_id in selected_ids
            if candidate_id in matches
        }
    )
    payload = runner_payload(case, tuple(applied_repair_ids), selection["repeat_id"])
    response = _run_payload(command, payload, timeout)
    actions = [
        {
            "candidate_id": candidate_id,
            "action": "ideal_exact_repair" if candidate_id in matches else "inspected_no_change",
            "repair_candidate_id": (
                matches[candidate_id]["candidate_id"] if candidate_id in matches else None
            ),
        }
        for candidate_id in selected_ids
    ]
    return {
        "execution_id": str(uuid4()),
        "record_kind": "policy_budget",
        "repeat_id": selection["repeat_id"],
        "policy": selection["policy"],
        "budget": selection["budget"],
        "spent_cost": selection["spent_cost"],
        "selected_candidate_ids": selected_ids,
        "selected_set_sha256": selection["selected_set_sha256"],
        "actions": actions,
        "input_sha256": digest(payload),
        "output_sha256": digest(response),
        "response": response,
    }


def run(
    *,
    case_path: Path,
    spec_path: Path,
    config_path: Path,
    out: Path,
    timeout: float,
    max_total_calls: int,
) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Output already exists; use a new append-only run path")
    spec = _load_json(spec_path)
    _validate_spec(spec)
    case = _subset_case(_load_json(case_path), spec)
    config = RunnerConfig.load(config_path)
    if config.synthesis_mode != "passthrough":
        raise ValueError("experiment_spec_v1 requires synthesis_mode=passthrough")
    plan = _call_plan(case, spec, config)
    if plan["estimated_model_calls"] > max_total_calls:
        raise ValueError("Preflight model-call estimate exceeds max_total_calls")
    git_state = _git_state()

    out.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "run_id": str(uuid4()),
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256(spec_path.read_bytes()),
        "case_sha256": digest(case),
        "config_sha256": sha256(config_path.read_bytes()),
        "call_plan": plan,
        "max_total_calls": max_total_calls,
        **git_state,
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "frozen_spec.json", spec)
    write_json(out / "frozen_case.json", case)
    write_json(out / "frozen_config.json", json.loads(config_path.read_text()))

    command = [
        sys.executable,
        "-m",
        "research.pipeline_runner",
        "run",
        "--config",
        str(config_path.resolve()),
    ]
    try:
        run_case(
            case,
            command,
            out / "targeted_conditions",
            repeats=spec["initial_runs"]["repeats"],
            timeout=timeout,
        )
        _, base_records = load_complete_run(out / "targeted_conditions")
        for record in base_records:
            _validate_live_response(record["response"])

        policy_inputs = []
        selections = []
        for repeat_id in range(spec["initial_runs"]["repeats"]):
            records = {
                row["condition"]: row
                for row in base_records
                if row["repeat_id"] == repeat_id
            }
            policy_input = build_policy_input(
                case=case,
                baseline_record=records["baseline"],
                no_op_record=records["no_op"],
                question_ids=spec["dataset"]["question_ids"],
                spec_id=spec["spec_id"],
                repeat_id=repeat_id,
            )
            matches = _repair_matches(case, policy_input["candidates"])
            if len(policy_input["candidates"]) <= len(matches):
                raise ValueError("Candidate universe must contain normal candidates")
            policy_input["candidate_count"] = len(policy_input["candidates"])
            policy_input["policy_input_sha256"] = digest(policy_input)
            policy_inputs.append(policy_input)
            for policy in POLICIES:
                for budget in spec["policies"]["budgets"]:
                    selection = select_candidates(
                        policy_input["candidates"],
                        policy=policy,
                        budget=budget,
                        seed_material=[
                            spec["spec_id"],
                            manifest["case_sha256"],
                            repeat_id,
                            budget,
                            policy,
                        ],
                        question_count=len(spec["dataset"]["question_ids"]),
                    )
                    selection.update(
                        {
                            "schema_version": 1,
                            "spec_id": spec["spec_id"],
                            "repeat_id": repeat_id,
                            "policy_input_sha256": policy_input["policy_input_sha256"],
                        }
                    )
                    selections.append(selection)

        # This is the leakage boundary: selections are durable before repair labels are joined.
        write_jsonl(out / "policy_inputs.jsonl", policy_inputs)
        write_jsonl(out / "selections.jsonl", selections)

        by_repeat = {row["repeat_id"]: row for row in policy_inputs}
        policy_records = []
        with (out / "policy_records.jsonl").open("x") as stream:
            for selection in selections:
                record = _condition_record(
                    selection=selection,
                    policy_input=by_repeat[selection["repeat_id"]],
                    case=case,
                    command=command,
                    timeout=timeout,
                )
                policy_records.append(record)
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()

        execution_ids = [
            row["response"]["metadata"]["pipeline_execution_id"]
            for row in [*base_records, *policy_records]
        ]
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("A model response was reused across experimental conditions")
        completed_model_calls = sum(
            row["response"]["metadata"]["call_count"]
            for row in [*base_records, *policy_records]
        )
        if completed_model_calls > max_total_calls:
            raise ValueError("Completed model calls exceeded max_total_calls")

        manifest.update(
            {
                "status": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "targeted_record_count": len(base_records),
                "policy_record_count": len(policy_records),
                "candidate_counts": {
                    str(row["repeat_id"]): row["candidate_count"] for row in policy_inputs
                },
                "policy_input_file_sha256": sha256(
                    (out / "policy_inputs.jsonl").read_bytes()
                ),
                "selection_file_sha256": sha256((out / "selections.jsonl").read_bytes()),
                "policy_record_file_sha256": sha256(
                    (out / "policy_records.jsonl").read_bytes()
                ),
                "completed_model_calls": completed_model_calls,
                "unique_pipeline_execution_ids": len(execution_ids),
            }
        )
    except Exception as error:
        manifest.update(
            {
                "status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
            }
        )
        raise
    finally:
        write_json(out / "manifest.json", manifest)
    return manifest


def _all_records(run_dir: Path) -> list[dict[str, Any]]:
    _, targeted = load_complete_run(run_dir / "targeted_conditions")
    policy = read_jsonl(run_dir / "policy_records.jsonl")
    records = [*targeted, *policy]
    execution_ids = [row["execution_id"] for row in records]
    pipeline_ids = []
    for row in records:
        _validate_live_response(row["response"])
        if digest(row["response"]) != row["output_sha256"]:
            raise ValueError("Recorded response changed after execution")
        pipeline_ids.append(row["response"]["metadata"]["pipeline_execution_id"])
    if len(execution_ids) != len(set(execution_ids)) or len(pipeline_ids) != len(
        set(pipeline_ids)
    ):
        raise ValueError("Duplicate execution identity")
    return records


def judgment_template(run_dir: Path, gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = _load_json(run_dir / "manifest.json")
    if manifest.get("status") != "complete":
        raise ValueError("Cannot judge an incomplete allocation run")
    case = _load_json(run_dir / "frozen_case.json")
    records = _all_records(run_dir)
    gold = {row["question_id"]: row for row in gold_rows}
    questions = {row["question_id"]: row["question"] for row in case["questions"]}
    blocks = {row["block_id"]: row for row in case["blocks"]}
    rows = []
    for record in records:
        for answer in record["response"]["answers"]:
            question_id = answer["question_id"]
            cited = [blocks[block_id] for block_id in answer.get("evidence_block_ids", [])]
            rows.append(
                {
                    "judgment_id": judgment_id(record, question_id),
                    "question_id": question_id,
                    "question": questions[question_id],
                    "prediction": answer["answer"],
                    "prediction_evidence_block_ids": answer.get("evidence_block_ids", []),
                    "cited_evidence": [
                        {
                            "block_id": row["block_id"],
                            "page_number": row["page_number"],
                            "text": row["text"],
                        }
                        for row in cited
                    ],
                    "reference_answer": gold[question_id]["reference_answer"],
                    "reference_evidence": gold[question_id].get("evidence", []),
                    "answer_correct": None,
                    "evidence_correct": None,
                    "judge_id": "",
                    "rationale": "",
                }
            )
    return sorted(rows, key=lambda row: row["judgment_id"])


NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _reference_numbers(value: str) -> list[str]:
    return [match.group(0).replace(",", "") for match in NUMBER_PATTERN.finditer(value)]


def deterministic_judgments(template: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A strict, transparent v1 judge; not a validated general FinanceBench evaluator."""
    output = []
    for row in template:
        prediction = row["prediction"].replace(",", "")
        required_numbers = _reference_numbers(row["reference_answer"])
        missing_numbers = [value for value in required_numbers if value not in prediction]
        reference = row["reference_answer"].lower()
        normalized_prediction = prediction.lower()
        direction_ok = True
        if reference.lstrip().startswith("yes") and not (
            "yes" in normalized_prediction or "improv" in normalized_prediction
        ):
            direction_ok = False
        answer_correct = not missing_numbers and direction_ok
        allowed_blocks = {
            evidence["block_id"] for evidence in row.get("reference_evidence", [])
        }
        cited_blocks = set(row.get("prediction_evidence_block_ids", []))
        evidence_correct = bool(allowed_blocks & cited_blocks)
        output.append(
            {
                **row,
                "answer_correct": answer_correct,
                "evidence_correct": evidence_correct,
                "judge_id": "deterministic-reference-numeric-v1",
                "rationale": (
                    f"missing_reference_numbers={missing_numbers}; direction_ok={direction_ok}; "
                    f"gold_block_cited={evidence_correct}. Strict pilot rule; alternate supporting "
                    "pages require manual review."
                ),
            }
        )
    return output


def _outcome(
    current: dict[str, bool], baseline: dict[str, bool]
) -> dict[str, Any]:
    if set(current) != set(baseline):
        raise ValueError("Outcome question sets differ")
    recovered = sorted(q for q in baseline if not baseline[q] and current[q])
    regressed = sorted(q for q in baseline if baseline[q] and not current[q])
    return {
        "correct_count": sum(current.values()),
        "question_count": len(current),
        "accuracy": sum(current.values()) / len(current),
        "recovered_question_ids": recovered,
        "regressed_question_ids": regressed,
        "net_recovery": len(recovered) - len(regressed),
    }


def score(run_dir: Path, judgments: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = _load_json(run_dir / "manifest.json")
    if manifest.get("status") != "complete":
        raise ValueError("Cannot score an incomplete allocation run")
    case = _load_json(run_dir / "frozen_case.json")
    records = _all_records(run_dir)
    mapped = {row["judgment_id"]: row for row in judgments}
    expected = {
        judgment_id(record, answer["question_id"])
        for record in records
        for answer in record["response"]["answers"]
    }
    if len(mapped) != len(judgments) or set(mapped) != expected:
        raise ValueError("Every prediction needs exactly one unmodified judgment")
    for row in judgments:
        if (
            type(row.get("answer_correct")) is not bool
            or type(row.get("evidence_correct")) is not bool
            or not str(row.get("judge_id", "")).strip()
        ):
            raise ValueError("Complete answer/evidence judgments and judge_id are required")

    correctness: dict[str, dict[str, bool]] = {}
    for record in records:
        correctness[record["execution_id"]] = {
            answer["question_id"]: bool(
                mapped[judgment_id(record, answer["question_id"])]["answer_correct"]
                and mapped[judgment_id(record, answer["question_id"])]["evidence_correct"]
            )
            for answer in record["response"]["answers"]
        }

    targeted = [row for row in records if "condition" in row]
    policy_records = [row for row in records if row.get("record_kind") == "policy_budget"]
    policy_inputs = {row["repeat_id"]: row for row in read_jsonl(run_dir / "policy_inputs.jsonl")}
    repeat_rows = []
    for repeat_id in range(_load_json(run_dir / "frozen_spec.json")["initial_runs"]["repeats"]):
        target_by_condition = {
            row["condition"]: row for row in targeted if row["repeat_id"] == repeat_id
        }
        baseline = correctness[target_by_condition["baseline"]["execution_id"]]
        condition_outcomes = {
            condition: _outcome(correctness[row["execution_id"]], baseline)
            for condition, row in target_by_condition.items()
        }
        policy_outcomes = []
        for record in sorted(
            (row for row in policy_records if row["repeat_id"] == repeat_id),
            key=lambda row: (row["policy"], row["budget"]),
        ):
            policy_outcomes.append(
                {
                    "policy": record["policy"],
                    "budget": record["budget"],
                    "spent_cost": record["spent_cost"],
                    "selected_candidate_ids": record["selected_candidate_ids"],
                    "actions": record["actions"],
                    **_outcome(correctness[record["execution_id"]], baseline),
                }
            )

        candidates = policy_inputs[repeat_id]["candidates"]
        matches = _repair_matches(case, candidates)
        candidate_by_repair = {
            repair["candidate_id"]: candidate_id for candidate_id, repair in matches.items()
        }
        candidate_by_id = {row["candidate_id"]: row for row in candidates}
        a_id, b_id = candidate_by_repair.get("A"), candidate_by_repair.get("B")
        recovered_a = set(condition_outcomes["A"]["recovered_question_ids"])
        recovered_b = set(condition_outcomes["B"]["recovered_question_ids"])
        recovery_union = recovered_a | recovered_b
        repeat_rows.append(
            {
                "repeat_id": repeat_id,
                "targeted_conditions": condition_outcomes,
                "policy_budget_outcomes": policy_outcomes,
                "no_op_net_change": condition_outcomes["no_op"]["net_recovery"],
                "interaction_count": condition_outcomes["AB"]["net_recovery"]
                - condition_outcomes["A"]["net_recovery"]
                - condition_outcomes["B"]["net_recovery"],
                "graph_vs_actual": {
                    "repair_candidate_ids": {"A": a_id, "B": b_id},
                    "structural_overlap": (
                        graph_overlap(candidate_by_id[a_id], candidate_by_id[b_id])
                        if a_id and b_id
                        else None
                    ),
                    "actual_recovery_overlap": (
                        len(recovered_a & recovered_b) / len(recovery_union)
                        if recovery_union
                        else None
                    ),
                    "actual_recovered_by_A": sorted(recovered_a),
                    "actual_recovered_by_B": sorted(recovered_b),
                },
            }
        )
    return {
        "schema_version": 1,
        "spec_id": manifest["spec_id"],
        "run_id": manifest["run_id"],
        "run_manifest_sha256": sha256((run_dir / "manifest.json").read_bytes()),
        "judgments_sha256": digest(judgments),
        "scope": (
            "one-document controlled-text exploratory wiring pilot; "
            "no policy-superiority or population claim"
        ),
        "correctness_definition": "answer_correct AND evidence_correct",
        "interaction_definition": "G(AB)-G(A)-G(B) from actual fresh simultaneous AB rerun",
        "repeats": repeat_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    estimate = commands.add_parser("preflight")
    execute = commands.add_parser("run")
    for command in (estimate, execute):
        command.add_argument("--case", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--max-total-calls", type=int, required=True)
    execute.add_argument("--out", type=Path, required=True)
    execute.add_argument("--timeout", type=float, default=900)
    template = commands.add_parser("judge-template")
    template.add_argument("--run", type=Path, required=True)
    template.add_argument("--gold", type=Path, required=True)
    template.add_argument("--out", type=Path, required=True)
    auto = commands.add_parser("auto-judge")
    auto.add_argument("--template", type=Path, required=True)
    auto.add_argument("--out", type=Path, required=True)
    scoring = commands.add_parser("score")
    scoring.add_argument("--run", type=Path, required=True)
    scoring.add_argument("--judgments", type=Path, required=True)
    scoring.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.action in {"preflight", "run"}:
        report = preflight(args.case, args.spec, args.config, args.max_total_calls)
        if args.action == "preflight":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if not report["within_call_budget"]:
                raise SystemExit(2)
            return
        if not report["within_call_budget"]:
            raise ValueError("Preflight exceeds the requested call budget")
        result = run(
            case_path=args.case,
            spec_path=args.spec,
            config_path=args.config,
            out=args.out,
            timeout=args.timeout,
            max_total_calls=args.max_total_calls,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "judge-template":
        if args.out.exists():
            raise ValueError("Judgment output already exists")
        write_jsonl(args.out, judgment_template(args.run, read_jsonl(args.gold)))
    elif args.action == "auto-judge":
        if args.out.exists():
            raise ValueError("Judgment output already exists")
        write_jsonl(args.out, deterministic_judgments(read_jsonl(args.template)))
    else:
        if args.out.exists():
            raise ValueError("Score output already exists")
        write_json(args.out, score(args.run, read_jsonl(args.judgments)))


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as error:
        print(f"Allocation pilot stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
