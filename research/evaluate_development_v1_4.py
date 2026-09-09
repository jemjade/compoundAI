"""Evaluate every frozen v1.4 row without dropping failures or the seventh question."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from research.pilot import read_jsonl, sha256, write_json

CONDITIONS = {
    "pypdf_llm_v2",
    "pypdf_calculator_v1",
    "docling_llm_v2",
    "docling_calculator_v1",
}
PRIMARY_EXCLUDED = "financebench_id_00685"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _failed_judgment(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "conclusion_correctness": "MISSING_OR_UNDETERMINED",
        "stated_numeric_accuracy": "NOT_APPLICABLE_NO_NUMBERS",
        "required_explanation_completeness": "MISSING_OR_INCOMPLETE",
        "evidence_sufficiency": "AVAILABLE_BUT_PIPELINE_FAILED",
        "overall_task_correct": False,
        "metric_selection": "NOT_EXECUTED_OR_INVALID",
        "source_value_selection": "NOT_EXECUTED_OR_INVALID",
        "row_period_unit_selection": "NOT_EXECUTED_OR_INVALID",
        "program_arithmetic": "NOT_EXECUTED",
        "answer_uses_program_result": "NOT_EXECUTED",
        "rationale": f"Fail-closed: {record.get('failure_message', 'unknown failure')}",
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "denominator": len(rows),
        "pipeline_completed": sum(row["status"] == "completed" for row in rows),
        "overall_task_correct": sum(row["overall_task_correct"] for row in rows),
        "conclusion_correctness": dict(
            Counter(row["conclusion_correctness"] for row in rows)
        ),
        "stated_numeric_accuracy": dict(
            Counter(row["stated_numeric_accuracy"] for row in rows)
        ),
        "required_explanation_completeness": dict(
            Counter(row["required_explanation_completeness"] for row in rows)
        ),
        "evidence_sufficiency": dict(
            Counter(row["evidence_sufficiency"] for row in rows)
        ),
        "tool_failure_dimensions": {
            key: dict(Counter(row[key] for row in rows))
            for key in (
                "metric_selection",
                "source_value_selection",
                "row_period_unit_selection",
                "program_arithmetic",
                "answer_uses_program_result",
            )
        },
    }


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    row = {
        key: record.get(key)
        for key in (
            "execution_id",
            "condition",
            "question_id",
            "document_id",
            "source_state",
            "evidence_route",
            "input_sha256",
            "output_sha256",
            "pipeline",
            "status",
            "actual_call_count",
            "failure_type",
            "failure_message",
            "repair_target_state",
        )
        if record.get(key) is not None
    }
    response = record.get("response")
    if not isinstance(response, dict):
        return row
    if record["pipeline"] == "llm":
        answer = response["answers"][0]
        row.update(
            {
                "answer_text": answer["answer"],
                "structured_output": answer["structured_output"],
                "evidence_block_ids": answer["evidence_block_ids"],
                "qa_contract_violations": answer.get("qa_contract_violations", []),
                "pipeline_execution_id": response["metadata"]["pipeline_execution_id"],
            }
        )
    else:
        row.update(
            {
                "answer_text": response["answer_text"],
                "plan": response["plan"],
                "calculation": response["calculation"],
                "dependency_edges": response["dependency_edges"],
            }
        )
    return row


def evaluate(run_dir: Path, judgments_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Evaluation output exists; use a new path")
    manifest = _load(run_dir / "manifest.json")
    if manifest.get("status") != "complete":
        raise ValueError("Only a complete v1.4 run can be evaluated")
    records = read_jsonl(run_dir / "records.jsonl")
    base = [row for row in records if row["condition"] in CONDITIONS]
    repair = [row for row in records if row["condition"].startswith("amd_repair:")]
    if len(base) != 28 or {row["condition"] for row in base} != CONDITIONS:
        raise ValueError("The 7 × 4 result grid is incomplete")
    per_condition = Counter(row["condition"] for row in base)
    if set(per_condition.values()) != {7}:
        raise ValueError("Each v1.4 condition must contain seven rows")
    if manifest["call_plan"]["repair_eligible"] and len(repair) != 5:
        raise ValueError("Eligible AMD repair diagnostic needs five fresh rows")
    judgments = _load(judgments_path)
    keyed = {
        (row["condition"], row["question_id"]): row
        for row in judgments.get("judgments", [])
    }
    completed_keys = {
        (row["condition"], row["question_id"])
        for row in records
        if row["status"] == "completed"
    }
    if set(keyed) != completed_keys:
        raise ValueError("Manual review must cover every and only completed response")
    merged = []
    for record in records:
        key = (record["condition"], record["question_id"])
        judgment = (
            keyed[key] if record["status"] == "completed" else _failed_judgment(record)
        )
        merged.append({**_compact_record(record), **judgment})
    aggregates = {}
    for condition in sorted(CONDITIONS):
        rows = [row for row in merged if row["condition"] == condition]
        aggregates[condition] = {
            "all_7": _aggregate(rows),
            "primary_6": _aggregate(
                [row for row in rows if row["question_id"] != PRIMARY_EXCLUDED]
            ),
        }
    repair_rows = [row for row in merged if row["condition"].startswith("amd_repair:")]
    result = {
        "schema_version": 1,
        "status": "POSTRUN_SOURCE_AUDITED_DEVELOPMENT_ANALYSIS",
        "scope": "oracle source-page diagnostic; retrieval excluded",
        "run_manifest_sha256": sha256((run_dir / "manifest.json").read_bytes()),
        "records_sha256": sha256((run_dir / "records.jsonl").read_bytes()),
        "judgments_sha256": sha256(judgments_path.read_bytes()),
        "completed_model_calls": manifest["completed_model_calls"],
        "hard_call_limit": manifest["call_plan"]["hard_limit"],
        "aggregates": aggregates,
        "amd_repair": _aggregate(repair_rows),
        "rows": merged,
    }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(args.run, args.judgments, args.output),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
