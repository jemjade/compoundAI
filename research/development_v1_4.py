"""Run the frozen 7-question parser × calculator development diagnostic."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from uuid import uuid4

from research.budgeted_ollama import BudgetedOllamaGenerator
from research.calculator_qa import run_calculator_qa
from research.canonical_adapter import canonical_to_blocks
from research.pilot import digest, read_jsonl, sha256, write_json
from research.pipeline_runner import RunnerConfig, run_pipeline

SPEC_STATUS = "FROZEN_DEVELOPMENT_DIAGNOSTIC"
REPAIR_QID = "financebench_id_00222"
REPAIR_STATES: dict[str, tuple[str, ...]] = {
    "damaged_baseline": (),
    "damaged_no_op_fresh": (),
    "A_only": ("A",),
    "B_only": ("B",),
    "A_plus_B": ("A", "B"),
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _git_state(root: Path, tracked: list[Path]) -> dict[str, Any]:
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("Live v1.4 execution requires a clean tracked worktree")
    for path in tracked:
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.relative_to(root))],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    hashes = {
        str(path.relative_to(root)): sha256(path.read_bytes()) for path in tracked
    }
    return {
        "git_commit": commit,
        "git_tracked_files_dirty": False,
        "code_sha256": digest(hashes),
        "code_files_sha256": hashes,
    }


def _load_questions(data_dir: Path, spec: dict[str, Any]) -> list[dict[str, str]]:
    wanted = [row["question_id"] for row in spec["questions"]]
    by_id = {
        row["question_id"]: row
        for row in read_jsonl(data_dir / "inputs/questions.jsonl")
    }
    if set(wanted) - set(by_id):
        raise ValueError("Frozen questions are absent from the development snapshot")
    return [
        {key: by_id[qid][key] for key in ("question_id", "document_id", "question")}
        for qid in wanted
    ]


def _load_pypdf_pages(
    data_dir: Path, questions: list[dict[str, str]], spec: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    page_by_qid = {row["question_id"]: row["page"] for row in spec["questions"]}
    blocks = read_jsonl(data_dir / "inputs/blocks.jsonl")
    by_key = {(row["document_id"], row["page_number"]): row for row in blocks}
    return {
        qid: [by_key[(question["document_id"], page_by_qid[qid])]]
        for qid, question in ((row["question_id"], row) for row in questions)
    }


def _load_docling_pages(
    parser_dir: Path, questions: list[dict[str, str]], spec: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    page_by_qid = {row["question_id"]: row["page"] for row in spec["questions"]}
    result: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        qid = question["question_id"]
        page = page_by_qid[qid]
        path = parser_dir / "canonical" / f"{question['document_id']}-p{page}.json"
        canonical = _load(path)
        blocks = canonical_to_blocks(canonical)
        if not blocks or {row["page_number"] for row in blocks} != {page}:
            raise ValueError(f"Docling canonical page mismatch for {qid}")
        result[qid] = blocks
    return result


def _payload(question: dict[str, str], blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repeat_id": 0,
        "blocks": blocks,
        "questions": [question],
    }


def _table_text(cells: list[dict[str, Any]]) -> str:
    rows = max((cell["row"] + cell.get("row_span", 1) for cell in cells), default=0)
    columns = max(
        (cell["column"] + cell.get("column_span", 1) for cell in cells), default=0
    )
    grid = [["" for _ in range(columns)] for _ in range(rows)]
    for cell in cells:
        grid[cell["row"]][cell["column"]] = cell.get("text", "")
    return "\n".join(" | ".join(row) for row in grid)


def build_amd_repair_state(
    clean: list[dict[str, Any]], restored: tuple[str, ...]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Corrupt two exact 2022 cells, then apply only the named ideal restorations."""
    blocks = copy.deepcopy(clean)
    definitions = {
        "A": ("Cash and cash equivalents", "4,835", "835"),
        "B": ("Accounts receivable, net", "4,126", "126"),
    }
    matches: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for label, (row_name, clean_value, _damaged) in definitions.items():
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for block in blocks:
            cells = block.get("cells", [])
            for cell in cells:
                cell_text = cell.get("text", "")
                if not isinstance(cell_text, str) or cell_text.count(clean_value) != 1:
                    continue
                same_row = [
                    other.get("text", "")
                    for other in cells
                    if other.get("row") == cell.get("row")
                ]
                same_col = [
                    other.get("text", "")
                    for other in cells
                    if other.get("column") == cell.get("column")
                ]
                if row_name in same_row and any("2022" in value for value in same_col):
                    candidates.append((block, cell))
        if len(candidates) != 1:
            raise ValueError(
                f"Docling repair target {label} was not unambiguous: {len(candidates)}"
            )
        matches[label] = candidates[0]
    labels: dict[str, Any] = {}
    for label, (_row_name, clean_value, damaged) in definitions.items():
        block, cell = matches[label]
        replacement = clean_value if label in restored else damaged
        cell["text"] = cell["text"].replace(clean_value, replacement, 1)
        labels[label] = {
            "block_id": block["block_id"],
            "cell_id": cell["id"],
            "row": cell["row"],
            "column": cell["column"],
            "observed_text": cell["text"],
            "restored": label in restored,
        }
    for block, _cell in matches.values():
        block["text"] = _table_text(block["cells"])
    return blocks, labels


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
        or spec.get("frozen_before_comparison_run") is not True
    ):
        raise ValueError("v1.4 spec is not frozen")
    if (
        spec["live_call_budget"]["expected_max"] != 52
        or spec["live_call_budget"]["hard_max_including_failures_and_retries"] != 60
    ):
        raise ValueError("Frozen call plan changed")
    if max_calls != 60:
        raise ValueError("v1.4 hard call limit must be exactly 60")
    config = RunnerConfig.load(config_path)
    if (
        config.model != "llama3:latest"
        or config.max_retries != 0
        or config.synthesis_mode != "passthrough"
    ):
        raise ValueError("Frozen local model settings changed")
    questions = _load_questions(data_dir, spec)
    pypdf = _load_pypdf_pages(data_dir, questions, spec)
    docling = _load_docling_pages(parser_dir, questions, spec)
    repair_eligible = True
    repair_reason = "unambiguous Docling 2022 Cash and Accounts receivable cells"
    try:
        build_amd_repair_state(docling[REPAIR_QID], ())
    except ValueError as error:
        repair_eligible = False
        repair_reason = str(error)
    base_calls = len(questions) * (1 + 2 + 1 + 2)
    repair_calls = 10 if repair_eligible else 0
    return {
        "execution_mode": "preflight_no_model_calls",
        "question_count": len(questions),
        "condition_count": 4,
        "base_calls": base_calls,
        "repair_eligible": repair_eligible,
        "repair_reason": repair_reason,
        "repair_calls": repair_calls,
        "expected_calls": base_calls + repair_calls,
        "hard_limit": max_calls,
        "within_budget": base_calls + repair_calls <= max_calls,
        "pypdf_block_count": sum(len(rows) for rows in pypdf.values()),
        "docling_block_count": sum(len(rows) for rows in docling.values()),
        "model": config.model,
        "config": config.public_dict(),
    }


