"""Run the frozen v1.1 candidate-recall versus evidence-access diagnostic."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from research.allocation import (
    NUMERIC_PATTERN,
    POLICIES,
    _add_graph_trace,
    _question_instability,
    _trace_parts,
    assert_policy_input_safe,
    select_candidates,
)
from research.allocation_pilot import _run_payload, _validate_live_response
from research.pilot import (
    digest,
    judgment_id,
    load_complete_run,
    read_jsonl,
    runner_payload,
    sha256,
    validate_case,
    write_json,
    write_jsonl,
)
from research.pipeline_runner import RunnerConfig, bm25_search

SPEC_STATUS = "FROZEN_DEVELOPMENT_DIAGNOSTIC"
ORACLE_BLOCK_ID = "BOEING_2022_10K:p55"
GROSS_QUESTION_ID = "financebench_id_00678"
TAX_QUESTION_ID = "financebench_id_00585"
CONDITIONS = {
    "A_damaged_general": {"repairs": (), "oracle": False},
    "B_repaired_general": {"repairs": ("A", "B"), "oracle": False},
    "C_damaged_oracle_evidence": {"repairs": (), "oracle": True},
    "D_repaired_oracle_evidence": {"repairs": ("A", "B"), "oracle": True},
}
FINANCEBENCH_VALID_BLOCKS = {
    GROSS_QUESTION_ID: {ORACLE_BLOCK_ID, "BOEING_2022_10K:p28"},
    TAX_QUESTION_ID: {ORACLE_BLOCK_ID},
}
DOCUMENT_VALID_BLOCKS = {
    GROSS_QUESTION_ID: {ORACLE_BLOCK_ID, "BOEING_2022_10K:p28"},
    TAX_QUESTION_ID: {
        ORACLE_BLOCK_ID,
        "BOEING_2022_10K:p24",
        "BOEING_2022_10K:p77",
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("status") != SPEC_STATUS or spec.get("frozen_before_live_run") is not True:
        raise ValueError("v1.1 diagnostic spec must be frozen before execution")
    names = [row["condition"] for row in spec["diagnostic_conditions"]]
    if names != list(CONDITIONS):
        raise ValueError("v1.1 diagnostic conditions differ from the implementation")
    if spec["live_call_budget"]["maximum_model_calls"] != 8:
        raise ValueError("v1.1 diagnostic is frozen to eight model calls")


def _subset_case(case: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    wanted = spec["scope"]["question_ids"]
    by_id = {row["question_id"]: row for row in case["questions"]}
    if set(wanted) - set(by_id):
        raise ValueError("Frozen diagnostic questions are missing")
    result = {**case, "questions": [by_id[question_id] for question_id in wanted]}
    validate_case(result)
    return result


def _git_state(spec_path: Path) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(spec_path.resolve().relative_to(root))],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    if dirty:
        raise ValueError("Live diagnostic requires a clean tracked worktree")
    code_files = [
        root / "research/diagnostic_v1_1.py",
        root / "research/allocation.py",
        root / "research/allocation_pilot.py",
        root / "research/pipeline_runner.py",
        root / "research/pilot.py",
    ]
    hashes = {str(path.relative_to(root)): sha256(path.read_bytes()) for path in code_files}
    return {
        "git_commit": commit,
        "git_tracked_files_dirty": False,
        "diagnostic_code_files_sha256": hashes,
        "diagnostic_code_sha256": digest(hashes),
    }


def _candidate_id(document_id: str, block_id: str, start: int, end: int, text: str) -> str:
    return f"candidate:{digest([document_id, block_id, start, end, text])[:24]}"


def _chunk_maps(record: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    chunks, retrievals = _trace_parts(record)
    retrieved_for: dict[str, set[str]] = defaultdict(set)
    for retrieval in retrievals:
        for row in retrieval.get("output", []):
            retrieved_for[row["chunk_id"]].add(retrieval["question_id"])
    return chunks, retrieved_for


def build_full_document_policy_input(
    *,
    case: dict[str, Any],
    baseline_record: dict[str, Any],
    no_op_record: dict[str, Any],
    question_ids: list[str],
    spec_id: str,
) -> dict[str, Any]:
    """Enumerate all numeric spans without accepting gold or repair arguments."""
    if baseline_record["condition"] != "baseline" or no_op_record["condition"] != "no_op":
        raise ValueError("Only baseline and no-op parent records may be policy-visible")
    blocks = {row["block_id"]: row for row in case["blocks"]}
    questions = {row["question_id"]: row for row in case["questions"]}
    instability = _question_instability(baseline_record, no_op_record, question_ids)

    graph_nodes: dict[str, dict[str, Any]] = {}
    graph_edges: set[tuple[str, str, str]] = set()
    for block in blocks.values():
        graph_nodes[block["block_id"]] = {
            "node_id": block["block_id"],
            "node_type": "source_block",
            "document_id": block["document_id"],
            "page_number": block["page_number"],
        }
    for question_id in question_ids:
        graph_nodes[question_id] = {
            "node_id": question_id,
            "node_type": "question",
            "question": questions[question_id]["question"],
        }
    for record in (baseline_record, no_op_record):
        _add_graph_trace(graph_nodes, graph_edges, record)

    record_maps = [_chunk_maps(record) for record in (baseline_record, no_op_record)]
    chunks_by_block: dict[str, list[tuple[dict[str, Any], dict[str, set[str]]]]] = defaultdict(list)
    for chunks, retrieved_for in record_maps:
        for chunk in chunks.values():
            if chunk.get("lineage_mode") != "deterministic_passthrough":
                raise ValueError("v1.1 whole-document spans require passthrough lineage")
            if len(chunk.get("source_block_ids", [])) != 1:
                raise ValueError("A passthrough chunk must have one source block")
            chunks_by_block[chunk["source_block_ids"][0]].append((chunk, retrieved_for))

    baseline_chunks = list(record_maps[0][0].values())
    lexical_by_question: dict[str, dict[str, float]] = {}
    for question_id in question_ids:
        ranked = bm25_search(
            questions[question_id]["question"], baseline_chunks, len(baseline_chunks)
        )
        lexical_by_question[question_id] = {
            row["chunk_id"]: row["score"] for row in ranked if row["score"] > 0
        }

    candidates = []
    estimated_edges: list[dict[str, Any]] = []
    candidate_edges: list[dict[str, Any]] = []
    for block in blocks.values():
        for match in NUMERIC_PATTERN.finditer(block["text"]):
            start, end, observed = match.start(), match.end(), match.group(0)
            candidate_id = _candidate_id(
                block["document_id"], block["block_id"], start, end, observed
            )
            overlapping_chunks: set[str] = set()
            descendants: set[str] = set()
            baseline_overlaps: set[str] = set()
            for chunk, retrieved_for in chunks_by_block[block["block_id"]]:
                if max(start, chunk["start"]) < min(end, chunk["end"]):
                    overlapping_chunks.add(chunk["chunk_id"])
                    descendants.update(retrieved_for.get(chunk["chunk_id"], set()))
                    if chunk["chunk_id"] in record_maps[0][0]:
                        baseline_overlaps.add(chunk["chunk_id"])
            estimated_scores = {
                question_id: max(
                    (
                        lexical_by_question[question_id].get(chunk_id, 0.0)
                        for chunk_id in baseline_overlaps
                    ),
                    default=0.0,
                )
                for question_id in question_ids
            }
            estimated_questions = sorted(
                question_id for question_id, score in estimated_scores.items() if score > 0
            )
            observed_questions = sorted(descendants)
            proxy = (1.0 + sum(instability[q] for q in observed_questions)) / (
                2.0 + len(observed_questions)
            )
            observed_reach = len(observed_questions) / len(question_ids)
            candidate = {
                "candidate_id": candidate_id,
                "candidate_type": "numeric_text_span",
                "document_id": block["document_id"],
                "block_id": block["block_id"],
                "page_number": block["page_number"],
                "start": start,
                "end": end,
                "observed_text": observed,
                "descendant_question_ids": observed_questions,
                "estimated_relevant_question_ids": estimated_questions,
                "overlapping_chunk_ids": sorted(overlapping_chunks),
                "features": {
                    "candidate_instability_proxy": round(proxy, 8),
                    "proxy_source": (
                        "baseline_no_op_question_instability_not_span_error_probability"
                    ),
                    "observed_structural_reach": round(observed_reach, 8),
                    "estimated_lexical_reach": round(
                        len(estimated_questions) / len(question_ids), 8
                    ),
                    "ideal_repair_given_detection": 1.0,
                    "repair_assumption": "exact_evaluation_correction_if_controlled_error_detected",
                    "verification_cost": 1,
                    "parser_disagreement": None,
                    "parser_confidence": None,
                },
                "scores": {
                    "uncertainty": round(proxy, 8),
                    "individual_impact": round(proxy * observed_reach, 8),
                },
                "estimated_bm25_scores": {
                    question_id: round(score, 8)
                    for question_id, score in estimated_scores.items()
                    if score > 0
                },
            }
            candidates.append(candidate)
            graph_nodes[candidate_id] = {
                "node_id": candidate_id,
                "node_type": "candidate",
                "block_id": block["block_id"],
                "start": start,
                "end": end,
            }
            candidate_edges.append(
                {
                    "source": candidate_id,
                    "target": block["block_id"],
                    "edge_type": "candidate_in_block",
                    "edge_basis": "exact_source_span",
                }
            )
            for chunk_id in sorted(overlapping_chunks):
                candidate_edges.append(
                    {
                        "source": candidate_id,
                        "target": chunk_id,
                        "edge_type": "candidate_to_chunk",
                        "edge_basis": "deterministic_span_overlap",
                    }
                )
            for question_id in estimated_questions:
                estimated_edges.append(
                    {
                        "source": candidate_id,
                        "target": question_id,
                        "edge_type": "candidate_to_question_estimated",
                        "edge_basis": "positive_full_corpus_bm25_lexical_estimate",
                        "score": candidate["estimated_bm25_scores"][question_id],
                    }
                )

    candidates.sort(key=lambda row: row["candidate_id"])
    observed_edges = [
        {
            "source": source,
            "target": target,
            "edge_type": {
                "chunk_to_question": "chunk_to_question_observed",
                "chunk_to_answer": "chunk_to_answer_observed",
            }.get(edge_type, edge_type),
            "edge_basis": (
                "deterministic_trace_lineage"
                if edge_type in {"source_to_transform", "transform_to_chunk"}
                else "observed_pipeline_trace"
            ),
        }
        for source, target, edge_type in sorted(graph_edges)
    ]
    result = {
        "schema_version": 1,
        "spec_id": spec_id,
        "visible_conditions": ["baseline", "no_op"],
        "question_ids": question_ids,
        "question_instability": instability,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "graph": {
            "node_count": len(graph_nodes),
            "actual_edge_count": len(observed_edges) + len(candidate_edges),
            "estimated_edge_count": len(estimated_edges),
            "nodes": sorted(graph_nodes.values(), key=lambda row: row["node_id"]),
            "actual_edges": [*observed_edges, *candidate_edges],
            "estimated_edges": estimated_edges,
        },
    }
    assert_policy_input_safe(result)
    result["policy_input_sha256"] = digest(result)
    return result


def _repair_matches(case: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, str]:
    matches = {}
    for candidate in candidates:
        for repair in case["repairs"]:
            if candidate["block_id"] != repair["block_id"]:
                continue
            relative_start = repair["start"] - candidate["start"]
            relative_end = repair["end"] - candidate["start"]
            if (
                0 <= relative_start < relative_end <= len(candidate["observed_text"])
                and candidate["observed_text"][relative_start:relative_end] == repair["before"]
            ):
                matches[candidate["candidate_id"]] = repair["candidate_id"]
    return matches


def analyze_distinguishability(
    case: dict[str, Any], policy_input: dict[str, Any], selections: list[dict[str, Any]]
) -> dict[str, Any]:
    candidates = policy_input["candidates"]
    matches = _repair_matches(case, candidates)
    feature_groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    score_groups: dict[tuple[float, float], list[str]] = defaultdict(list)
    by_id = {row["candidate_id"]: row for row in candidates}
    for row in candidates:
        features = row["features"]
        feature_key = (
            features["candidate_instability_proxy"],
            features["observed_structural_reach"],
            features["estimated_lexical_reach"],
            features["ideal_repair_given_detection"],
            features["verification_cost"],
        )
        feature_groups[feature_key].append(row["candidate_id"])
        score_groups[(row["scores"]["uncertainty"], row["scores"]["individual_impact"])].append(
            row["candidate_id"]
        )
    tied_ids = {
        candidate_id for group in score_groups.values() if len(group) > 1 for candidate_id in group
    }
    mixed_groups = []
    for key, group in feature_groups.items():
        repair_ids = sorted(
            matches[candidate_id] for candidate_id in group if candidate_id in matches
        )
        if repair_ids and len(group) > len(repair_ids):
            mixed_groups.append(
                {
                    "feature_tuple": list(key),
                    "candidate_count": len(group),
                    "repair_ids": repair_ids,
                }
            )
    selected_by = {(row["policy"], row["budget"]): row for row in selections}
    set_comparisons = []
    for budget in (1, 2):
        individual = set(selected_by[("individual_impact", budget)]["selected_candidate_ids"])
        graph = set(selected_by[("graph_aware", budget)]["selected_candidate_ids"])
        union = individual | graph
        set_comparisons.append(
            {
                "budget": budget,
                "individual_ids": sorted(individual),
                "graph_aware_ids": sorted(graph),
                "symmetric_difference_count": len(individual ^ graph),
                "jaccard": len(individual & graph) / len(union) if union else 1.0,
            }
        )
    repair_rows = []
    for candidate_id, repair_id in sorted(matches.items(), key=lambda row: row[1]):
        row = by_id[candidate_id]
        repair_rows.append(
            {
                "repair_id": repair_id,
                "candidate_id": candidate_id,
                "observed_text": row["observed_text"],
                "descendant_question_ids": row["descendant_question_ids"],
                "estimated_relevant_question_ids": row["estimated_relevant_question_ids"],
                "features": row["features"],
                "scores": row["scores"],
            }
        )
    return {
        "candidate_count": len(candidates),
        "repair_label_count": len(case["repairs"]),
        "repair_candidate_count": len(matches),
        "candidate_recall": len(matches) / len(case["repairs"]),
        "repair_candidates": repair_rows,
        "zero_observed_reach_count": sum(not row["descendant_question_ids"] for row in candidates),
        "zero_observed_reach_with_estimated_relevance_count": sum(
            not row["descendant_question_ids"] and bool(row["estimated_relevant_question_ids"])
            for row in candidates
        ),
        "unique_feature_tuple_count": len(feature_groups),
        "unique_policy_score_tuple_count": len(score_groups),
        "tied_candidate_count": len(tied_ids),
        "tied_candidate_fraction": len(tied_ids) / len(candidates),
        "feature_identical_mixed_error_normal_group_count": len(mixed_groups),
        "feature_identical_mixed_error_normal_groups": mixed_groups,
        "id_tie_break_selection_count": sum(
            step["id_tie_break_used"] for row in selections for step in row["steps"]
        ),
        "id_tie_breaks_by_policy_budget": [
            {
                "policy": row["policy"],
                "budget": row["budget"],
                "count": sum(step["id_tie_break_used"] for step in row["steps"]),
            }
            for row in selections
        ],
        "individual_vs_graph": set_comparisons,
    }


def preflight(
    case_path: Path, spec_path: Path, config_path: Path, max_calls: int
) -> dict[str, Any]:
    spec = _load_json(spec_path)
    _validate_spec(spec)
    case = _subset_case(_load_json(case_path), spec)
    config = RunnerConfig.load(config_path)
    if config.synthesis_mode != "passthrough":
        raise ValueError("v1.1 diagnostic requires passthrough synthesis")
    executions = len(CONDITIONS)
    questions = len(case["questions"])
    estimate = executions * questions
    return {
        "schema_version": 1,
        "spec_id": spec["spec_id"],
        "pipeline_executions": executions,
        "questions_per_execution": questions,
        "estimated_model_calls": estimate,
        "maximum_output_tokens": estimate * config.qa_max_output_tokens,
        "max_total_calls": max_calls,
        "within_call_budget": estimate <= max_calls,
        "model": config.model,
        "config": config.public_dict(),
    }


def run(
    *,
    case_path: Path,
    spec_path: Path,
    config_path: Path,
    parent_run: Path,
    out: Path,
    max_calls: int,
    timeout: float,
) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Output exists; use a new append-only preserved run directory")
    plan = preflight(case_path, spec_path, config_path, max_calls)
    if not plan["within_call_budget"]:
        raise ValueError("Preflight exceeds the frozen call budget")
    spec = _load_json(spec_path)
    case = _subset_case(_load_json(case_path), spec)
    parent_manifest, parent_records = load_complete_run(parent_run / "targeted_conditions")
    parent_by_condition = {row["condition"]: row for row in parent_records if row["repeat_id"] == 0}
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
        "config_sha256": sha256(config_path.read_bytes()),
        "parent_targeted_manifest_sha256": sha256(
            (parent_run / "targeted_conditions/manifest.json").read_bytes()
        ),
        "parent_run_id": _load_json(parent_run / "manifest.json")["run_id"],
        "parent_targeted_run_id": parent_manifest["run_id"],
        "call_plan": plan,
        **git_state,
    }
    write_json(out / "manifest.json", manifest)
    write_json(out / "frozen_spec.json", spec)
    write_json(out / "frozen_case.json", case)
    write_json(out / "frozen_config.json", _load_json(config_path))
    try:
        policy_input = build_full_document_policy_input(
            case=case,
            baseline_record=parent_by_condition["baseline"],
            no_op_record=parent_by_condition["no_op"],
            question_ids=spec["scope"]["question_ids"],
            spec_id=spec["spec_id"],
        )
        selections = []
        for policy in POLICIES:
            for budget in spec["features_and_policies"]["selection"]["budgets"]:
                selected = select_candidates(
                    policy_input["candidates"],
                    policy=policy,
                    budget=budget,
                    seed_material=[spec["spec_id"], digest(case), policy, budget],
                    question_count=len(spec["scope"]["question_ids"]),
                )
                selected.update(
                    {
                        "schema_version": 1,
                        "spec_id": spec["spec_id"],
                        "policy_input_sha256": policy_input["policy_input_sha256"],
                    }
                )
                selections.append(selected)
        write_jsonl(out / "policy_inputs.jsonl", [policy_input])
        write_jsonl(out / "selections.jsonl", selections)

        # Evaluation-only join occurs after the policy inputs and selections are durable.
        candidate_diagnostics = analyze_distinguishability(case, policy_input, selections)
        write_json(out / "candidate_diagnostics.json", candidate_diagnostics)

        base_command = [
            sys.executable,
            "-m",
            "research.pipeline_runner",
            "run",
            "--config",
            str(config_path.resolve()),
        ]
        records = []
        with (out / "records.jsonl").open("x") as stream:
            for condition, rule in CONDITIONS.items():
                payload = runner_payload(case, rule["repairs"], 0)
                command = [*base_command]
                if rule["oracle"]:
                    command.extend(["--force-evidence-block-id", ORACLE_BLOCK_ID])
                response = _run_payload(command, payload, timeout)
                record = {
                    "execution_id": str(uuid4()),
                    "condition": condition,
                    "source_state": "repaired" if rule["repairs"] else "damaged",
                    "evidence_route": "oracle_evidence" if rule["oracle"] else "general_bm25",
                    "input_sha256": digest(payload),
                    "output_sha256": digest(response),
                    "response": response,
                }
                records.append(record)
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
        pipeline_ids = [row["response"]["metadata"]["pipeline_execution_id"] for row in records]
        calls = sum(row["response"]["metadata"]["call_count"] for row in records)
        if len(set(pipeline_ids)) != len(CONDITIONS):
            raise ValueError("Every diagnostic condition needs a fresh pipeline execution")
        if calls > max_calls:
            raise ValueError("Actual model calls exceeded the frozen budget")
        manifest.update(
            {
                "status": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
                "candidate_count": policy_input["candidate_count"],
                "candidate_recall": candidate_diagnostics["candidate_recall"],
                "completed_model_calls": calls,
                "unique_pipeline_execution_ids": len(pipeline_ids),
                "policy_inputs_sha256": sha256((out / "policy_inputs.jsonl").read_bytes()),
                "selections_sha256": sha256((out / "selections.jsonl").read_bytes()),
                "candidate_diagnostics_sha256": sha256(
                    (out / "candidate_diagnostics.json").read_bytes()
                ),
                "records_sha256": sha256((out / "records.jsonl").read_bytes()),
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


def _answer_has_all(value: str, required: list[str]) -> bool:
    normalized = value.replace(",", "").replace("−", "-")
    return all(item.replace(",", "") in normalized for item in required)


def _blind_template(run_dir: Path, gold_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case = _load_json(run_dir / "frozen_case.json")
    records = read_jsonl(run_dir / "records.jsonl")
    gold = {row["question_id"]: row for row in gold_rows}
    questions = {row["question_id"]: row["question"] for row in case["questions"]}
    blocks = {row["block_id"]: row for row in case["blocks"]}
    result = []
    for record in records:
        _validate_live_response(record["response"])
        retrieved_by_question = {
            row["question_id"]: row["output"]
            for row in record["response"]["trace"]
            if row.get("stage") == "retrieval"
        }
        for answer in record["response"]["answers"]:
            qid = answer["question_id"]
            retrieved = retrieved_by_question[qid]
            result.append(
                {
                    "judgment_id": judgment_id(record, qid),
                    "question_id": qid,
                    "question": questions[qid],
                    "prediction": answer["answer"],
                    "prediction_evidence_block_ids": answer["evidence_block_ids"],
                    "cited_evidence": [
                        {
                            "block_id": block_id,
                            "page_number": blocks[block_id]["page_number"],
                            "text": "\n".join(
                                chunk["text"]
                                for chunk in retrieved
                                if block_id in chunk["source_block_ids"]
                            ),
                        }
                        for block_id in answer["evidence_block_ids"]
                    ],
                    "reference_answer": gold[qid]["reference_answer"],
                    "reference_evidence": gold[qid]["evidence"],
                    "financebench_answer_correct": None,
                    "financebench_evidence_correct": None,
                    "document_answer_correct": None,
                    "document_evidence_correct": None,
                    "judge_id": "",
                    "rationale": "",
                }
            )
    return sorted(result, key=lambda row: row["judgment_id"])


def diagnostic_judgments(template: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in template:
        qid = row["question_id"]
        prediction = row["prediction"]
        cited = set(row["prediction_evidence_block_ids"])
        if qid == GROSS_QUESTION_ID:
            fb_answer = _answer_has_all(
                prediction, ["2022", "2021", "3,502", "3,017", "5.3", "4.8"]
            )
            lowered = prediction.lower()
            fb_answer = (
                fb_answer
                and ("improv" in lowered or "yes" in lowered)
                and prediction.count("%") >= 2
                and ("million" in lowered or "$" in prediction)
            )
            document_answer = fb_answer
        elif qid == TAX_QUESTION_ID:
            fb_answer = (
                _answer_has_all(prediction, ["2022", "2021", "0.62", "-14.76"])
                and prediction.count("%") >= 2
            )
            document_answer = (
                _answer_has_all(prediction, ["2022", "2021", "-0.6"])
                and (_answer_has_all(prediction, ["14.7"]) or _answer_has_all(prediction, ["14.8"]))
                and prediction.count("%") >= 2
            )
        else:
            raise ValueError(f"Unexpected diagnostic question: {qid}")
        fb_evidence = bool(cited & FINANCEBENCH_VALID_BLOCKS[qid])
        document_evidence = bool(cited & DOCUMENT_VALID_BLOCKS[qid])
        output.append(
            {
                **row,
                "financebench_answer_correct": fb_answer,
                "financebench_evidence_correct": fb_evidence,
                "document_answer_correct": document_answer,
                "document_evidence_correct": document_evidence,
                "judge_id": "deterministic-v1.1-dual-reference-development",
                "rationale": (
                    "Strict numeric/direction fixture; evidence requires a pre-audited supporting "
                    "block. The tax item has a known FinanceBench-versus-filing sign conflict."
                ),
            }
        )
    return output


def evaluator_sanity() -> dict[str, Any]:
    base = {
        "judgment_id": "fixture",
        "prediction_evidence_block_ids": [ORACLE_BLOCK_ID],
        "cited_evidence": [],
        "reference_answer": "fixture",
        "reference_evidence": [],
        "financebench_answer_correct": None,
        "financebench_evidence_correct": None,
        "document_answer_correct": None,
        "document_evidence_correct": None,
        "judge_id": "",
        "rationale": "",
        "fixture_kind": "AUTHORED_EVALUATOR_FIXTURE",
    }
    fixtures = [
        {
            **base,
            "question_id": GROSS_QUESTION_ID,
            "question": "fixture",
            "prediction": (
                "Yes, gross profit improved from $3,017 million in FY2021 to "
                "$3,502 million in FY2022 and margin from 4.8% to 5.3%."
            ),
        },
        {
            **base,
            "judgment_id": "fixture-tax-gold",
            "question_id": TAX_QUESTION_ID,
            "question": "fixture",
            "prediction": "FY2022 was 0.62%, compared with -14.76% in FY2021.",
        },
        {
            **base,
            "judgment_id": "fixture-tax-filing",
            "question_id": TAX_QUESTION_ID,
            "question": "fixture",
            "prediction": "The filing reports -0.6% for FY2022 versus 14.8% for FY2021.",
        },
        {
            **base,
            "judgment_id": "fixture-bad",
            "question_id": GROSS_QUESTION_ID,
            "question": "fixture",
            "prediction": "Insufficient evidence",
            "prediction_evidence_block_ids": [],
        },
    ]
    judged = diagnostic_judgments(fixtures)
    checks = [
        judged[0]["financebench_answer_correct"] and judged[0]["financebench_evidence_correct"],
        judged[1]["financebench_answer_correct"] and judged[1]["financebench_evidence_correct"],
        judged[2]["document_answer_correct"] and judged[2]["document_evidence_correct"],
        not judged[3]["financebench_answer_correct"]
        and not judged[3]["financebench_evidence_correct"],
    ]
    return {"status": "pass" if all(checks) else "fail", "checks": checks, "fixtures": judged}


def _retrieved_blocks(record: dict[str, Any], question_id: str) -> set[str]:
    blocks = set()
    for row in record["response"]["trace"]:
        if row.get("stage") == "retrieval" and row.get("question_id") == question_id:
            for chunk in row["output"]:
                blocks.update(chunk["source_block_ids"])
    return blocks


def _oracle_integrity(record: dict[str, Any], repaired: bool) -> dict[str, Any]:
    required = [
        "Consolidated Statements of Operations",
        "Dollars in millions",
        "Years ended December 31, 2022 2021 2020",
        "Total revenues",
        "Total costs and expenses",
        "Loss before income taxes",
        "Income tax (expense)/benefit",
    ]
    expected_numbers = ["66,608", "63,106"] if repaired else ["6,608", "6,106"]
    rows = [row for row in record["response"]["trace"] if row.get("stage") == "qa"]
    checks = []
    for row in rows:
        value = json.loads(row["input_text"])
        texts = [chunk["text"] for chunk in value["retrieved_chunks"]]
        combined = "\n".join(texts)
        checks.append(
            {
                "question_id": row["question_id"],
                "chunk_count": len(texts),
                "context_characters": len(combined),
                "all_required_context_present": all(item in combined for item in required),
                "expected_source_numbers_present": all(
                    item in combined for item in expected_numbers
                ),
                "reference_answer_fields_absent": "reference_answer" not in row["input_text"]
                and "correctness" not in row["input_text"],
            }
        )
    return {
        "checks": checks,
        "pass": all(
            all(v for k, v in row.items() if k.endswith("present") or k.endswith("absent"))
            for row in checks
        ),
    }


def evaluate(run_dir: Path, gold_path: Path) -> dict[str, Any]:
    for name in (
        "judgments.template.jsonl",
        "judgments.jsonl",
        "summary.json",
        "evaluation_manifest.json",
    ):
        if (run_dir / name).exists():
            raise ValueError("Evaluation output exists; do not overwrite append-only artifacts")
    manifest = _load_json(run_dir / "manifest.json")
    if manifest["status"] != "complete":
        raise ValueError("Cannot evaluate an incomplete diagnostic")
    records = read_jsonl(run_dir / "records.jsonl")
    template = _blind_template(run_dir, read_jsonl(gold_path))
    judgments = diagnostic_judgments(template)
    sanity = evaluator_sanity()
    if sanity["status"] != "pass":
        raise ValueError("Authored evaluator sanity fixtures failed")
    write_jsonl(run_dir / "judgments.template.jsonl", template)
    write_jsonl(run_dir / "judgments.jsonl", judgments)
    by_judgment = {row["judgment_id"]: row for row in judgments}
    outcomes = []
    for record in records:
        per_question = []
        for answer in record["response"]["answers"]:
            judged = by_judgment[judgment_id(record, answer["question_id"])]
            per_question.append(
                {
                    "question_id": answer["question_id"],
                    "answer": answer["answer"],
                    "evidence_block_ids": answer["evidence_block_ids"],
                    "financebench_answer_correct": judged["financebench_answer_correct"],
                    "financebench_evidence_correct": judged["financebench_evidence_correct"],
                    "financebench_overall_correct": judged["financebench_answer_correct"]
                    and judged["financebench_evidence_correct"],
                    "document_answer_correct": judged["document_answer_correct"],
                    "document_evidence_correct": judged["document_evidence_correct"],
                    "document_overall_correct": judged["document_answer_correct"]
                    and judged["document_evidence_correct"],
                    "retrieved_block_ids": sorted(_retrieved_blocks(record, answer["question_id"])),
                    "retrieval_has_financebench_sufficient_block": bool(
                        _retrieved_blocks(record, answer["question_id"])
                        & FINANCEBENCH_VALID_BLOCKS[answer["question_id"]]
                    ),
                    "retrieval_has_document_sufficient_block": bool(
                        _retrieved_blocks(record, answer["question_id"])
                        & DOCUMENT_VALID_BLOCKS[answer["question_id"]]
                    ),
                }
            )
        outcomes.append(
            {
                "condition": record["condition"],
                "source_state": record["source_state"],
                "evidence_route": record["evidence_route"],
                "pipeline_execution_id": record["response"]["metadata"]["pipeline_execution_id"],
                "questions": per_question,
            }
        )
    by_condition = {row["condition"]: row for row in records}
    integrity = {
        "C": _oracle_integrity(by_condition["C_damaged_oracle_evidence"], False),
        "D": _oracle_integrity(by_condition["D_repaired_oracle_evidence"], True),
    }
    candidate_diagnostics = _load_json(run_dir / "candidate_diagnostics.json")
    d_gross = next(
        q
        for row in outcomes
        if row["condition"] == "D_repaired_oracle_evidence"
        for q in row["questions"]
        if q["question_id"] == GROSS_QUESTION_ID
    )
    summary = {
        "schema_version": 1,
        "spec_id": manifest["spec_id"],
        "run_id": manifest["run_id"],
        "scope": "development diagnostic only",
        "candidate_diagnostics": candidate_diagnostics,
        "oracle_evidence_integrity": integrity,
        "evaluator_sanity": sanity,
        "condition_outcomes": outcomes,
        "stop_rule_triggered": not d_gross["financebench_overall_correct"],
        "stop_rule_reason": (
            "D failed the non-conflicted gross-margin question; analyze evidence representation/QA"
            if not d_gross["financebench_overall_correct"]
            else None
        ),
        "tax_evaluation_conflict": True,
    }
    write_json(run_dir / "summary.json", summary)
    evaluation_manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "gold_sha256": sha256(gold_path.read_bytes()),
        "judgment_template_sha256": sha256((run_dir / "judgments.template.jsonl").read_bytes()),
        "judgments_sha256": sha256((run_dir / "judgments.jsonl").read_bytes()),
        "summary_sha256": sha256((run_dir / "summary.json").read_bytes()),
        "evaluator_sanity_status": sanity["status"],
    }
    write_json(run_dir / "evaluation_manifest.json", evaluation_manifest)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        command.add_argument("--case", type=Path, required=True)
        command.add_argument("--spec", type=Path, required=True)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--max-total-calls", type=int, required=True)
        if name == "run":
            command.add_argument("--parent-run", type=Path, required=True)
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--timeout", type=float, default=900)
    judge = commands.add_parser("evaluate")
    judge.add_argument("--run", type=Path, required=True)
    judge.add_argument("--gold", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "preflight":
        result = preflight(args.case, args.spec, args.config, args.max_total_calls)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["within_call_budget"]:
            raise SystemExit(2)
    elif args.action == "run":
        result = run(
            case_path=args.case,
            spec_path=args.spec,
            config_path=args.config,
            parent_run=args.parent_run,
            out=args.out,
            max_calls=args.max_total_calls,
            timeout=args.timeout,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = evaluate(args.run, args.gold)
        print(json.dumps(result, ensure_ascii=False, indent=2))


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
        print(f"v1.1 diagnostic stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from error
