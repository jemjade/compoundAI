"""Run the frozen multi-document v1.3 development feasibility diagnostic.

The module keeps evaluation labels out of model payloads and policy inputs. It serializes policy
inputs/selections before joining controlled-error labels, and preserves complete model traces in
an append-only run directory.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from uuid import uuid4

from research.allocation import NUMERIC_PATTERN, assert_policy_input_safe, select_candidates
from research.allocation_pilot import _run_payload
from research.pilot import SAFE_BLOCK_FIELDS, digest, read_jsonl, sha256, write_json
from research.pipeline_runner import RunnerConfig, _chunk_text, bm25_search

SPEC_STATUS = "FROZEN_DEVELOPMENT_FEASIBILITY_DIAGNOSTIC"
POLICIES = ("individual_impact", "graph_aware")
REPAIR_QUESTION_ID = "financebench_id_00222"
REPAIR_BLOCK_ID = "AMD_2022_10K:p56"
REPAIR_STATES: dict[str, tuple[str, ...]] = {
    "damaged": (),
    "A_only": ("A",),
    "B_only": ("B",),
    "AB": ("A", "B"),
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def _validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("status") != SPEC_STATUS or spec.get("frozen_before_live_run") is not True:
        raise ValueError("v1.3 spec must be frozen before execution")
    if spec["live_call_budget"]["maximum_model_calls"] != 18:
        raise ValueError("v1.3 is frozen to at most 18 local model calls")
    if spec["model_and_pipeline"]["models"] != ["llama3:latest"]:
        raise ValueError("v1.3 is frozen to exactly one QA model")


def _git_state(spec_path: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(spec_path.resolve().relative_to(root))],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("Live v1.3 execution requires a clean tracked worktree")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    code_files = [
        root / "research/development_v1_3.py",
        root / "research/pipeline_runner.py",
        root / "research/allocation.py",
    ]
    hashes = {str(path.relative_to(root)): sha256(path.read_bytes()) for path in code_files}
    return {
        "git_commit": commit,
        "git_tracked_files_dirty": False,
        "code_files_sha256": hashes,
        "code_sha256": digest(hashes),
    }


def load_development_data(
    data_dir: Path, spec: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    manifest = _load_json(data_dir / "manifest.json")
    blocks = read_jsonl(data_dir / "inputs/blocks.jsonl")
    all_questions = read_jsonl(data_dir / "inputs/questions.jsonl")
    all_gold = read_jsonl(data_dir / "evaluation/gold.jsonl")
    wanted = spec["scope"]["question_ids"]
    qmap = {row["question_id"]: row for row in all_questions}
    gmap = {row["question_id"]: row for row in all_gold}
    if set(wanted) - set(qmap) or set(wanted) - set(gmap):
        raise ValueError("Development snapshot is missing a frozen question or reference")
    questions = [qmap[qid] for qid in wanted]
    gold = [gmap[qid] for qid in wanted]
    documents = set(spec["scope"]["documents"])
    selected_blocks = [row for row in blocks if row["document_id"] in documents]
    if {row["document_id"] for row in selected_blocks} != documents:
        raise ValueError("Development snapshot is missing a frozen document")
    expected_pdf = {
        row["document_id"]: row["pdf_sha256"] for row in spec["source_data"]["documents"]
    }
    observed_pdf = {
        row["document_id"]: row["pdf_sha256"] for row in manifest["documents"]
    }
    if expected_pdf != observed_pdf:
        raise ValueError("PDF identities differ from the frozen spec")
    return selected_blocks, questions, gold, manifest


def _safe_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in SAFE_BLOCK_FIELDS if key in row} for row in blocks]


def _payload(
    blocks: list[dict[str, Any]], questions: list[dict[str, Any]], repeat_id: int = 0
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repeat_id": repeat_id,
        "blocks": _safe_blocks(blocks),
        "questions": [
            {key: row[key] for key in ("question_id", "document_id", "question")}
            for row in questions
        ],
    }


def _replace_once(text: str, old: str, new: str) -> tuple[str, int, int]:
    first = text.find(old)
    if first < 0 or text.find(old, first + 1) >= 0:
        raise ValueError(f"Expected exactly one controlled source fragment: {old!r}")
    start = first + old.index(next(token for token in old.split() if "," in token))
    old_value = next(token for token in old.split() if "," in token)
    if text[start : start + len(old_value)] != old_value:
        raise AssertionError("Controlled value offset mismatch")
    return text[:start] + new + text[start + len(old_value) :], start, start + len(new)


def build_damaged_blocks(
    clean_blocks: list[dict[str, Any]], selected: tuple[str, ...]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return the damaged base with exactly the selected ideal restorations applied."""
    if set(selected) - {"A", "B"}:
        raise ValueError("Unknown controlled restoration")
    output = _safe_blocks(clean_blocks)
    block = next(row for row in output if row["block_id"] == REPAIR_BLOCK_ID)
    text = block["text"]
    definitions = (
        (
            "A",
            "Cash and cash equivalents $ 4,835 $ 2,535",
            "835",
            "4,835",
        ),
        (
            "B",
            "Accounts receivable, net 4,126 2,706",
            "126",
            "4,126",
        ),
    )
    labels: dict[str, dict[str, Any]] = {}
    for label, context, damaged_value, clean_value in definitions:
        context_start = text.find(context)
        if context_start < 0:
            raise ValueError(f"Controlled source context is missing for {label}")
        value_start = context_start + context.index(clean_value)
        value_end = value_start + len(clean_value)
        text = text[:value_start] + damaged_value + text[value_end:]
        labels[label] = {
            "block_id": REPAIR_BLOCK_ID,
            "start": value_start,
            "end": value_start + len(damaged_value),
            "observed_text": damaged_value,
        }
    # Offsets above are generated in A-then-B order. A shortens text by two characters, so B's
    # context search and stored offset already refer to the final damaged base.
    for label in selected:
        item = labels[label]
        before = item["observed_text"]
        after = "4,835" if label == "A" else "4,126"
        start, end = item["start"], item["end"]
        if text[start:end] != before:
            raise AssertionError("Controlled restoration span moved unexpectedly")
        text = text[:start] + after + text[end:]
        delta = len(after) - len(before)
        if label == "A":
            labels["B"]["start"] += delta
            labels["B"]["end"] += delta
    block["text"] = text
    return output, labels


