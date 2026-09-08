"""Combine frozen v1.3 traces with explicit source-audited manual judgments."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from research.pilot import read_jsonl, sha256, write_json

EXPECTED_GENERAL = {
    "financebench_id_00799",
    "financebench_id_00684",
    "financebench_id_00685",
    "financebench_id_01275",
    "financebench_id_00222",
    "financebench_id_00563",
    "financebench_id_00757",
}
EXPECTED_REPAIR = {"damaged", "A_only", "B_only", "AB"}
ALLOWED_CONCLUSIONS = {"CORRECT", "INCORRECT", "MISSING_OR_UNDETERMINED"}
ALLOWED_NUMERIC = {
    "ALL_STATED_NUMBERS_CORRECT",
    "INCORRECT_NUMERIC_CLAIM",
    "NOT_APPLICABLE_NO_NUMBERS",
}
ALLOWED_EXPLANATIONS = {
    "COMPLETE",
    "PRESENT_BUT_INVALID",
    "MISSING_OR_INCOMPLETE",
    "NOT_REQUIRED_DIRECT_ANSWER",
}
ALLOWED_EVIDENCE = {
    "AVAILABLE_AND_SUPPORTS_ANSWER",
    "AVAILABLE_BUT_OUTPUT_UNSUPPORTED",
    "REQUIRED_EVIDENCE_NOT_RETRIEVED",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _answer_records(run_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for record in read_jsonl(run_dir / "records.jsonl"):
        retrievals = {
            trace["question_id"]: trace
            for trace in record["response"]["trace"]
            if trace.get("stage") == "retrieval"
        }
        for answer in record["response"]["answers"]:
            retrieval = retrievals[answer["question_id"]]
            rows.append(
                {
                    "condition": record["condition"],
                    "source_state": record["source_state"],
                    "evidence_route": record["evidence_route"],
                    "question_id": answer["question_id"],
                    "answer": answer["answer"],
                    "structured_output": answer["structured_output"],
                    "qa_contract_violations": answer.get("qa_contract_violations", []),
                    "cited_block_ids": answer["evidence_block_ids"],
                    "retrieved_block_ids": sorted(
                        {
                            block_id
                            for chunk in retrieval["output"]
                            for block_id in chunk["source_block_ids"]
                        }
                    ),
                    "pipeline_execution_id": record["response"]["metadata"][
                        "pipeline_execution_id"
                    ],
                }
            )
    return rows


def _validate_coverage(rows: list[dict[str, Any]]) -> None:
    if len(rows) != 18:
        raise ValueError("v1.3 must have exactly 18 answer records")
    general = {
        row["question_id"]
        for row in rows
        if row["condition"].startswith("clean_general:")
    }
    oracle = {
        row["question_id"]
        for row in rows
        if row["condition"].startswith("clean_oracle:")
    }
    repair = {
        row["source_state"]
        for row in rows
        if row["condition"].startswith("controlled_repair:")
    }
    if general != EXPECTED_GENERAL or oracle != EXPECTED_GENERAL or repair != EXPECTED_REPAIR:
        raise ValueError("v1.3 condition coverage is incomplete or duplicated")


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "answer_count": len(rows),
        "conclusion_correct": sum(row["conclusion_correctness"] == "CORRECT" for row in rows),
        "numeric_status": dict(Counter(row["stated_numeric_accuracy"] for row in rows)),
        "explanation_status": dict(
            Counter(row["required_explanation_completeness"] for row in rows)
        ),
        "evidence_status": dict(Counter(row["evidence_sufficiency"] for row in rows)),
        "contract_complete": sum(not row["qa_contract_violations"] for row in rows),
        "overall_task_correct": sum(row["overall_task_correct"] for row in rows),
    }


def evaluate(run_dir: Path, judgments_path: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Evaluation output exists; use a new append-only path")
    manifest = _load(run_dir / "manifest.json")
    if manifest.get("status") != "complete" or manifest.get("completed_model_calls") != 18:
        raise ValueError("Only the complete frozen v1.3 run may be evaluated")
    answers = _answer_records(run_dir)
    _validate_coverage(answers)
    judgments = _load(judgments_path)
    if judgments.get("source_audit") != "rendered_pdf_pages_checked":
        raise ValueError("Manual judgments must attest direct source audit")
    keyed = {
        (row["condition"], row["question_id"]): row for row in judgments["judgments"]
    }
    if len(keyed) != len(answers):
        raise ValueError("Manual judgments must cover every answer exactly once")
    merged = []
    for answer in answers:
        key = (answer["condition"], answer["question_id"])
        if key not in keyed:
            raise ValueError(f"Missing manual judgment for {key}")
        judgment = keyed[key]
        if judgment["conclusion_correctness"] not in ALLOWED_CONCLUSIONS:
            raise ValueError("Unknown conclusion judgment")
        if judgment["stated_numeric_accuracy"] not in ALLOWED_NUMERIC:
            raise ValueError("Unknown numeric judgment")
        if judgment["required_explanation_completeness"] not in ALLOWED_EXPLANATIONS:
            raise ValueError("Unknown explanation judgment")
        if judgment["evidence_sufficiency"] not in ALLOWED_EVIDENCE:
            raise ValueError("Unknown evidence judgment")
        merged.append({**answer, **judgment})
    general = [row for row in merged if row["condition"].startswith("clean_general:")]
    oracle = [row for row in merged if row["condition"].startswith("clean_oracle:")]
    repair = [row for row in merged if row["condition"].startswith("controlled_repair:")]
    result = {
        "schema_version": 1,
        "status": "POSTRUN_SOURCE_AUDITED_DEVELOPMENT_ANALYSIS",
        "run_id": manifest["run_id"],
        "run_manifest_sha256": sha256((run_dir / "manifest.json").read_bytes()),
        "records_sha256": sha256((run_dir / "records.jsonl").read_bytes()),
        "judgments_sha256": sha256(judgments_path.read_bytes()),
        "dimensions_independent": True,
        "clean_general": _aggregate(general),
        "clean_oracle": _aggregate(oracle),
        "controlled_repair": _aggregate(repair),
        "valid_required_page_retrieval": {
            "count": sum(
                row["evidence_sufficiency"] == "AVAILABLE_AND_SUPPORTS_ANSWER"
                or (
                    row["evidence_route"] == "general_bm25_document_isolated"
                    and row.get("valid_required_evidence_retrieved") is True
                )
                for row in general
            ),
            "denominator": len(general),
            "question_ids": sorted(
                row["question_id"]
                for row in general
                if row.get("valid_required_evidence_retrieved") is True
            ),
        },
        "repair_effect": {
            "fully_correct_states": [
                row["source_state"] for row in repair if row["overall_task_correct"]
            ],
            "recovered_by_A": False,
            "recovered_by_B": False,
            "recovered_by_AB": False,
            "interpretation": "no controlled state produced a correct ratio explanation; conclusion-only stability is not repair success",
        },
        "answers": merged,
    }
    write_json(out, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.run, args.judgments, args.out), indent=2))


if __name__ == "__main__":
    main()
