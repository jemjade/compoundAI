"""Run and evaluate the frozen v1.2 QA evidence/output-contract diagnostic."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from research.allocation_pilot import _run_payload, _validate_live_response
from research.pilot import (
    digest,
    read_jsonl,
    runner_payload,
    sha256,
    validate_case,
    write_json,
)
from research.pipeline_runner import RunnerConfig

SPEC_STATUS = "FROZEN_DEVELOPMENT_DIAGNOSTIC"
ORACLE_BLOCK_ID = "BOEING_2022_10K:p55"
GROSS_QUESTION_ID = "financebench_id_00678"
TAX_QUESTION_ID = "financebench_id_00585"
CONDITIONS = {
    "flat_old_prompt_damaged": {
        "repairs": (),
        "representation": "flat_extracted_text",
        "contract": "concise_v1",
    },
    "flat_old_prompt_repaired": {
        "repairs": ("A", "B"),
        "representation": "flat_extracted_text",
        "contract": "concise_v1",
    },
    "flat_quantitative_prompt_damaged": {
        "repairs": (),
        "representation": "flat_extracted_text",
        "contract": "quantitative_v2",
    },
    "flat_quantitative_prompt_repaired": {
        "repairs": ("A", "B"),
        "representation": "flat_extracted_text",
        "contract": "quantitative_v2",
    },
    "table_quantitative_prompt_damaged": {
        "repairs": (),
        "representation": "oracle_human_verified_table_v1",
        "contract": "quantitative_v2",
    },
    "table_quantitative_prompt_repaired": {
        "repairs": ("A", "B"),
        "representation": "oracle_human_verified_table_v1",
        "contract": "quantitative_v2",
    },
}

NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def _validate_spec(spec: dict[str, Any]) -> None:
    if (
        spec.get("status") != SPEC_STATUS
        or spec.get("frozen_before_live_run") is not True
    ):
        raise ValueError("v1.2 diagnostic spec must be frozen before execution")
    names = [row["condition"] for row in spec["diagnostic_conditions"]]
    if names != list(CONDITIONS):
        raise ValueError("v1.2 diagnostic conditions differ from the implementation")
    budget = spec["live_call_budget"]
    if budget["maximum_model_calls"] != 12 or budget["pipeline_executions"] != 6:
        raise ValueError("v1.2 is frozen to six executions and twelve model calls")


def _subset_case(case: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    by_id = {row["question_id"]: row for row in case["questions"]}
    wanted = spec["scope"]["question_ids"]
    if set(wanted) - set(by_id):
        raise ValueError("Frozen diagnostic questions are missing")
    result = {**case, "questions": [by_id[question_id] for question_id in wanted]}
    validate_case(result)
    return result


def _git_state(spec_path: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            str(spec_path.resolve().relative_to(root)),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if dirty:
        raise ValueError("Live diagnostic requires a clean tracked worktree")
    code_files = [
        root / "research/diagnostic_v1_2.py",
        root / "research/pipeline_runner.py",
        root / "research/allocation_pilot.py",
        root / "research/pilot.py",
    ]
    hashes = {
        str(path.relative_to(root)): sha256(path.read_bytes()) for path in code_files
    }
    return {
        "git_commit": commit,
        "git_tracked_files_dirty": False,
        "diagnostic_code_files_sha256": hashes,
        "diagnostic_code_sha256": digest(hashes),
    }


def _structured_table(source_text: str) -> str:
    repaired = "Total revenues 66,608" in source_text
    damaged = "Total revenues 6,608" in source_text
    if repaired == damaged:
        raise ValueError("Cannot identify exactly one p55 source state")
    revenue = "66,608" if repaired else "6,608"
    cost = "(63,106)" if repaired else "(6,106)"
    required_source_tokens = [
        f"Total revenues {revenue}",
        f"Total costs and expenses {cost}",
        "3,502 3,017 (5,685)",
        "Income tax (expense)/benefit (31) 743 2,535",
    ]
    if not all(token in source_text for token in required_source_tokens):
        raise ValueError("p55 source state does not match the audited table")
    return """The Boeing Company and Subsidiaries