def _canonical_number(raw: str) -> str | None:
    value = raw.strip().replace("−", "-")
    is_percent = value.endswith("%")
    value = value.removesuffix("%").replace("$", "").strip()
    negative = value.startswith("(") and value.endswith(")")
    value = value.strip("()").replace(",", "")
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if negative:
        number = -number
    normalized = format(number.normalize(), "f")
    return f"{normalized}{'%' if is_percent else ''}"


def _secondary_numeric_words(pdf_path: Path) -> dict[int, list[dict[str, Any]]]:
    import pymupdf

    result: dict[int, list[dict[str, Any]]] = {}
    with pymupdf.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            rows = []
            for x0, y0, x1, y1, word, block_no, line_no, word_no in page.get_text("words"):
                canonical = _canonical_number(str(word))
                if canonical is None:
                    continue
                rows.append(
                    {
                        "canonical": canonical,
                        "text": str(word),
                        "bbox": [round(float(x0), 3), round(float(y0), 3), round(float(x1), 3), round(float(y1), 3)],
                        "block_number": int(block_no),
                        "line_number": int(line_no),
                        "word_number": int(word_no),
                    }
                )
            result[page_index + 1] = rows
    return result


def _current_asset_constraint(
    block: dict[str, Any], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Human-configured row identity using only values visible in the current input state."""
    if block["block_id"] != REPAIR_BLOCK_ID:
        raise ValueError("The frozen v1.3 constraint applies only to AMD p56")
    text = block["text"]
    labels = [
        "Cash and cash equivalents",
        "Short-term investments",
        "Accounts receivable, net",
        "Inventories",
        "Receivables from related parties",
        "Prepaid expenses and other current assets",
        "Total current assets",
    ]
    values: dict[str, list[tuple[float, tuple[int, int]]]] = {}
    number = r"(\(?\d[\d,]*(?:\.\d+)?\)?)"
    for label in labels:
        match = re.search(re.escape(label) + r"\s+\$?\s*" + number + r"\s+\$?\s*" + number, text)
        if match is None:
            raise ValueError(f"Cannot observe both year cells for constraint row {label}")
        row = []
        for group in (1, 2):
            raw = match.group(group)
            signed = -1 if raw.startswith("(") else 1
            row.append((signed * float(raw.strip("()").replace(",", "")), match.span(group)))
        values[label] = row
    participants: dict[tuple[int, int], float] = {}
    residuals = []
    total_label = "Total current assets"
    for column in range(2):
        components = sum(values[label][column][0] for label in labels[:-1])
        total = values[total_label][column][0]
        residual = min(abs(total - components) / max(abs(total), 1.0), 1.0)
        residuals.append(residual)
        for label in labels:
            participants[values[label][column][1]] = residual
    candidate_residuals = {}
    for candidate in candidates:
        span = (candidate["start"], candidate["end"])
        if span in participants:
            candidate_residuals[candidate["candidate_id"]] = participants[span]
    return {
        "constraint_id": "AMD_2022_10K:p56:total_current_assets_equals_components",
        "configuration": "human_configured_from_visible_row_labels_not_automatic_table_parser",
        "year_order": [2022, 2021],
        "normalized_residuals": [round(value, 8) for value in residuals],
        "participant_candidate_residuals": candidate_residuals,
    }


def build_policy_input(
    *,
    blocks: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    source_manifest: dict[str, Any],
    config: RunnerConfig,
    spec_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build policy-visible observations, with no reference or controlled-label argument."""
    document_paths = {
        row["document_id"]: Path(row["pdf_path"]) for row in source_manifest["documents"]
    }
    secondary = {
        document_id: _secondary_numeric_words(path)
        for document_id, path in document_paths.items()
    }
    question_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        question_by_doc[question["document_id"]].append(question)

    chunk_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    block_chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        for index, (start, end, text) in enumerate(
            _chunk_text(block["text"], config.chunk_chars, config.chunk_overlap_chars)
        ):
            chunk = {
                "chunk_id": f"observable:{block['block_id']}:{index}",
                "parent_synthesis_id": f"observable:{block['block_id']}",
                "source_block_ids": [block["block_id"]],
                "lineage_mode": "deterministic_passthrough",
                "score": None,
                "text": text,
                "start": start,
                "end": end,
            }
            chunk_rows[block["document_id"]].append(chunk)
            block_chunks[block["block_id"]].append(chunk)
    retrieved_by_question = {}
    for document_id, doc_questions in question_by_doc.items():
        for question in doc_questions:
            retrieved_by_question[question["question_id"]] = bm25_search(
                question["question"], chunk_rows[document_id], config.retrieval_top_k
            )

    candidates = []
    for block in blocks:
        primary_counts: Counter[str] = Counter()
        primary_occurrence: Counter[str] = Counter()
        matches = list(NUMERIC_PATTERN.finditer(block["text"]))
        for match in matches:
            canonical = _canonical_number(match.group(0))
            if canonical is not None:
                primary_counts[canonical] += 1
        secondary_rows = secondary[block["document_id"]][block["page_number"]]
        secondary_by_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in secondary_rows:
            secondary_by_number[row["canonical"]].append(row)
        for match in matches:
            canonical = _canonical_number(match.group(0))
            if canonical is None:
                continue
            occurrence = primary_occurrence[canonical]
            primary_occurrence[canonical] += 1
            secondary_matches = secondary_by_number.get(canonical, [])
            matched = secondary_matches[occurrence] if occurrence < len(secondary_matches) else None
            descendants = []
            overlaps = []
            for chunk in block_chunks[block["block_id"]]:
                if max(match.start(), chunk["start"]) < min(match.end(), chunk["end"]):
                    overlaps.append(chunk["chunk_id"])
                    for question_id, retrieved in retrieved_by_question.items():
                        if any(row["chunk_id"] == chunk["chunk_id"] for row in retrieved):
                            descendants.append(question_id)
            candidate_id = "candidate:" + digest(
                [block["document_id"], block["block_id"], match.start(), match.end(), match.group(0)]
            )[:24]
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_type": "numeric_text_span",
                    "document_id": block["document_id"],
                    "block_id": block["block_id"],
                    "page_number": block["page_number"],
                    "start": match.start(),
                    "end": match.end(),
                    "observed_text": match.group(0),
                    "canonical_observed_number": canonical,
                    "descendant_question_ids": sorted(set(descendants)),
                    "overlapping_chunk_ids": sorted(set(overlaps)),
                    "secondary_observation": {
                        "primary_page_count": primary_counts[canonical],
                        "secondary_page_count": len(secondary_matches),
                        "count_disagrees": primary_counts[canonical] != len(secondary_matches),
                        "occurrence_index": occurrence,
                        "layout_match_status": (
                            "MATCHED_BY_NORMALIZED_VALUE_AND_OCCURRENCE"
                            if matched is not None
                            else "UNMATCHED"
                        ),
                        "bbox": matched["bbox"] if matched is not None else None,
                        "block_number": matched["block_number"] if matched is not None else None,
                        "line_number": matched["line_number"] if matched is not None else None,
                    },
                }
            )

    constraint_block = next(row for row in blocks if row["block_id"] == REPAIR_BLOCK_ID)
    on_constraint_page = [row for row in candidates if row["block_id"] == REPAIR_BLOCK_ID]
    constraint = _current_asset_constraint(constraint_block, on_constraint_page)
    residual_by_id = constraint["participant_candidate_residuals"]
    question_count = len(questions)
    for row in candidates:
        disagreement = float(row["secondary_observation"]["count_disagrees"])
        residual = float(residual_by_id.get(row["candidate_id"], 0.0))
        anomaly = round(0.70 * disagreement + 0.30 * residual, 8)
        reach = len(row["descendant_question_ids"]) / question_count
        row["features"] = {
            "parser_count_disagreement": disagreement,
            "layout_value_unmatched": float(
                row["secondary_observation"]["layout_match_status"] == "UNMATCHED"
            ),
            "max_normalized_constraint_residual": round(residual, 8),
            "observed_anomaly_score": anomaly,
            "candidate_instability_proxy": anomaly,
            "structural_reach": round(reach, 8),
            "expected_repairability": 1.0,
            "ideal_repair_given_detection": 1.0,
            "verification_cost": 1,
        }
        row["scores"] = {
            "uncertainty": anomaly,
            "individual_impact": round(anomaly * reach, 8),
        }
    candidates.sort(key=lambda row: row["candidate_id"])
    policy_input = {
        "schema_version": 1,
        "spec_id": spec_id,
        "visible_source_state": "controlled_damaged_primary_text",
        "question_ids": [row["question_id"] for row in questions],
        "feature_definitions": {
            "primary_parser": "pypdf 6.10.0",
            "secondary_parser": "PyMuPDF 1.28.2",
            "anomaly_formula": "0.70*parser_count_disagreement+0.30*max_normalized_constraint_residual",
            "score_semantics": "development anomaly proxy, not calibrated error probability",
            "layout_semantics": "normalized value and occurrence match to actual secondary-parser word geometry",
            "constraint_semantics": "human-configured accounting identity, not automatic table parsing",
            "ideal_exact_fix_assumption": "constant 1.0 conditional on inspecting a controlled error, not downstream success probability",
        },
        "estimated_question_edges": {
            question_id: [row["chunk_id"] for row in retrieved]
            for question_id, retrieved in retrieved_by_question.items()
        },
        "candidates": candidates,
        "constraints": [
            {
                key: value
                for key, value in constraint.items()
                if key != "participant_candidate_residuals"
            }
        ],
    }
    assert_policy_input_safe(policy_input)
    diagnostics = {
        "candidate_count": len(candidates),
        "constraint_participant_count": len(residual_by_id),
        "secondary_parser_pages": sum(len(pages) for pages in secondary.values()),
    }
    return policy_input, diagnostics


