"""Prepare real PDF inputs and measure paired repairs without exposing evaluation labels.

The executable runner contract remains separate from reference answers and scoring.  A concrete
implementation of that contract lives in :mod:`research.pipeline_runner`.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

FINANCEBENCH_COMMIT = "cc39aeb4afdf33909ee1412188bf89035950c2eb"
DEFAULT_DOCUMENTS = ["BOEING_2022_10K", "AMCOR_2023_10K", "BESTBUY_2023_10K"]
CONDITIONS = {"baseline": (), "no_op": (), "A": ("A",), "B": ("B",), "AB": ("A", "B")}
SAFE_BLOCK_FIELDS = (
    "block_id",
    "document_id",
    "page_number",
    "text",
    "source_kind",
    "run_id",
    "canonical_block_id",
    "block_type",
    "reading_order",
    "bbox",
    "parser_name",
    "parser_version",
    "page_width",
    "page_height",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def evidence_doc(evidence: dict[str, Any]) -> str:
    """The released JSON uses doc_name; the README also documents evidence_doc_name."""
    first = evidence.get("doc_name")
    second = evidence.get("evidence_doc_name")
    if first and second and first != second:
        raise ValueError("Conflicting evidence document identifiers")
    value = first or second
    if not isinstance(value, str) or not value:
        raise ValueError("Evidence document identifier is missing")
    return value


def select_questions(
    rows: list[dict[str, Any]], documents: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """A single-document pilot; exclusion is explicit and independent of model outcomes."""
    chosen, excluded = [], []
    ids: set[str] = set()
    for row in rows:
        question_id = row["financebench_id"]
        if question_id in ids:
            raise ValueError(f"Duplicate question ID: {question_id}")
        ids.add(question_id)
        if row["doc_name"] not in documents:
            continue
        evidence = row.get("evidence", [])
        if not evidence or any(
            evidence_doc(item) != row["doc_name"] for item in evidence
        ):
            excluded.append(
                {"question_id": question_id, "reason": "not_single_document"}
            )
            continue
        chosen.append(row)
    missing = set(documents) - {row["doc_name"] for row in chosen}
    if missing:
        raise ValueError(f"No eligible questions for: {sorted(missing)}")
    return chosen, excluded


def prepare(source: Path, out: Path, documents: list[str]) -> dict[str, Any]:
    """Read complete PDFs, never annotation-provided evidence text, to form model inputs."""
    import pypdf

    if out.exists():
        raise ValueError(
            "Output already exists; use a new directory to preserve the snapshot"
        )
    if len(documents) != len(set(documents)):
        raise ValueError("Document IDs must be unique")
    question_path = source / "data/financebench_open_source.jsonl"
    rows, excluded = select_questions(read_jsonl(question_path), documents)
    blocks, document_records = [], []
    page_counts: dict[str, int] = {}
    for document in documents:
        if Path(document).name != document or not document:
            raise ValueError("Invalid document name")
        pdf = source / "pdfs" / f"{document}.pdf"
        pdf_bytes = pdf.read_bytes()
        pdf_sha256 = sha256(pdf_bytes)
        parser_run_id = f"pypdf-{pypdf.__version__}-{pdf_sha256[:16]}"
        reader = pypdf.PdfReader(pdf)
        page_counts[document] = len(reader.pages)
        empty_pages = []
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if not text.strip():
                empty_pages.append(index + 1)
            blocks.append(
                {
                    "block_id": f"{document}:p{index + 1}",
                    "document_id": document,
                    "page_number": index + 1,
                    "text": text,
                    "source_kind": "pypdf_page_text",
                    "run_id": parser_run_id,
                    "parser_name": "pypdf",
                    "parser_version": pypdf.__version__,
                }
            )
        document_records.append(
            {
                "document_id": document,
                "run_id": parser_run_id,
                "pdf_path": str(pdf.resolve()),
                "pdf_sha256": pdf_sha256,
                "page_count": len(reader.pages),
                "empty_text_pages": empty_pages,
            }
        )
    questions, gold = [], []
    for row in rows:
        questions.append(
            {
                "question_id": row["financebench_id"],
                "document_id": row["doc_name"],
                "question": row["question"],
            }
        )
        evidence = []
        for item in row["evidence"]:
            doc = evidence_doc(item)
            page = item["evidence_page_num"]
            if type(page) is not int or not 0 <= page < page_counts[doc]:
                raise ValueError(
                    f"Invalid ZERO-based evidence page for {row['financebench_id']}"
                )
            evidence.append(
                {
                    "block_id": f"{doc}:p{page + 1}",
                    "page_number": page + 1,
                    "evidence_text": item["evidence_text"],
                }
            )
        gold.append(
            {
                "question_id": row["financebench_id"],
                "reference_answer": row["answer"],
                "evidence": evidence,
            }
        )
    manifest = {
        "schema_version": 1,
        "purpose": "pipeline_debugging_pilot_not_representative_evaluation",
        "dataset": "FinanceBench public 150-question release",
        "source_url": "https://github.com/patronus-ai/financebench",
        "expected_source_commit": FINANCEBENCH_COMMIT,
        "question_file_sha256": sha256(question_path.read_bytes()),
        "license_card": "https://huggingface.co/datasets/PatronusAI/financebench",
        "license_as_declared_by_publisher": "CC-BY-NC-4.0",
        "citation": "Islam et al. (2023). FinanceBench. arXiv:2311.11944.",
        "parser": f"pypdf {pypdf.__version__} extract_text; page-level text baseline",
        "selection": "explicit documents; single-document questions; no outcome-based selection",
        "split": "pilot_only; no train/test claims or learned allocation",
        "annotation_page_index": "zero_based_converted_to_one_based",
        "question_count": len(questions),
        "block_count": len(blocks),
        "excluded_questions": excluded,
        "documents": document_records,
        "inputs_sha256": digest({"blocks": blocks, "questions": questions}),
        "created_at": datetime.now(UTC).isoformat(),
    }
    out.mkdir(parents=True)
    write_jsonl(out / "inputs/blocks.jsonl", blocks)
    write_jsonl(out / "inputs/questions.jsonl", questions)
    write_jsonl(out / "evaluation/gold.jsonl", gold)
    write_json(out / "manifest.json", manifest)
    return manifest


def validate_case(case: dict[str, Any]) -> None:
    if case.get("schema_version") != 1 or not isinstance(case.get("case_id"), str):
        raise ValueError("A schema_version=1 and case_id are required")
    blocks, questions = case.get("blocks", []), case.get("questions", [])
    if not blocks or not questions:
        raise ValueError("A case needs blocks and questions")
    block_ids = [block["block_id"] for block in blocks]
    question_ids = [row["question_id"] for row in questions]
    if len(set(block_ids)) != len(block_ids) or len(set(question_ids)) != len(
        question_ids
    ):
        raise ValueError("Duplicate block or question identifiers")
    for block in blocks:
        if not isinstance(block["text"], str) or not isinstance(
            block["document_id"], str
        ):
            raise ValueError("Invalid block text or document identifier")
        if type(block["page_number"]) is not int or block["page_number"] < 1:
            raise ValueError("Page numbers are one-based positive integers")
        if "source_kind" in block and block["source_kind"] not in {
            "pypdf_page_text",
            "canonical_parser",
        }:
            raise ValueError("Unknown block source_kind")
    docs = {block["document_id"] for block in blocks}
    if len(docs) != 1 or any(row["document_id"] not in docs for row in questions):
        raise ValueError("The initial paired-repair case must use one document")
    if any(not isinstance(row["question"], str) for row in questions):
        raise ValueError("Questions must be strings")
    repairs = case.get("repairs", [])
    if len(repairs) != 2 or {r["candidate_id"] for r in repairs} != {"A", "B"}:
        raise ValueError("Exactly two candidates named A and B are required")
    mapping = {block["block_id"]: block for block in blocks}
    intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for repair in repairs:
        if repair["block_id"] not in mapping:
            raise ValueError("Unknown repair block")
        text = mapping[repair["block_id"]]["text"]
        start, end = repair["start"], repair["end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(text)
        ):
            raise ValueError("Repair offsets must refer to a nonempty original span")
        if text[start:end] != repair["before"]:
            raise ValueError("Repair before-text does not match the frozen base input")
        if not isinstance(repair["after"], str) or repair["after"] == repair["before"]:
            raise ValueError("A repair must change the selected text")
        if (
            not isinstance(repair.get("source_note"), str)
            or not repair["source_note"].strip()
        ):
            raise ValueError("Record how the source was checked in source_note")
        for previous_start, previous_end in intervals[repair["block_id"]]:
            if max(previous_start, start) < min(previous_end, end):
                raise ValueError(
                    "Overlapping patches have ambiguous simultaneous semantics"
                )
        intervals[repair["block_id"]].append((start, end))


def repaired_blocks(
    case: dict[str, Any], selected: tuple[str, ...]
) -> list[dict[str, Any]]:
    validate_case(case)
    if set(selected) - {"A", "B"}:
        raise ValueError("Unknown repair candidate")
    # Explicit whitelist: references, labels, and repair targets never cross this boundary.
    blocks = [{k: b[k] for k in SAFE_BLOCK_FIELDS if k in b} for b in case["blocks"]]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repair in case["repairs"]:
        if repair["candidate_id"] in selected:
            grouped[repair["block_id"]].append(repair)
    for block in blocks:
        for repair in sorted(
            grouped[block["block_id"]], key=lambda r: r["start"], reverse=True
        ):
            block["text"] = (
                block["text"][: repair["start"]]
                + repair["after"]
                + block["text"][repair["end"] :]
            )
    return blocks


def runner_payload(
    case: dict[str, Any], selected: tuple[str, ...], repeat: int
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repeat_id": repeat,
        "blocks": repaired_blocks(case, selected),
        "questions": [
            {k: row[k] for k in ("question_id", "document_id", "question")}
            for row in case["questions"]
        ],
    }


def injected_case(case: dict[str, Any]) -> dict[str, Any]:
    """Treat the two supplied edits as corruptions; construct exact inverse repair offsets.

    Restoration targets are parser-extracted baseline spans, not independently verified
    ground truth for the whole document. Record source checks in the supplied notes.
    """
    validate_case(case)
    output = copy.deepcopy(case)
    output["blocks"] = repaired_blocks(case, ("A", "B"))
    output["intervention_mode"] = "controlled_corruption_restore_parser_baseline"
    output["pre_corruption_blocks_sha256"] = digest(case["blocks"])
    inverse = []
    for edit in case["repairs"]:
        if not edit["after"]:
            raise ValueError(
                "Injection must leave a nonempty span to anchor its inverse repair"
            )
        shift = sum(
            len(other["after"]) - len(other["before"])
            for other in case["repairs"]
            if other["block_id"] == edit["block_id"] and other["end"] <= edit["start"]
        )
        start = edit["start"] + shift
        inverse.append(
            {
                **edit,
                "start": start,
                "end": start + len(edit["after"]),
                "before": edit["after"],
                "after": edit["before"],
            }
        )
    output["repairs"] = inverse
    validate_case(output)
    return output


def validate_response(response: dict[str, Any], payload: dict[str, Any]) -> None:
    if not isinstance(response, dict):
        raise ValueError("Runner output must be a JSON object")
    metadata = response.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ValueError("Runner metadata must be an object")
        if "status" in metadata and metadata["status"] != "completed":
            raise ValueError("Runner metadata does not report a completed response")
        if metadata.get("status", "completed") != "completed":
            raise ValueError("Incomplete or failed model output cannot be accepted")
        call_count = metadata.get("call_count")
        if call_count is not None and (type(call_count) is not int or call_count < 1):
            raise ValueError("Runner call_count must be a positive integer")
    answers = response.get("answers")
    if not isinstance(answers, list):
        raise ValueError("Runner must return an answers array")
    expected = {row["question_id"] for row in payload["questions"]}
    found = [row["question_id"] for row in answers]
    if len(found) != len(set(found)) or set(found) != expected:
        raise ValueError("Runner must return every question exactly once")
    known_blocks = {block["block_id"] for block in payload["blocks"]}
    for answer in answers:
        if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
            raise ValueError("Runner answers must be nonempty strings")
        cited = answer.get("evidence_block_ids", [])
        if not isinstance(cited, list) or not all(isinstance(x, str) for x in cited):
            raise ValueError("Evidence IDs must be a list of strings")
        if set(cited) - known_blocks:
            raise ValueError("Runner cited unknown block IDs")


def run_case(
    case: dict[str, Any],
    command: list[str],
    out: Path,
    repeats: int = 2,
    timeout: float = 120,
) -> dict[str, Any]:
    validate_case(case)
    if not command or repeats < 1 or timeout <= 0 or not math.isfinite(timeout):
        raise ValueError(
            "An executable runner, positive repeats and finite timeout are required"
        )
    out.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "case_id": case["case_id"],
        "case_sha256": digest(case),
        "run_id": str(uuid4()),
        "status": "running",
        "repeats": repeats,
        "expected_calls": repeats * len(CONDITIONS),
        "completed_calls": 0,
        "completed_model_calls": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "runner_command": command,
        "timeout_seconds": timeout,
        "scoring": "not_scored; independent judgments required",
        "notes": "No cross-condition response cache. All five conditions execute independently.",
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "frozen_case.json", case)
    try:
        with (out / "records.jsonl").open("x") as stream:
            for repeat in range(repeats):
                conditions = list(CONDITIONS)
                # Reproducible shuffled order helps avoid always placing AB last in time.
                random.Random(f"{digest(case)}:{repeat}").shuffle(conditions)
                for condition in conditions:
                    payload = runner_payload(case, CONDITIONS[condition], repeat)
                    manifest["active_call"] = {
                        "repeat_id": repeat,
                        "condition": condition,
                    }
                    write_json(out / "manifest.json", manifest)
                    result = subprocess.run(
                        command,
                        input=json.dumps(payload),
                        text=True,
                        capture_output=True,
                        timeout=timeout,
                        check=False,
                    )
                    if result.returncode:
                        raise RuntimeError(
                            f"Runner exited with code {result.returncode}"
                        )
                    response = json.loads(result.stdout)
                    validate_response(response, payload)
                    metadata = response.get("metadata", {})
                    usage = (
                        metadata.get("usage", {}) if isinstance(metadata, dict) else {}
                    )
                    record = {
                        "execution_id": str(uuid4()),
                        "case_id": case["case_id"],
                        "repeat_id": repeat,
                        "condition": condition,
                        "input_sha256": digest(payload),
                        "output_sha256": digest(response),
                        "response": response,
                    }
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                    stream.flush()
                    manifest["completed_calls"] += 1
                    model_calls = (
                        metadata.get("call_count", 0)
                        if isinstance(metadata, dict)
                        else 0
                    )
                    if type(model_calls) is int and model_calls >= 0:
                        manifest["completed_model_calls"] += model_calls
                    for key in ("input_tokens", "output_tokens", "total_tokens"):
                        value = usage.get(key, 0) if isinstance(usage, dict) else 0
                        if type(value) is int and value >= 0:
                            manifest["usage"][key] += value
                    write_json(out / "manifest.json", manifest)
        manifest["status"] = "complete"
        manifest.pop("active_call", None)
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["error_type"] = "KeyboardInterrupt"
        raise
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error_type"] = type(error).__name__
        raise
    finally:
        write_json(out / "manifest.json", manifest)
    return manifest


def judgment_id(record: dict[str, Any], question_id: str) -> str:
    return digest([record["execution_id"], question_id])


def load_complete_run(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("Cannot score an incomplete or failed run")
    case = json.loads((run / "frozen_case.json").read_text())
    if digest(case) != manifest["case_sha256"]:
        raise ValueError("Frozen case changed after execution")
    records = read_jsonl(run / "records.jsonl")
    expected = {
        (repeat, condition)
        for repeat in range(manifest["repeats"])
        for condition in CONDITIONS
    }
    actual = [(r["repeat_id"], r["condition"]) for r in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Missing or duplicate experimental conditions")
    if len({r["execution_id"] for r in records}) != len(records):
        raise ValueError("Duplicate execution IDs")
    for record in records:
        payload = runner_payload(
            case, CONDITIONS[record["condition"]], record["repeat_id"]
        )
        if digest(payload) != record["input_sha256"]:
            raise ValueError("Recorded input hash does not match the frozen case")
        if digest(record["response"]) != record["output_sha256"]:
            raise ValueError("Recorded output changed after execution")
        validate_response(record["response"], payload)
    return case, records


def judgment_template(
    run: Path, gold_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    case, records = load_complete_run(run)
    gold = {row["question_id"]: row for row in gold_rows}
    if len(gold) != len(gold_rows):
        raise ValueError("Duplicate reference question IDs")
    questions = {row["question_id"]: row["question"] for row in case["questions"]}
    if set(questions) - set(gold):
        raise ValueError("Reference answers are missing")
    rows = []
    for record in records:
        for answer in record["response"]["answers"]:
            qid = answer["question_id"]
            rows.append(
                {
                    "judgment_id": judgment_id(record, qid),
                    "question_id": qid,
                    "question": questions[qid],
                    "prediction": answer["answer"],
                    "reference_answer": gold[qid]["reference_answer"],
                    "reference_evidence": gold[qid].get("evidence", []),
                    "correct": None,
                    "judge_id": "",
                    "rationale": "",
                }
            )
    # No condition/repeat/model labels appear in this file.
    return sorted(rows, key=lambda row: row["judgment_id"])


def score(run: Path, judgments: list[dict[str, Any]]) -> dict[str, Any]:
    case, records = load_complete_run(run)
    mapped = {row["judgment_id"]: row for row in judgments}
    if len(mapped) != len(judgments):
        raise ValueError("Duplicate judgments")
    expected_ids = {
        judgment_id(record, answer["question_id"])
        for record in records
        for answer in record["response"]["answers"]
    }
    if set(mapped) != expected_ids:
        raise ValueError(
            "Every prediction needs exactly one judgment; extra labels are rejected"
        )
    if any(
        type(row.get("correct")) is not bool or not str(row.get("judge_id", "")).strip()
        for row in judgments
    ):
        raise ValueError("Judgments need a boolean correct label and a judge_id")
    correctness = {}
    for record in records:
        correctness[(record["repeat_id"], record["condition"])] = {
            answer["question_id"]: mapped[judgment_id(record, answer["question_id"])][
                "correct"
            ]
            for answer in record["response"]["answers"]
        }
    output_rows = []
    for repeat in sorted({r["repeat_id"] for r in records}):
        base = correctness[(repeat, "baseline")]
        values = {}
        for condition in CONDITIONS:
            current = correctness[(repeat, condition)]
            recovered = sorted(q for q in base if not base[q] and current[q])
            regressed = sorted(q for q in base if base[q] and not current[q])
            values[condition] = {
                "correct_count": sum(current.values()),
                "question_count": len(current),
                "accuracy": sum(current.values()) / len(current),
                "recovered_question_ids": recovered,
                "regressed_question_ids": regressed,
                "net_recovery": len(recovered) - len(regressed),
            }
        output_rows.append(
            {
                "repeat_id": repeat,
                "conditions": values,
                "interaction_count": (
                    values["AB"]["net_recovery"]
                    - values["A"]["net_recovery"]
                    - values["B"]["net_recovery"]
                ),
                "no_op_net_change": values["no_op"]["net_recovery"],
            }
        )
    return {
        "case_id": case["case_id"],
        "judgments_sha256": digest(judgments),
        "scope": "descriptive paired-repair pilot; no population CI or human-time claim",
        "interaction_definition": "G(AB)-G(A)-G(B), G(S)=correct(S)-correct(baseline)",
        "repeats": output_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source", type=Path, required=True)
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--documents", nargs="+", default=DEFAULT_DOCUMENTS)
    case_cmd = commands.add_parser("make-case")
    case_cmd.add_argument("--inputs", type=Path, required=True)
    case_cmd.add_argument("--repairs", type=Path, required=True)
    case_cmd.add_argument("--document", required=True)
    case_cmd.add_argument("--case-id", required=True)
    case_cmd.add_argument(
        "--inject",
        action="store_true",
        help="Supplied edits are corruptions; create inverse repairs",
    )
    case_cmd.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--case", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--repeats", type=int, default=2)
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("runner", nargs=argparse.REMAINDER)
    judge = commands.add_parser("judge-template")
    judge.add_argument("--run", type=Path, required=True)
    judge.add_argument("--gold", type=Path, required=True)
    judge.add_argument("--out", type=Path, required=True)
    scoring = commands.add_parser("score")
    scoring.add_argument("--run", type=Path, required=True)
    scoring.add_argument("--judgments", type=Path, required=True)
    scoring.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output already exists; use a new path")
    if args.action == "prepare":
        result = prepare(args.source, args.out, args.documents)
        print(
            json.dumps(
                {k: result[k] for k in ("question_count", "block_count", "documents")}
            )
        )
    elif args.action == "make-case":
        case = {
            "schema_version": 1,
            "case_id": args.case_id,
            "blocks": [
                r
                for r in read_jsonl(args.inputs / "blocks.jsonl")
                if r["document_id"] == args.document
            ],
            "questions": [
                r
                for r in read_jsonl(args.inputs / "questions.jsonl")
                if r["document_id"] == args.document
            ],
            "repairs": json.loads(args.repairs.read_text()),
        }
        validate_case(case)
        if args.inject:
            case = injected_case(case)
        write_json(args.out, case)
    elif args.action == "run":
        command = args.runner[1:] if args.runner[:1] == ["--"] else args.runner
        result = run_case(
            json.loads(args.case.read_text()),
            command,
            args.out,
            repeats=args.repeats,
            timeout=args.timeout,
        )
        print(json.dumps(result))
    elif args.action == "judge-template":
        write_jsonl(args.out, judgment_template(args.run, read_jsonl(args.gold)))
    else:
        write_json(args.out, score(args.run, read_jsonl(args.judgments)))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Pilot stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