Consolidated Statements of Operations
Unit: Dollars in millions, except per share data
Years ended December 31

| Source row label | 2022 | 2021 | 2020 |
|---|---:|---:|---:|
| Sales of products | 55,893 | 51,386 | 47,142 |
| Sales of services | 10,715 | 10,900 | 11,016 |
| Total revenues | REVENUE_2022 | 62,286 | 58,158 |
| Cost of products | (53,969) | (49,954) | (54,568) |
| Cost of services | (9,109) | (9,283) | (9,232) |
| Boeing Capital interest expense | (28) | (32) | (43) |
| Total costs and expenses | COST_2022 | (59,269) | (63,843) |
| [row label blank in source] | 3,502 | 3,017 | (5,685) |
| (Loss)/income from operating investments, net | (16) | 210 | 9 |
| General and administrative expense | (4,187) | (4,157) | (4,817) |
| Research and development expense, net | (2,852) | (2,249) | (2,476) |
| Gain on dispositions, net | 6 | 277 | 202 |
| Loss from operations | (3,547) | (2,902) | (12,767) |
| Other income, net | 1,058 | 551 | 447 |
| Interest and debt expense | (2,533) | (2,682) | (2,156) |
| Loss before income taxes | (5,022) | (5,033) | (14,476) |
| Income tax (expense)/benefit | (31) | 743 | 2,535 |
| Net loss | (5,053) | (4,290) | (11,941) |
| Less: net loss attributable to noncontrolling interest | (118) | (88) | (68) |
| Net loss attributable to Boeing Shareholders | ($4,935) | ($4,202) | ($11,873) |
| Basic loss per share | ($8.30) | ($7.15) | ($20.88) |
| Diluted loss per share | ($8.30) | ($7.15) | ($20.88) |
""".replace("REVENUE_2022", revenue).replace("COST_2022", cost)


def _payload(
    case: dict[str, Any], repairs: tuple[str, ...], representation: str
) -> dict[str, Any]:
    payload = runner_payload(case, repairs, 0)
    if representation == "flat_extracted_text":
        return payload
    if representation != "oracle_human_verified_table_v1":
        raise ValueError(f"Unsupported representation: {representation}")
    block = next(row for row in payload["blocks"] if row["block_id"] == ORACLE_BLOCK_ID)
    block["text"] = _structured_table(block["text"])
    block["source_kind"] = "oracle_human_verified_table"
    block["run_id"] = "oracle-representation-v1"
    block.pop("parser_name", None)
    block.pop("parser_version", None)
    return payload


def preflight(
    case_path: Path,
    spec_path: Path,
    old_config_path: Path,
    quantitative_config_path: Path,
    max_calls: int,
) -> dict[str, Any]:
    spec = _load_json(spec_path)
    _validate_spec(spec)
    case = _subset_case(_load_json(case_path), spec)
    old_config = RunnerConfig.load(old_config_path)
    quantitative_config = RunnerConfig.load(quantitative_config_path)
    if old_config.qa_output_contract != "concise_v1":
        raise ValueError("Historical comparison config must use concise_v1")
    if quantitative_config.qa_output_contract != "quantitative_v2":
        raise ValueError("New comparison config must use quantitative_v2")
    invariant_fields = (
        "provider",
        "model",
        "base_url",
        "synthesis_mode",
        "chunk_chars",
        "chunk_overlap_chars",
        "retrieval_top_k",
        "temperature",
        "top_p",
        "ollama_num_ctx",
    )
    mismatched = [
        field
        for field in invariant_fields
        if getattr(old_config, field) != getattr(quantitative_config, field)
    ]
    if mismatched:
        raise ValueError(f"Comparison configs change uncontrolled fields: {mismatched}")
    executions = len(CONDITIONS)
    questions = len(case["questions"])
    calls = executions * questions
    return {
        "schema_version": 1,
        "execution_mode": "preflight_no_model_calls",
        "spec_id": spec["spec_id"],
        "pipeline_executions": executions,
        "questions_per_execution": questions,
        "estimated_model_calls": calls,
        "maximum_output_tokens": sum(
            questions
            * (
                old_config if rule["contract"] == "concise_v1" else quantitative_config
            ).qa_max_output_tokens
            for rule in CONDITIONS.values()
        ),
        "max_total_calls": max_calls,
        "within_call_budget": calls <= max_calls,
        "model": old_config.model,
        "controlled_config_fields": list(invariant_fields),
        "old_config": old_config.public_dict(),
        "quantitative_config": quantitative_config.public_dict(),
    }


def run(
    *,
    case_path: Path,
    spec_path: Path,
    old_config_path: Path,
    quantitative_config_path: Path,
    out: Path,
    max_calls: int,
    timeout: float,
) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Output exists; use a new append-only preserved run directory")
    plan = preflight(
        case_path, spec_path, old_config_path, quantitative_config_path, max_calls
    )
    if not plan["within_call_budget"]:
        raise ValueError("Preflight exceeds the frozen call budget")
    spec = _load_json(spec_path)
    case = _subset_case(_load_json(case_path), spec)
    git_state = _git_state(spec_path)
    out.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "status": "running",
        "run_id": str(uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256(spec_path.read_bytes()),
        "case_sha256": digest(case),
        "old_config_sha256": sha256(old_config_path.read_bytes()),
        "quantitative_config_sha256": sha256(quantitative_config_path.read_bytes()),
        "call_plan": plan,
        **git_state,
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "frozen_spec.json", spec)
    write_json(out / "frozen_case.json", case)
    write_json(out / "frozen_old_config.json", _load_json(old_config_path))
    write_json(
        out / "frozen_quantitative_config.json", _load_json(quantitative_config_path)
    )
    representations: dict[str, str] = {}
    records = []
    try:
        with (
            (out / "inputs.jsonl").open("x") as input_stream,
            (out / "records.jsonl").open("x") as record_stream,
        ):
            for condition, rule in CONDITIONS.items():
                payload = _payload(case, rule["repairs"], rule["representation"])
                p55 = next(
                    row["text"]
                    for row in payload["blocks"]
                    if row["block_id"] == ORACLE_BLOCK_ID
                )
                representations[
                    f"{rule['representation']}:{'repaired' if rule['repairs'] else 'damaged'}"
                ] = p55
                config_path = (
                    old_config_path
                    if rule["contract"] == "concise_v1"
                    else quantitative_config_path
                )
                command = [
                    sys.executable,
                    "-m",
                    "research.pipeline_runner",
                    "run",
                    "--config",
                    str(config_path.resolve()),
                    "--force-evidence-block-id",
                    ORACLE_BLOCK_ID,
                ]
                input_record = {
                    "condition": condition,
                    "source_state": "repaired" if rule["repairs"] else "damaged",
                    "evidence_representation": rule["representation"],
                    "qa_output_contract": rule["contract"],
                    "payload": payload,
                }
                input_stream.write(json.dumps(input_record, ensure_ascii=False) + "\n")
                input_stream.flush()
                response = _run_payload(command, payload, timeout)
                expected_contract = rule["contract"]
                actual_contract = response["metadata"]["applied_generation_settings"][
                    "qa_output_contract"
                ]
                if actual_contract != expected_contract:
                    raise ValueError(
                        "Pipeline did not apply the frozen QA output contract"
                    )
                record = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "source_state": input_record["source_state"],
                    "evidence_route": "oracle_evidence_full_p55",
                    "evidence_representation": rule["representation"],
                    "qa_output_contract": rule["contract"],
                    "input_sha256": digest(payload),
                    "output_sha256": digest(response),
                    "response": response,
                }
                records.append(record)
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
        write_json(
            out / "representations.json",
            {
                "status": "oracle table variants are human-authored evaluation diagnostics",
                "values": representations,
            },
        )
        pipeline_ids = [
            row["response"]["metadata"]["pipeline_execution_id"] for row in records
        ]
        calls = sum(row["response"]["metadata"]["call_count"] for row in records)
        if len(set(pipeline_ids)) != len(CONDITIONS):
            raise ValueError("Every condition needs a fresh pipeline execution")
        if calls > max_calls:
            raise ValueError("Actual model calls exceeded the frozen budget")
        runtime_ids = {
            json.dumps(row["response"]["metadata"]["provider_runtime"], sort_keys=True)
            for row in records
        }
        if len(runtime_ids) != 1:
            raise ValueError("Model runtime identity changed during the comparison")
        manifest.update(
            {
                "status": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "completed_model_calls": calls,
                "unique_pipeline_execution_ids": len(pipeline_ids),
                "inputs_sha256": sha256((out / "inputs.jsonl").read_bytes()),
                "records_sha256": sha256((out / "records.jsonl").read_bytes()),
                "representations_sha256": sha256(
                    (out / "representations.json").read_bytes()
                ),
                "provider_runtime": records[0]["response"]["metadata"][
                    "provider_runtime"
                ],
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


def _numeric_claims(answer: str) -> list[dict[str, Any]]:
    claims = []
    for match in NUMBER_PATTERN.finditer(answer.replace("−", "-")):
        raw = match.group(0)
        document_label = answer[match.end() : match.end() + 2].lower() == "-k"
        stripped = raw.replace("$", "").replace(",", "").replace("%", "")
        negative_parentheses = stripped.startswith("(") and stripped.endswith(")")
        stripped = stripped.strip("()")
        try:
            value = float(stripped)
        except ValueError:
            continue
        is_year = abs(value) in {2020.0, 2021.0, 2022.0, 2023.0}
        if negative_parentheses and not is_year:
            value = -value
        claims.append(
            {
                "raw": raw,
                "value": value,
                "is_percent": "%" in raw,
                "is_currency": "$" in raw,
                "is_year": is_year,
                "is_document_label": document_label,
            }
        )
    return claims


def _near(value: float, options: tuple[float, ...], tolerance: float = 0.011) -> bool:
    return any(
        math.isclose(abs(value), abs(option), abs_tol=tolerance) for option in options
    )


def _gross_evaluation(answer: dict[str, Any], source_state: str) -> dict[str, Any]:
    text = answer["answer"]
    lowered = text.lower()
    insufficient = "insufficient" in lowered or "not enough" in lowered
    negated_improvement = bool(
        re.search(r"\bnot\b.{0,30}\bimprov", lowered)
        or re.search(r"\bdoesn['’]?t\b.{0,30}\bimprov", lowered)
    )
    direction_incorrect = not insufficient and (
        negated_improvement
        or any(word in lowered for word in ("deterior", "declin", "worsen"))
    )
    direction_correct = (
        not insufficient
        and not direction_incorrect
        and ("improv" in lowered or lowered.startswith("yes"))
    )
    conclusion = (
        "CORRECT"
        if direction_correct
        else ("INCORRECT" if direction_incorrect else "MISSING")
    )
    claims = _numeric_claims(text)
    non_year = [
        claim
        for claim in claims
        if not claim["is_year"] and not claim["is_document_label"]
    ]
    valid_values = (
        3502,
        3017,
        66608,
        62286,
        63106,
        59269,
        5.3,
        4.8,
        5.26,
        4.84,
        5.2576,
        4.8438,
        0.5,
        94.7,
        95.2,
        100,
        55893,
        51386,
        47142,
        10715,
        10900,
        11016,
        53969,
        49954,
        54568,
        9109,
        9283,
        9232,
        28,
        32,
        43,
    )
    wrong = [claim for claim in non_year if not _near(claim["value"], valid_values)]
    if not non_year:
        numeric_status = "NOT_APPLICABLE_NO_NUMBERS"
    elif wrong:
        numeric_status = "INCORRECT_NUMERIC_CLAIM"
    else:
        numeric_status = "ALL_STATED_NUMBERS_CORRECT"
    values = [claim["value"] for claim in non_year]
    has_margins = _near_any(values, 5.3) and _near_any(values, 4.8)
    has_years = "2022" in text and "2021" in text
    structured = answer.get("structured_output", {})
    calculations = (
        structured.get("calculations", []) if isinstance(structured, dict) else []
    )
    calculation_shown = bool(calculations) and any(
        marker in " ".join(calculations).lower()
        for marker in ("/", "=", "divid", "minus", "subtract", "100")
    )
    verbal_basis = "gross margin" in lowered and any(
        marker in lowered for marker in ("/", "divid", "revenue", "100 -")
    )
    complete = (
        conclusion == "CORRECT"
        and numeric_status == "ALL_STATED_NUMBERS_CORRECT"
        and has_years
        and has_margins
        and (calculation_shown or verbal_basis)
    )
    cited = ORACLE_BLOCK_ID in answer.get("evidence_block_ids", [])
    evidence_sufficient = cited and source_state == "repaired"
    return {
        "conclusion_correctness": conclusion,
        "stated_numeric_accuracy": numeric_status,
        "numeric_claims": claims,
        "incorrect_numeric_claims": wrong,
        "required_quantitative_explanation_completeness": (
            "COMPLETE" if complete else "MISSING_OR_INCOMPLETE"
        ),
        "evidence_sufficiency": "SUFFICIENT" if evidence_sufficient else "INSUFFICIENT",
        "all_reference_numbers_required": False,
        "complete_route_observed": "two_period_margins" if complete else None,
        "unconditional_overall_correct": conclusion == "CORRECT"
        and numeric_status == "ALL_STATED_NUMBERS_CORRECT"
        and complete
        and evidence_sufficient,
    }


def _near_any(values: list[float], target: float, tolerance: float = 0.011) -> bool:
    return any(
        math.isclose(abs(value), abs(target), abs_tol=tolerance) for value in values
    )


def _near_signed(values: list[float], target: float, tolerance: float = 0.011) -> bool:
    return any(math.isclose(value, target, abs_tol=tolerance) for value in values)


def _tax_evaluation(answer: dict[str, Any]) -> dict[str, Any]:
    text = answer["answer"]
    claims = _numeric_claims(text)
    non_year = [
        claim
        for claim in claims
        if not claim["is_year"] and not claim["is_document_label"]
    ]
    values = [claim["value"] for claim in non_year]
    financebench_numbers = _near_signed(values, 0.62) and _near_signed(values, -14.76)
    filing_numbers = _near_signed(values, -0.6) and (
        _near_signed(values, 14.7) or _near_signed(values, 14.8)
    )
    has_years = "2022" in text and "2021" in text
    if not non_year:
        numeric_status = "NOT_APPLICABLE_NO_NUMBERS"
    elif financebench_numbers or filing_numbers:
        numeric_status = "MATCHES_ONE_RETAINED_REFERENCE"
    else:
        numeric_status = "DOES_NOT_MATCH_RETAINED_REFERENCES"
    cited = ORACLE_BLOCK_ID in answer.get("evidence_block_ids", [])
    return {
        "conclusion_correctness": "UNRESOLVED_REFERENCE_CONFLICT",
        "stated_numeric_accuracy": numeric_status,
        "numeric_claims": claims,
        "financebench_reference_numbers_correct": financebench_numbers,
        "filing_reported_numbers_correct": filing_numbers,
        "required_quantitative_explanation_completeness": (
            "COMPLETE_FOR_ONE_REFERENCE"
            if has_years and (financebench_numbers or filing_numbers)
            else "MISSING_OR_INCOMPLETE"
        ),
        "financebench_evidence_sufficiency": "SUFFICIENT_FOR_ARITHMETIC"
        if cited
        else "INSUFFICIENT",
        "filing_reported_evidence_sufficiency": "INSUFFICIENT_P55_DOES_NOT_REPORT_RATE",
        "unconditional_overall_correct": None,
        "unconditional_claim_withheld": True,
    }


def _evaluate_record(record: dict[str, Any]) -> dict[str, Any]:
    _validate_live_response(record["response"])
    questions = []
    for answer in record["response"]["answers"]:
        qid = answer["question_id"]
        if qid == GROSS_QUESTION_ID:
            evaluation = _gross_evaluation(answer, record["source_state"])
        elif qid == TAX_QUESTION_ID:
            evaluation = _tax_evaluation(answer)
        else:
            raise ValueError(f"Unexpected question: {qid}")
        questions.append(
            {
                "question_id": qid,
                "answer": answer["answer"],
                "evidence_block_ids": answer.get("evidence_block_ids", []),
                "qa_output_contract": answer.get("qa_output_contract", "concise_v1"),
                "structured_output": answer.get("structured_output"),
                **evaluation,
            }
        )
    return {
        "condition": record["condition"],
        "source_state": record["source_state"],
        "evidence_representation": record.get(
            "evidence_representation", "flat_extracted_text"
        ),
        "qa_output_contract": record.get("qa_output_contract", "concise_v1"),
        "pipeline_execution_id": record["response"]["metadata"][
            "pipeline_execution_id"
        ],
        "questions": questions,
    }


def _gross_row(outcome: dict[str, Any]) -> dict[str, Any]:
    return next(
        row for row in outcome["questions"] if row["question_id"] == GROSS_QUESTION_ID
    )


def _effect(left: dict[str, Any], right: dict[str, Any], name: str) -> dict[str, Any]:
    a = _gross_row(left)
    b = _gross_row(right)
    fields = (
        "conclusion_correctness",
        "stated_numeric_accuracy",
        "required_quantitative_explanation_completeness",
        "evidence_sufficiency",
        "unconditional_overall_correct",
    )
    return {
        "comparison": name,
        "left_condition": left["condition"],
        "right_condition": right["condition"],
        "changed_fields": [field for field in fields if a[field] != b[field]],
        "left": {field: a[field] for field in fields},
        "right": {field: b[field] for field in fields},
        "interpretation_limit": "single independent local-model executions; observed difference is diagnostic, not a causal or general-performance estimate",
    }


def _posthoc_v11(parent: Path) -> dict[str, Any]:
    manifest = _load_json(parent / "manifest.json")
    records = read_jsonl(parent / "records.jsonl")
    outcomes = [_evaluate_record(record) for record in records]
    old_summary_path = parent / "adjudication-v2/summary.json"
    if not old_summary_path.exists():
        old_summary_path = parent / "summary.json"
    old_summary = _load_json(old_summary_path)
    return {
        "analysis_status": "POSTHOC_EXPLORATORY_REANALYSIS",
        "parent_run_id": manifest["run_id"],
        "parent_records_sha256": sha256((parent / "records.jsonl").read_bytes()),
        "historical_strict_summary_sha256": sha256(old_summary_path.read_bytes()),
        "historical_strict_condition_outcomes": old_summary["condition_outcomes"],
        "v1_2_dimension_outcomes": outcomes,
        "same_rule_applied_to_all_conditions": True,
    }


def evaluate(
    run_dir: Path, parent_v11: Path, out_dir: Path | None = None
) -> dict[str, Any]:
    output = out_dir or run_dir
    if output != run_dir:
        output.mkdir(parents=True, exist_ok=False)
    for name in ("evaluation_v2.json", "posthoc_v1_1_reanalysis.json", "summary.json"):
        if (output / name).exists():
            raise ValueError(
                "Evaluation output exists; do not overwrite append-only artifacts"
            )
    manifest = _load_json(run_dir / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError("Cannot evaluate an incomplete run")
    outcomes = [
        _evaluate_record(record) for record in read_jsonl(run_dir / "records.jsonl")
    ]
    by_condition = {row["condition"]: row for row in outcomes}
    comparisons = [
        _effect(
            by_condition["flat_old_prompt_damaged"],
            by_condition["flat_quantitative_prompt_damaged"],
            "output_requirement_effect_damaged_flat",
        ),
        _effect(
            by_condition["flat_old_prompt_repaired"],
            by_condition["flat_quantitative_prompt_repaired"],
            "output_requirement_effect_repaired_flat",
        ),
        _effect(
            by_condition["flat_quantitative_prompt_damaged"],
            by_condition["table_quantitative_prompt_damaged"],
            "table_representation_effect_damaged_quantitative",
        ),
        _effect(
            by_condition["flat_quantitative_prompt_repaired"],
            by_condition["table_quantitative_prompt_repaired"],
            "table_representation_effect_repaired_quantitative",
        ),
    ]
    evaluation = {
        "schema_version": 1,
        "evaluation_version": "separated-qa-evidence-contract-v1.2.2",
        "scope": "development diagnostic only",
        "condition_outcomes": outcomes,
        "controlled_comparisons": comparisons,
        "tax_reference_conflict": True,
        "tax_unconditional_claim_withheld": True,
        "all_reference_numbers_required_for_gross": False,
    }
    write_json(output / "evaluation_v2.json", evaluation)
    posthoc = _posthoc_v11(parent_v11)
    write_json(output / "posthoc_v1_1_reanalysis.json", posthoc)
    summary = {
        "schema_version": 1,
        "spec_id": manifest["spec_id"],
        "run_id": manifest["run_id"],
        "model_runtime": manifest["provider_runtime"],
        "completed_model_calls": manifest["completed_model_calls"],
        "condition_outcomes": [
            {
                "condition": outcome["condition"],
                "gross": _gross_row(outcome),
                "tax": next(
                    row
                    for row in outcome["questions"]
                    if row["question_id"] == TAX_QUESTION_ID
                ),
            }
            for outcome in outcomes
        ],
        "controlled_comparisons": comparisons,
        "intervention_validity": "not suitable for combination-effect or policy-superiority claims",
        "policy_comparison_gate": "NOT_READY",
        "most_important_next_work": "freeze an independent development/evaluation case set whose actual error candidates have non-gold distinguishing features, varied downstream dependencies, and repairs that can change a frozen final metric",
        "evaluation_v2_sha256": sha256((output / "evaluation_v2.json").read_bytes()),
        "posthoc_v1_1_reanalysis_sha256": sha256(
            (output / "posthoc_v1_1_reanalysis.json").read_bytes()
        ),
    }
    write_json(output / "summary.json", summary)
    write_json(
        output / "evaluation_manifest.json",
        {
            "schema_version": 1,
            "evaluation_version": evaluation["evaluation_version"],
            "created_at": datetime.now(UTC).isoformat(),
            "evaluation_v2_sha256": sha256(
                (output / "evaluation_v2.json").read_bytes()
            ),
            "posthoc_v1_1_reanalysis_sha256": sha256(
                (output / "posthoc_v1_1_reanalysis.json").read_bytes()
            ),
            "summary_sha256": sha256((output / "summary.json").read_bytes()),
        },
    )
    return summary


def preservation_manifest(run_dir: Path) -> dict[str, Any]:
    target = run_dir / "preservation_manifest.json"
    if target.exists():
        raise ValueError("Preservation manifest exists; do not overwrite it")
    files = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path != target:
            files.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()),
                }
            )
    result = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "run_directory": str(run_dir.resolve()),
        "file_count": len(files),
        "total_bytes": sum(row["bytes"] for row in files),
        "files": files,
    }
    write_json(target, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        command.add_argument("--case", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--old-config", type=Path, required=True)
        command.add_argument("--quantitative-config", type=Path, required=True)
        command.add_argument("--max-total-calls", type=int, required=True)
        if name == "run":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--timeout", type=float, default=900)
    judge = commands.add_parser("evaluate")
    judge.add_argument("--run", type=Path, required=True)
    judge.add_argument("--parent-v11", type=Path, required=True)
    judge.add_argument("--out-dir", type=Path)
    preserve = commands.add_parser("preservation-manifest")
    preserve.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "preflight":
        result = preflight(
            args.case,
            args.spec,
            args.old_config,
            args.quantitative_config,
            args.max_total_calls,
        )
    elif args.action == "run":
        result = run(
            case_path=args.case,
            spec_path=args.spec,
            old_config_path=args.old_config,
            quantitative_config_path=args.quantitative_config,
            out=args.out,
            max_calls=args.max_total_calls,
            timeout=args.timeout,
        )
    elif args.action == "evaluate":
        result = evaluate(args.run, args.parent_v11, args.out_dir)
    else:
        result = preservation_manifest(args.run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(f"v1.2 diagnostic stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