def _selection_analysis(
    policy_input: dict[str, Any], selections: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    candidates = policy_input["candidates"]
    by_id = {row["candidate_id"]: row for row in candidates}
    label_ids = {}
    for label, target in labels.items():
        matches = [
            row["candidate_id"]
            for row in candidates
            if row["block_id"] == target["block_id"]
            and row["start"] == target["start"]
            and row["end"] == target["end"]
            and row["observed_text"] == target["observed_text"]
        ]
        if len(matches) != 1:
            raise ValueError(f"Controlled label {label} maps to {len(matches)} candidates")
        label_ids[label] = matches[0]
    vectors = [
        (
            row["features"]["parser_count_disagreement"],
            row["features"]["max_normalized_constraint_residual"],
            row["features"]["structural_reach"],
        )
        for row in candidates
    ]
    vector_counts = Counter(vectors)
    scores = [row["scores"]["individual_impact"] for row in candidates]
    score_counts = Counter(scores)
    selected_sets = {row["policy"]: set(row["selected_candidate_ids"]) for row in selections}
    per_policy = {}
    controlled = set(label_ids.values())
    for selection in selections:
        selected = set(selection["selected_candidate_ids"])
        per_policy[selection["policy"]] = {
            "selected_candidate_ids": selection["selected_candidate_ids"],
            "selected_observed_text": [by_id[cid]["observed_text"] for cid in selection["selected_candidate_ids"]],
            "controlled_error_labels_selected": sorted(
                label for label, cid in label_ids.items() if cid in selected
            ),
            "controlled_error_recall": len(selected & controlled) / len(controlled),
            "id_tie_break_selection_count": sum(
                bool(step["id_tie_break_used"]) for step in selection["steps"]
            ),
        }
    return {
        "controlled_candidate_ids": label_ids,
        "candidate_inclusion": {
            "included": len(label_ids),
            "expected": 2,
            "rate": len(label_ids) / 2,
        },
        "unique_feature_vectors": len(vector_counts),
        "candidate_count": len(candidates),
        "tied_feature_candidate_ratio": sum(
            count for count in vector_counts.values() if count > 1
        )
        / len(candidates),
        "unique_individual_scores": len(score_counts),
        "tied_individual_score_candidate_ratio": sum(
            count for count in score_counts.values() if count > 1
        )
        / len(candidates),
        "policies": per_policy,
        "individual_graph_sets_equal": selected_sets["individual_impact"] == selected_sets["graph_aware"],
        "same_dependency_error_normal_distinguishability": {
            "status": "OBSERVED_VIA_SECOND_PARSER_ON_CONTROLLED_POST_EXTRACTION_DAMAGE",
            "controlled_vectors": {
                label: by_id[cid]["features"] for label, cid in label_ids.items()
            },
            "limit": "the secondary parser reads the clean PDF while controlled errors are injected into primary text, so this demonstrates an observable route but not natural-parser error discrimination",
        },
    }


def preflight(data_dir: Path, spec_path: Path, config_path: Path, max_calls: int) -> dict[str, Any]:
    spec = _load_json(spec_path)
    _validate_spec(spec)
    blocks, questions, _gold, source_manifest = load_development_data(data_dir, spec)
    config = RunnerConfig.load(config_path)
    if config.synthesis_mode != "passthrough" or config.qa_output_contract != "quantitative_v2":
        raise ValueError("v1.3 requires passthrough and quantitative_v2")
    if config.retrieval_top_k != 6 or config.model != "llama3:latest":
        raise ValueError("v1.3 config differs from frozen retrieval/model settings")
    per_doc = Counter(row["document_id"] for row in questions)
    estimated_calls = sum(per_doc.values()) + len(questions) + 4
    return {
        "schema_version": 1,
        "execution_mode": "preflight_no_model_calls",
        "spec_id": spec["spec_id"],
        "documents": sorted(per_doc),
        "questions_per_document": dict(per_doc),
        "clean_general_calls": len(questions),
        "clean_oracle_calls": len(questions),
        "controlled_state_calls": 4,
        "estimated_model_calls": estimated_calls,
        "pipeline_executions": len(per_doc) + len(questions) + 4,
        "maximum_output_tokens": estimated_calls * config.qa_max_output_tokens,
        "max_calls": max_calls,
        "within_budget": estimated_calls <= max_calls,
        "source_manifest_sha256": sha256((data_dir / "manifest.json").read_bytes()),
        "model": config.model,
        "config": config.public_dict(),
        "block_count": len(blocks),
    }


def _ollama_inventory(config: RunnerConfig) -> dict[str, Any]:
    origin = config.base_url.rstrip("/")
    with urlopen(f"{origin}/api/version", timeout=config.timeout_seconds) as response:  # noqa: S310
        version = json.loads(response.read())
    with urlopen(f"{origin}/api/tags", timeout=config.timeout_seconds) as response:  # noqa: S310
        tags = json.loads(response.read())
    return {"version": version, "tags": tags}


def run(
    *,
    data_dir: Path,
    spec_path: Path,
    config_path: Path,
    out: Path,
    timeout: float,
    max_calls: int,
) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Output exists; v1.3 raw directories are append-only")
    plan = preflight(data_dir, spec_path, config_path, max_calls)
    if not plan["within_budget"] or plan["estimated_model_calls"] != 18:
        raise ValueError("Frozen v1.3 call budget is not satisfied")
    spec = _load_json(spec_path)
    blocks, questions, gold, source_manifest = load_development_data(data_dir, spec)
    config = RunnerConfig.load(config_path)
    git_state = _git_state(spec_path)

    out.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "status": "running",
        "run_id": str(uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256(spec_path.read_bytes()),
        "config_sha256": sha256(config_path.read_bytes()),
        "source_manifest_sha256": sha256((data_dir / "manifest.json").read_bytes()),
        "call_plan": plan,
        "backup_status": "primary persistent project path only; no independently verified second physical backup",
        **git_state,
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "frozen_spec.json", spec)
    write_json(out / "frozen_config.json", _load_json(config_path))
    write_json(out / "frozen_source_manifest.json", source_manifest)
    write_json(out / "evaluation_only_reference.json", {"questions": gold})
    inventory = _ollama_inventory(config)
    write_json(out / "model_inventory.json", inventory)

    damaged_blocks, controlled_labels = build_damaged_blocks(blocks, ())
    policy_input, feature_diagnostics = build_policy_input(
        blocks=damaged_blocks,
        questions=questions,
        source_manifest=source_manifest,
        config=config,
        spec_id=spec["spec_id"],
    )
    write_json(out / "policy_input_before_labels.json", policy_input)
    selections = [
        {
            **select_candidates(
                policy_input["candidates"],
                policy=policy,
                budget=spec["policy_probe"]["budget"],
                seed_material=[spec["spec_id"], policy],
                question_count=len(questions),
            ),
            "selection_scope": "development_behavior_probe_not_performance",
        }
        for policy in POLICIES
    ]
    write_json(out / "policy_selections_before_labels.json", {"selections": selections})
    selection_analysis = _selection_analysis(policy_input, selections, controlled_labels)
    write_json(out / "policy_selection_evaluation_after_labels.json", selection_analysis)

    command = [
        sys.executable,
        "-m",
        "research.pipeline_runner",
        "run",
        "--config",
        str(config_path.resolve()),
    ]
    records = []
    call_count = 0
    try:
        with (out / "inputs.jsonl").open("x") as input_stream, (out / "records.jsonl").open("x") as record_stream:
            for document_id in spec["scope"]["documents"]:
                doc_blocks = [row for row in blocks if row["document_id"] == document_id]
                doc_questions = [row for row in questions if row["document_id"] == document_id]
                payload = _payload(doc_blocks, doc_questions)
                condition = f"clean_general:{document_id}"
                input_stream.write(json.dumps({"condition": condition, "payload": payload}, ensure_ascii=False) + "\n")
                input_stream.flush()
                response = _run_payload(command, payload, timeout)
                record = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "source_state": "clean",
                    "evidence_route": "general_bm25_document_isolated",
                    "input_sha256": digest(payload),
                    "output_sha256": digest(response),
                    "response": response,
                }
                records.append(record)
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
                call_count += response["metadata"]["call_count"]

            question_spec = {row["question_id"]: row for row in spec["questions"]}
            for question in questions:
                document_id = question["document_id"]
                doc_blocks = [row for row in blocks if row["document_id"] == document_id]
                payload = _payload(doc_blocks, [question])
                oracle_block = question_spec[question["question_id"]]["oracle_block_id"]
                condition = f"clean_oracle:{question['question_id']}"
                full_command = command + ["--force-evidence-block-id", oracle_block]
                input_stream.write(json.dumps({"condition": condition, "oracle_block_id": oracle_block, "payload": payload}, ensure_ascii=False) + "\n")
                input_stream.flush()
                response = _run_payload(full_command, payload, timeout)
                record = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "source_state": "clean",
                    "evidence_route": "oracle_full_source_page",
                    "oracle_block_id": oracle_block,
                    "input_sha256": digest(payload),
                    "output_sha256": digest(response),
                    "response": response,
                }
                records.append(record)
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
                call_count += response["metadata"]["call_count"]

            repair_question = next(row for row in questions if row["question_id"] == REPAIR_QUESTION_ID)
            amd_blocks = [row for row in blocks if row["document_id"] == repair_question["document_id"]]
            for state, selected in REPAIR_STATES.items():
                state_blocks, _ = build_damaged_blocks(amd_blocks, selected)
                payload = _payload(state_blocks, [repair_question])
                condition = f"controlled_repair:{state}"
                full_command = command + ["--force-evidence-block-id", REPAIR_BLOCK_ID]
                input_stream.write(json.dumps({"condition": condition, "oracle_block_id": REPAIR_BLOCK_ID, "payload": payload}, ensure_ascii=False) + "\n")
                input_stream.flush()
                response = _run_payload(full_command, payload, timeout)
                record = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "source_state": state,
                    "evidence_route": "oracle_full_source_page",
                    "oracle_block_id": REPAIR_BLOCK_ID,
                    "input_sha256": digest(payload),
                    "output_sha256": digest(response),
                    "response": response,
                }
                records.append(record)
                record_stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                record_stream.flush()
                call_count += response["metadata"]["call_count"]

        pipeline_ids = [row["response"]["metadata"]["pipeline_execution_id"] for row in records]
        if len(records) != 14 or len(set(pipeline_ids)) != 14 or call_count != 18:
            raise ValueError("Actual executions/calls differ from the frozen v1.3 plan")
        runtime_ids = {
            json.dumps(row["response"]["metadata"]["provider_runtime"], sort_keys=True)
            for row in records
        }
        if len(runtime_ids) != 1:
            raise ValueError("Model runtime identity changed during v1.3")
        manifest.update(
            {
                "status": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "completed_model_calls": call_count,
                "completed_pipeline_executions": len(records),
                "unique_pipeline_execution_ids": len(set(pipeline_ids)),
                "provider_runtime": records[0]["response"]["metadata"]["provider_runtime"],
                "feature_diagnostics": feature_diagnostics,
                "inputs_sha256": sha256((out / "inputs.jsonl").read_bytes()),
                "records_sha256": sha256((out / "records.jsonl").read_bytes()),
                "policy_input_sha256": sha256((out / "policy_input_before_labels.json").read_bytes()),
                "policy_selections_sha256": sha256((out / "policy_selections_before_labels.json").read_bytes()),
                "selection_evaluation_sha256": sha256((out / "policy_selection_evaluation_after_labels.json").read_bytes()),
                "model_inventory_sha256": sha256((out / "model_inventory.json").read_bytes()),
            }
        )
    except Exception as error:
        manifest.update(
            {
                "status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
                "completed_model_calls": call_count,
            }
        )
        raise
    finally:
        write_json(out / "manifest.json", manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("--data", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--max-calls", type=int, default=18)
        if name == "run":
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--timeout", type=float, default=600.0)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "preflight":
        result = preflight(args.data, args.spec, args.config, args.max_calls)
    else:
        result = run(
            data_dir=args.data,
            spec_path=args.spec,
            config_path=args.config,
            out=args.out,
            timeout=args.timeout,
            max_calls=args.max_calls,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