def _inventory(config: RunnerConfig) -> dict[str, Any]:
    with urlopen(
        f"{config.base_url.rstrip('/')}/api/version", timeout=config.timeout_seconds
    ) as response:
        version = json.loads(response.read())
    with urlopen(
        f"{config.base_url.rstrip('/')}/api/tags", timeout=config.timeout_seconds
    ) as response:
        tags = json.loads(response.read())
    return {"version": version, "tags": tags}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise ValueError("Output exists; v1.4 runs are append-only")
    plan = preflight(
        data_dir=args.data_dir,
        parser_dir=args.parser_dir,
        spec_path=args.spec,
        config_path=args.config,
        max_calls=args.max_calls,
    )
    if not plan["within_budget"] or plan["base_calls"] != 42:
        raise ValueError("Frozen v1.4 preflight failed")
    root = Path(__file__).resolve().parents[1]
    tracked = [
        args.spec.resolve(),
        args.config.resolve(),
        root / "research/development_v1_4.py",
        root / "research/calculator_qa.py",
        root / "research/budgeted_ollama.py",
        root / "research/pipeline_runner.py",
    ]
    git_state = _git_state(root, tracked)
    spec = _load(args.spec)
    questions = _load_questions(args.data_dir, spec)
    pypdf = _load_pypdf_pages(args.data_dir, questions, spec)
    docling = _load_docling_pages(args.parser_dir, questions, spec)
    config = RunnerConfig.load(args.config)
    args.output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "status": "running",
        "run_id": str(uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "oracle_page_development_diagnostic_not_RAG",
        "call_plan": plan,
        "spec_sha256": sha256(args.spec.read_bytes()),
        "config_sha256": sha256(args.config.read_bytes()),
        "parser_manifest_sha256": sha256(
            (args.parser_dir / "manifest.json").read_bytes()
        ),
        "backup_status": "primary persistent project path; independent physical backup unverified",
        **git_state,
    }
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "frozen_spec.json", spec)
    write_json(args.output / "frozen_config.json", _load(args.config))
    write_json(args.output / "model_inventory.json", _inventory(config))
    generator = BudgetedOllamaGenerator(config, args.output / "calls", args.max_calls)
    records_path = args.output / "records.jsonl"
    inputs_path = args.output / "inputs.jsonl"
    conditions = [
        ("pypdf_llm_v2", pypdf, "llm"),
        ("pypdf_calculator_v1", pypdf, "calculator"),
        ("docling_llm_v2", docling, "llm"),
        ("docling_calculator_v1", docling, "calculator"),
    ]
    execution_count = 0
    with inputs_path.open("x") as input_stream, records_path.open("x") as record_stream:
        for condition, source, mode in conditions:
            for question in questions:
                qid = question["question_id"]
                blocks = source[qid]
                safe_question = {
                    key: question[key]
                    for key in ("question_id", "document_id", "question")
                }
                input_row = {
                    "condition": condition,
                    "question": safe_question,
                    "blocks": blocks,
                }
                input_stream.write(json.dumps(input_row, ensure_ascii=False) + "\n")
                input_stream.flush()
                record: dict[str, Any] = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "question_id": qid,
                    "document_id": question["document_id"],
                    "source_state": "clean",
                    "evidence_route": "frozen_oracle_source_page",
                    "input_sha256": digest(input_row),
                    "pipeline": mode,
                }
                before = generator.call_count
                try:
                    if mode == "llm":
                        payload = _payload(safe_question, blocks)
                        response = run_pipeline(
                            payload,
                            config,
                            generator,
                            forced_evidence_block_ids=tuple(
                                row["block_id"] for row in blocks
                            ),
                        )
                    else:
                        response = run_calculator_qa(
                            question=safe_question, blocks=blocks, generator=generator
                        )
                    record.update(
                        {
                            "status": "completed",
                            "response": response,
                            "output_sha256": digest(response),
                        }
                    )
                except Exception as error:  # noqa: BLE001 - every live failure is a result row
                    record.update(
                        {
                            "status": "failed",
                            "failure_type": type(error).__name__,
                            "failure_message": str(error),
                        }
                    )
                record["actual_call_count"] = generator.call_count - before
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
                execution_count += 1
        if plan["repair_eligible"]:
            question = next(
                row for row in questions if row["question_id"] == REPAIR_QID
            )
            for state, restored in REPAIR_STATES.items():
                blocks, target_state = build_amd_repair_state(
                    docling[REPAIR_QID], restored
                )
                input_row = {
                    "condition": f"amd_repair:{state}",
                    "question": question,
                    "blocks": blocks,
                    "repair_target_state": target_state,
                }
                input_stream.write(json.dumps(input_row, ensure_ascii=False) + "\n")
                input_stream.flush()
                record = {
                    "execution_id": str(uuid4()),
                    "condition": f"amd_repair:{state}",
                    "question_id": REPAIR_QID,
                    "document_id": question["document_id"],
                    "source_state": state,
                    "evidence_route": "frozen_oracle_source_page",
                    "input_sha256": digest(input_row),
                    "pipeline": "calculator",
                    "repair_target_state": target_state,
                }
                before = generator.call_count
                try:
                    response = run_calculator_qa(
                        question=question, blocks=blocks, generator=generator
                    )
                    record.update(
                        {
                            "status": "completed",
                            "response": response,
                            "output_sha256": digest(response),
                        }
                    )
                except Exception as error:  # noqa: BLE001 - every live failure is a result row
                    record.update(
                        {
                            "status": "failed",
                            "failure_type": type(error).__name__,
                            "failure_message": str(error),
                        }
                    )
                record["actual_call_count"] = generator.call_count - before
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
                execution_count += 1
    manifest.update(
        {
            "status": "complete",
            "finished_at": datetime.now(UTC).isoformat(),
            "completed_model_calls": generator.call_count,
            "completed_pipeline_executions": execution_count,
            "inputs_sha256": sha256(inputs_path.read_bytes()),
            "records_sha256": sha256(records_path.read_bytes()),
            "provider_runtime": generator.provider_runtime,
        }
    )
    write_json(args.output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run"):
        child = sub.add_parser(name)
        child.add_argument("--data-dir", type=Path, required=True)
        child.add_argument("--parser-dir", type=Path, required=True)
        child.add_argument("--spec", type=Path, required=True)
        child.add_argument("--config", type=Path, required=True)
        child.add_argument("--max-calls", type=int, default=60)
        if name == "run":
            child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = (
        preflight(
            data_dir=args.data_dir,
            parser_dir=args.parser_dir,
            spec_path=args.spec,
            config_path=args.config,
            max_calls=args.max_calls,
        )
        if args.command == "preflight"
        else run(args)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
