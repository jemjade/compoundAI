"""Aggregate the step-gated v1.5 run without converting missing stages to accuracy."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from research.pilot import read_jsonl, sha256, write_json

STAGES = (
    "planner_call",
    "format_validation",
    "reference_validation",
    "arithmetic_execution",
    "answerer_call",
    "answer_contract_validation",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _classify_call(path: Path) -> dict[str, Any]:
    row = _load(path)
    output_tokens = row.get("usage", {}).get("output_tokens")
    max_output = row.get("max_output_tokens")
    return {
        "call_index": row["call_index"],
        "stage": row["stage"],
        "status": row["status"],
        "input_characters": len(row.get("input_text", "")),
        "input_tokens": row.get("usage", {}).get("input_tokens"),
        "output_tokens": output_tokens,
        "max_output_tokens": max_output,
        "output_limit_reached": bool(
            row["status"] == "failed"
            and (row.get("raw_provider_response") or {}).get("done_reason") == "length"
            and output_tokens == max_output
        ),
        "input_context_limit_reached": bool(
            (row.get("raw_provider_response") or {}).get("prompt_eval_count") == 8191
        ),
        "raw_output_characters": len(row.get("raw_output", "")),
        "raw_output": row.get("raw_output"),
        "failure_message": row.get("failure_message"),
    }


def evaluate(
    *, clean_run: Path, source_audit_path: Path, output: Path
) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Evaluation output exists; v1.5 outputs are append-only")
    manifest = _load(clean_run / "manifest.json")
    if manifest.get("status") != "complete":
        raise ValueError("Clean run must be complete")
    records = read_jsonl(clean_run / "records.jsonl")
    if not records or records[0].get("condition") != "amd_clean":
        raise ValueError("Frozen v1.5 sequence must start with AMD clean")
    if records[0]["status"] != "completed" and len(records) != 1:
        raise ValueError("AMCOR must not run after an incomplete AMD request")
    audit = _load(source_audit_path)
    if audit.get("clean_run_manifest_sha256") != sha256(
        (clean_run / "manifest.json").read_bytes()
    ):
        raise ValueError("Source audit does not match the clean run")
    calls = [
        _classify_call(path)
        for path in sorted((clean_run / "calls").glob("call-*.json"))
    ]
    requested = len(records)
    completed = sum(row["status"] == "completed" for row in records)
    source_correct = int(bool(audit.get("overall_source_correct")))
    if len(records) > 1:
        raise ValueError("This evaluator requires a source audit per attempted row")
    stage_counts = {
        stage: dict(Counter(row.get("stage_status", {}).get(stage, "MISSING") for row in records))
        for stage in STAGES
    }
    planner_completed = sum(
        row.get("stage_status", {}).get("planner_call") == "COMPLETED"
        for row in records
    )
    arithmetic_completed = sum(
        row.get("stage_status", {}).get("arithmetic_execution") == "PASSED"
        for row in records
    )
    answerer_completed = sum(
        row.get("stage_status", {}).get("answerer_call") == "COMPLETED"
        for row in records
    )
    result = {
        "schema_version": 1,
        "status": "POSTRUN_SOURCE_AUDITED_DEVELOPMENT_ANALYSIS",
        "scope": "frozen oracle-source-page development diagnostic; not independent evaluation or RAG",
        "run_manifest_sha256": sha256((clean_run / "manifest.json").read_bytes()),
        "run_checksums_sha256": sha256((clean_run / "checksums.json").read_bytes()),
        "source_audit_sha256": sha256(source_audit_path.read_bytes()),
        "git_commit_at_run": manifest["git_commit"],
        "request_counts": {
            "requested": requested,
            "planner_completed": planner_completed,
            "calculator_completed": arithmetic_completed,
            "answerer_completed": answerer_completed,
            "pipeline_completed": completed,
        },
        "accuracy": {
            "whole_request": {"correct": source_correct, "denominator": requested},
            "completed_only": {
                "correct": source_correct if completed else None,
                "denominator": completed,
                "status": "MEASURED" if completed else "NOT_MEASURABLE_NO_COMPLETED_RESPONSES",
            },
        },
        "stage_status_counts": stage_counts,
        "failure_dimensions": {
            "metric_selection_error": int(audit["dimensions"]["metric_selection"] != "PASS"),
            "value_selection_error": int(audit["dimensions"]["value_selection"] != "PASS"),
            "period_or_unit_error": int(
                audit["dimensions"]["period_selection"] != "PASS"
                or audit["dimensions"]["unit_selection"] != "PASS"
            ),
            "arithmetic_error": int(audit["dimensions"]["arithmetic"] == "FAIL"),
            "arithmetic_not_executed": int(
                str(audit["dimensions"]["arithmetic"]).startswith("NOT_EXECUTED")
            ),
            "answer_error_or_missing": int(audit["dimensions"]["conclusion"] != "PASS"),
            "evidence_error": int(audit["dimensions"]["evidence"] != "PASS"),
        },
        "diagnosis": {
            "v1_4_preserved": {
                "whole_request_success": "0/7 per calculator condition",
                "completed_calculator_accuracy": "not measurable because denominator was 0",
            },
            "v1_5": {
                "input_context_overflow": False,
                "output_token_limit": False,
                "repetitive_unnecessary_output_observed": False,
                "nonexistent_or_undeclared_reference": True,
                "details": "The short planner finished in 147 output tokens, but steps referenced current sources not listed in its inputs. Even if accepted implicitly, the planned expression mixed periods and was not the selected quick-ratio definition.",
            },
        },
        "call_usage": {
            "actual_calls": len(calls),
            "input_tokens": sum(row.get("input_tokens") or 0 for row in calls),
            "output_tokens": sum(row.get("output_tokens") or 0 for row in calls),
            "hard_limit": manifest["hard_call_limit"],
            "normal_path_limit": manifest["normal_path_call_limit"],
        },
        "calls": calls,
        "source_audit": audit,
        "rows": records,
        "not_run_by_frozen_gate": [
            "AMCOR gross-margin clean",
            "AMD damaged baseline",
            "AMD damaged no-op fresh rerun",
            "AMD A-only repair",
            "AMD B-only repair",
            "AMD A+B repair",
        ] if records[0]["status"] != "completed" else [],
    }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-run", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(
                clean_run=args.clean_run,
                source_audit_path=args.source_audit,
                output=args.output,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
