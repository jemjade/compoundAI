"""Run the frozen, step-gated v1.5 short-planner development diagnostic."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from research.budgeted_ollama import BudgetedOllamaGenerator
from research.calculator_qa import (
    build_short_source_registry,
    prepare_short_planner_contract,
    run_short_calculator_qa,
)
from research.checksum_manifest import create as create_checksums
from research.development_v1_4 import (
    _git_state,
    _inventory,
    _load,
    _load_docling_pages,
    _load_questions,
    build_amd_repair_state,
)
from research.pilot import digest, read_jsonl, sha256, write_json
from research.pipeline_runner import RunnerConfig

SPEC_STATUS = "FROZEN_DEVELOPMENT_DIAGNOSTIC"
AMD_QID = "financebench_id_00222"
AMCOR_QID = "financebench_id_00684"
HARD_CALL_LIMIT = 16
NORMAL_PATH_CALLS = 14
REPAIR_STATES: dict[str, tuple[str, ...]] = {
    "damaged_baseline": (),
    "damaged_no_op_fresh": (),
    "A_only": ("A",),
    "B_only": ("B",),
    "A_plus_B": ("A", "B"),
}
GATE_DIMENSIONS = (
    "metric_selection",
    "value_selection",
    "period_selection",
    "unit_selection",
    "arithmetic",
    "conclusion",
    "evidence",
    "answer_uses_program_result",
)


def _question_spec(spec: dict[str, Any]) -> dict[str, Any]:
    rows = spec["fixed_inputs"]["source_pages"]
    return {
        "questions": [
            {
                "question_id": row["question_id"],
                "document_id": row["document_id"],
                "page": row["page"],
            }
            for row in rows
        ]
    }


def _inputs(
    data_dir: Path, parser_dir: Path, spec: dict[str, Any]
) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, Any]]]]:
    shim = _question_spec(spec)
    questions = _load_questions(data_dir, shim)
    pages = _load_docling_pages(parser_dir, questions, shim)
    return {row["question_id"]: row for row in questions}, pages


def preflight(
    *,
    data_dir: Path,
    parser_dir: Path,
    spec_path: Path,
    config_path: Path,
    max_calls: int,
) -> dict[str, Any]:
    spec = _load(spec_path)
    if (
        spec.get("status") != SPEC_STATUS
        or spec.get("frozen_before_live_run") is not True
        or spec.get("spec_id")
        != "short-planner-calculator-development-diagnostic-v1.5"
    ):
        raise ValueError("v1.5 spec is not frozen")
    budget = spec["live_call_budget"]
    if (
        max_calls != HARD_CALL_LIMIT
        or budget["normal_path"]["total"] != NORMAL_PATH_CALLS
        or budget["hard_max_including_failures"] != HARD_CALL_LIMIT
        or budget["retries"] != 0
    ):
        raise ValueError("Frozen v1.5 call budget changed")
    config = RunnerConfig.load(config_path)
    if (
        config.model != "llama3:latest"
        or config.max_retries != 0
        or config.synthesis_mode != "passthrough"
        or config.temperature != 0
        or config.ollama_num_ctx != 8192
    ):
        raise ValueError("Frozen v1.5 local model settings changed")
    parser_manifest = parser_dir / "manifest.json"
    if sha256(parser_manifest.read_bytes()) != spec["fixed_inputs"]["docling_manifest_sha256"]:
        raise ValueError("Reused Docling manifest hash changed")
    questions, pages = _inputs(data_dir, parser_dir, spec)
    estimates = {}
    for qid in (AMD_QID, AMCOR_QID):
        prepared = prepare_short_planner_contract(
            question=questions[qid], blocks=pages[qid], num_ctx=config.ollama_num_ctx
        )
        estimates[qid] = {
            "candidate_count": prepared["candidate_count"],
            "candidate_reduction": prepared["candidate_reduction"],
            "token_estimate": prepared["token_estimate"],
        }
    repair_eligible = True
    repair_reason = "unambiguous existing Docling 2022 cash and receivable cells"
    try:
        for restored in REPAIR_STATES.values():
            blocks, _labels = build_amd_repair_state(pages[AMD_QID], restored)
            prepare_short_planner_contract(
                question=questions[AMD_QID],
                blocks=blocks,
                num_ctx=config.ollama_num_ctx,
            )
    except (ValueError, RuntimeError) as error:
        repair_eligible = False
        repair_reason = str(error)
    return {
        "execution_mode": "preflight_no_model_calls",
        "spec_id": spec["spec_id"],
        "model": config.model,
        "num_ctx": config.ollama_num_ctx,
        "retries": config.max_retries,
        "clean_requests": 2,
        "repair_requests_if_gated": 5,
        "normal_path_calls": NORMAL_PATH_CALLS,
        "hard_call_limit": HARD_CALL_LIMIT,
        "within_budget": NORMAL_PATH_CALLS <= HARD_CALL_LIMIT,
        "repair_eligible": repair_eligible,
        "repair_reason": repair_reason,
        "planner_estimates": estimates,
        "reused_docling_manifest_sha256": sha256(parser_manifest.read_bytes()),
        "parser_calls": 0,
    }


def _tracked(root: Path, spec: Path, config: Path) -> list[Path]:
    return [
        spec.resolve(),
        config.resolve(),
        root / "research/development_v1_5.py",
        root / "research/calculator_qa.py",
        root / "research/budgeted_ollama.py",
        root / "research/pipeline_runner.py",
        root / "research/development_v1_4.py",
        root / "research/canonical_adapter.py",
    ]


def _base_manifest(
    *,
    phase: str,
    args: argparse.Namespace,
    plan: dict[str, Any],
    git_state: dict[str, Any],
    prior_calls: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "running",
        "run_id": str(uuid4()),
        "phase": phase,
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "oracle_source_page_development_diagnostic_not_RAG",
        "call_plan": plan,
        "phase_initial_call_count": prior_calls,
        "hard_call_limit": HARD_CALL_LIMIT,
        "normal_path_call_limit": NORMAL_PATH_CALLS,
        "spec_sha256": sha256(args.spec.read_bytes()),
        "config_sha256": sha256(args.config.read_bytes()),
        "parser_manifest_sha256": sha256((args.parser_dir / "manifest.json").read_bytes()),
        "backup_status": "primary persistent project path; independent physical backup unverified",
        **git_state,
    }


def _write_input(
    stream: Any,
    *,
    condition: str,
    question: dict[str, str],
    blocks: list[dict[str, Any]],
    repair_target_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = build_short_source_registry(blocks)
    row = {
        "condition": condition,
        "question": question,
        "blocks": blocks,
        "source_registry": registry,
        "candidate_rule": "all current-state numeric sources; no reduction",
    }
    if repair_target_state is not None:
        row["repair_target_state_evaluation_only_not_model_input"] = repair_target_state
    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    stream.flush()
    return row


def _execute_request(
    *,
    condition: str,
    question: dict[str, str],
    blocks: list[dict[str, Any]],
    generator: BudgetedOllamaGenerator,
    input_stream: Any,
    record_stream: Any,
    num_ctx: int,
    repair_target_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_row = _write_input(
        input_stream,
        condition=condition,
        question=question,
        blocks=blocks,
        repair_target_state=repair_target_state,
    )
    record: dict[str, Any] = {
        "execution_id": str(uuid4()),
        "condition": condition,
        "question_id": question["question_id"],
        "document_id": question["document_id"],
        "evidence_route": "frozen_oracle_docling_page",
        "input_sha256": digest(input_row),
        "pipeline": "short_calculator_v1_5",
        "candidate_count": len(input_row["source_registry"]),
        "candidate_reduction": "none",
    }
    if repair_target_state is not None:
        record["repair_target_state_evaluation_only"] = repair_target_state
    before = generator.call_count
    try:
        response = run_short_calculator_qa(
            question=question,
            blocks=blocks,
            generator=generator,
            num_ctx=num_ctx,
        )
        record.update(
            {
                "status": "completed",
                "response": response,
                "stage_status": response["stage_status"],
                "output_sha256": digest(response),
            }
        )
    except Exception as error:  # noqa: BLE001 - every live failure is an outcome
        record.update(
            {
                "status": "failed",
                "failure_type": type(error).__name__,
                "failure_message": str(error),
                "stage_status": getattr(error, "trace", {}),
            }
        )
    record["actual_call_count"] = generator.call_count - before
    record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    record_stream.flush()
    return record


def _finish(
    *,
    output: Path,
    manifest: dict[str, Any],
    generator: BudgetedOllamaGenerator,
    request_count: int,
) -> dict[str, Any]:
    inputs_path = output / "inputs.jsonl"
    records_path = output / "records.jsonl"
    phase_calls = generator.call_count - generator.initial_call_count
    manifest.update(
        {
            "status": "complete",
            "finished_at": datetime.now(UTC).isoformat(),
            "completed_phase_model_calls": phase_calls,
            "cumulative_v1_5_model_calls": generator.call_count,
            "completed_pipeline_requests": request_count,
            "inputs_sha256": sha256(inputs_path.read_bytes()),
            "records_sha256": sha256(records_path.read_bytes()),
            "provider_runtime": generator.provider_runtime,
        }
    )
    write_json(output / "manifest.json", manifest)
    create_checksums(output, output / "checksums.json")
    return manifest


def run_clean(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise ValueError("Output exists; v1.5 runs are append-only")
    plan = preflight(
        data_dir=args.data_dir,
        parser_dir=args.parser_dir,
        spec_path=args.spec,
        config_path=args.config,
        max_calls=args.max_calls,
    )
    root = Path(__file__).resolve().parents[1]
    git_state = _git_state(root, _tracked(root, args.spec, args.config))
    spec = _load(args.spec)
    questions, pages = _inputs(args.data_dir, args.parser_dir, spec)
    config = RunnerConfig.load(args.config)
    args.output.mkdir(parents=True)
    manifest = _base_manifest(
        phase="clean_gate", args=args, plan=plan, git_state=git_state, prior_calls=0
    )
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "frozen_spec.json", spec)
    write_json(args.output / "frozen_config.json", _load(args.config))
    write_json(args.output / "model_inventory.json", _inventory(config))
    generator = BudgetedOllamaGenerator(
        config, args.output / "calls", HARD_CALL_LIMIT
    )
    requests = []
    with (args.output / "inputs.jsonl").open("x") as input_stream, (
        args.output / "records.jsonl"
    ).open("x") as record_stream:
        amd = _execute_request(
            condition="amd_clean",
            question=questions[AMD_QID],
            blocks=pages[AMD_QID],
            generator=generator,
            input_stream=input_stream,
            record_stream=record_stream,
            num_ctx=config.ollama_num_ctx or 0,
        )
        requests.append(amd)
        if amd["status"] == "completed":
            requests.append(
                _execute_request(
                    condition="amcor_clean",
                    question=questions[AMCOR_QID],
                    blocks=pages[AMCOR_QID],
                    generator=generator,
                    input_stream=input_stream,
                    record_stream=record_stream,
                    num_ctx=config.ollama_num_ctx or 0,
                )
            )
    manifest["gate_outcome"] = (
        "AMD_PIPELINE_COMPLETED_AMCOR_ATTEMPTED"
        if amd["status"] == "completed"
        else "AMD_PIPELINE_INCOMPLETE_STOPPED"
    )
    return _finish(
        output=args.output,
        manifest=manifest,
        generator=generator,
        request_count=len(requests),
    )


def _validate_gate(clean_run: Path, gate_path: Path) -> tuple[dict[str, Any], int]:
    clean_manifest = _load(clean_run / "manifest.json")
    if clean_manifest.get("status") != "complete":
        raise ValueError("Clean gate run is incomplete")
    records = read_jsonl(clean_run / "records.jsonl")
    amd = next((row for row in records if row["condition"] == "amd_clean"), None)
    if not amd or amd.get("status") != "completed":
        raise ValueError("AMD clean pipeline did not complete")
    gate = _load(gate_path)
    if (
        gate.get("status") != "SOURCE_AUDITED_PASS"
        or gate.get("question_id") != AMD_QID
        or gate.get("clean_run_manifest_sha256")
        != sha256((clean_run / "manifest.json").read_bytes())
        or any(gate.get("dimensions", {}).get(key) != "PASS" for key in GATE_DIMENSIONS)
    ):
        raise ValueError("AMD semantic source-audit gate did not pass every dimension")
    return gate, int(clean_manifest["cumulative_v1_5_model_calls"])


def run_repairs(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise ValueError("Output exists; v1.5 runs are append-only")
    plan = preflight(
        data_dir=args.data_dir,
        parser_dir=args.parser_dir,
        spec_path=args.spec,
        config_path=args.config,
        max_calls=args.max_calls,
    )
    if not plan["repair_eligible"]:
        raise ValueError(plan["repair_reason"])
    gate, prior_calls = _validate_gate(args.clean_run, args.amd_gate)
    if prior_calls + 10 > NORMAL_PATH_CALLS or prior_calls + 10 > HARD_CALL_LIMIT:
        raise ValueError("Frozen repair phase exceeds the normal or hard call budget")
    root = Path(__file__).resolve().parents[1]
    git_state = _git_state(root, [*_tracked(root, args.spec, args.config), args.amd_gate.resolve()])
    spec = _load(args.spec)
    questions, pages = _inputs(args.data_dir, args.parser_dir, spec)
    config = RunnerConfig.load(args.config)
    args.output.mkdir(parents=True)
    manifest = _base_manifest(
        phase="amd_repair_states",
        args=args,
        plan=plan,
        git_state=git_state,
        prior_calls=prior_calls,
    )
    manifest.update(
        {
            "clean_run_manifest_sha256": sha256((args.clean_run / "manifest.json").read_bytes()),
            "amd_gate_sha256": sha256(args.amd_gate.read_bytes()),
            "amd_gate_status": gate["status"],
        }
    )
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "frozen_spec.json", spec)
    write_json(args.output / "frozen_config.json", _load(args.config))
    write_json(args.output / "frozen_amd_gate.json", gate)
    write_json(args.output / "model_inventory.json", _inventory(config))
    generator = BudgetedOllamaGenerator(
        config,
        args.output / "calls",
        HARD_CALL_LIMIT,
        initial_call_count=prior_calls,
    )
    requests = []
    with (args.output / "inputs.jsonl").open("x") as input_stream, (
        args.output / "records.jsonl"
    ).open("x") as record_stream:
        for state, restored in REPAIR_STATES.items():
            blocks, labels = build_amd_repair_state(pages[AMD_QID], restored)
            requests.append(
                _execute_request(
                    condition=f"amd_repair:{state}",
                    question=questions[AMD_QID],
                    blocks=blocks,
                    generator=generator,
                    input_stream=input_stream,
                    record_stream=record_stream,
                    num_ctx=config.ollama_num_ctx or 0,
                    repair_target_state=labels,
                )
            )
    return _finish(
        output=args.output,
        manifest=manifest,
        generator=generator,
        request_count=len(requests),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run-clean", "run-repairs"):
        child = sub.add_parser(name)
        child.add_argument("--data-dir", type=Path, required=True)
        child.add_argument("--parser-dir", type=Path, required=True)
        child.add_argument("--spec", type=Path, required=True)
        child.add_argument("--config", type=Path, required=True)
        child.add_argument("--max-calls", type=int, default=HARD_CALL_LIMIT)
        if name != "preflight":
            child.add_argument("--output", type=Path, required=True)
        if name == "run-repairs":
            child.add_argument("--clean-run", type=Path, required=True)
            child.add_argument("--amd-gate", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        result = preflight(
            data_dir=args.data_dir,
            parser_dir=args.parser_dir,
            spec_path=args.spec,
            config_path=args.config,
            max_calls=args.max_calls,
        )
    elif args.command == "run-clean":
        result = run_clean(args)
    else:
        result = run_repairs(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
