"""Leakage-controlled candidate generation and budgeted verification policies.

This module intentionally knows nothing about repair labels or reference answers.  It consumes
only corrupted source blocks and policy-visible baseline/no-op traces.  Repair labels are joined
later by :mod:`research.allocation_pilot`, after selections have been serialized.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections import defaultdict
from typing import Any

from research.pilot import digest

NUMERIC_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])\(?[-+$]?\d[\d,]*(?:\.\d+)?%?\)?(?![A-Za-z0-9_])"
)
POLICIES = ("random", "uncertainty", "individual_impact", "graph_aware")
FORBIDDEN_POLICY_KEYS = {
    "after",
    "correct",
    "corrected_text",
    "gold",
    "reference_answer",
    "reference_evidence",
    "repair",
    "repairs",
    "source_note",
    "target_condition",
}


def normalize_answer(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def _answer_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["question_id"]: row for row in record["response"]["answers"]}


def _question_instability(
    baseline: dict[str, Any], no_op: dict[str, Any], question_ids: list[str]
) -> dict[str, float]:
    first, second = _answer_map(baseline), _answer_map(no_op)
    if set(first) != set(question_ids) or set(second) != set(question_ids):
        raise ValueError("Policy-visible runs do not contain the frozen question set")
    values: dict[str, float] = {}
    for question_id in question_ids:
        answer_changed = normalize_answer(first[question_id]["answer"]) != normalize_answer(
            second[question_id]["answer"]
        )
        first_evidence = set(first[question_id].get("evidence_block_ids", []))
        second_evidence = set(second[question_id].get("evidence_block_ids", []))
        values[question_id] = round(
            0.5 * float(answer_changed)
            + 0.5 * (1.0 - jaccard(first_evidence, second_evidence)),
            8,
        )
    return values


def _trace_parts(record: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    chunks: dict[str, dict[str, Any]] = {}
    retrievals: list[dict[str, Any]] = []
    for row in record["response"].get("trace", []):
        if row.get("stage") == "chunking":
            for chunk in row.get("output", []):
                if chunk.get("lineage_mode") != "deterministic_passthrough":
                    raise ValueError(
                        "experiment_spec_v1 requires deterministic passthrough lineage"
                    )
                chunks[chunk["chunk_id"]] = chunk
        elif row.get("stage") == "retrieval":
            retrievals.append(row)
    if not chunks or not retrievals:
        raise ValueError("Policy-visible runs need chunking and retrieval traces")
    return chunks, retrievals


def _candidate_id(
    document_id: str, block_id: str, start: int, end: int, observed_text: str
) -> str:
    value = digest([document_id, block_id, start, end, observed_text])[:24]
    return f"candidate:{value}"


def _add_graph_trace(
    graph_nodes: dict[str, dict[str, Any]],
    graph_edges: set[tuple[str, str, str]],
    record: dict[str, Any],
) -> None:
    response = record["response"]
    condition = record["condition"]
    execution_id = response["metadata"]["pipeline_execution_id"]
    for row in response.get("trace", []):
        stage = row.get("stage")
        if stage in {"passthrough", "synthesis"}:
            transform_id = row["output_id"]
            graph_nodes[transform_id] = {
                "node_id": transform_id,
                "node_type": "transform",
                "stage": stage,
                "condition": condition,
                "execution_id": execution_id,
            }
            for source_id in row.get("input_ids", []):
                graph_edges.add((source_id, transform_id, "source_to_transform"))
        elif stage == "chunking":
            for chunk in row.get("output", []):
                chunk_id = chunk["chunk_id"]
                graph_nodes[chunk_id] = {
                    "node_id": chunk_id,
                    "node_type": "chunk",
                    "condition": condition,
                    "execution_id": execution_id,
                    "start": chunk["start"],
                    "end": chunk["end"],
                    "source_block_ids": chunk["source_block_ids"],
                }
                graph_edges.add(
                    (chunk["parent_synthesis_id"], chunk_id, "transform_to_chunk")
                )
        elif stage == "retrieval":
            question_id = row["question_id"]
            for chunk in row.get("output", []):
                graph_edges.add((chunk["chunk_id"], question_id, "chunk_to_question"))
        elif stage == "qa":
            answer_id = f"answer:{execution_id}:{row['question_id']}"
            graph_nodes[answer_id] = {
                "node_id": answer_id,
                "node_type": "answer",
                "question_id": row["question_id"],
                "condition": condition,
                "execution_id": execution_id,
            }
            for chunk_id in row.get("output", {}).get("evidence_chunk_ids", []):
                graph_edges.add((chunk_id, answer_id, "chunk_to_answer"))


def build_policy_input(
    *,
    case: dict[str, Any],
    baseline_record: dict[str, Any],
    no_op_record: dict[str, Any],
    question_ids: list[str],
    spec_id: str,
    repeat_id: int,
) -> dict[str, Any]:
    """Build candidates/features/graph without accepting repair or gold arguments."""
    if baseline_record.get("condition") != "baseline" or no_op_record.get("condition") != "no_op":
        raise ValueError("Only baseline and no_op may be policy-visible")
    if baseline_record.get("repeat_id") != repeat_id or no_op_record.get("repeat_id") != repeat_id:
        raise ValueError("Policy-visible record repeat mismatch")

    blocks = {block["block_id"]: block for block in case["blocks"]}
    questions = {
        row["question_id"]: row
        for row in case["questions"]
        if row["question_id"] in question_ids
    }
    if set(questions) != set(question_ids):
        raise ValueError("Frozen questions are missing from the case")

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

    candidate_rows: dict[tuple[str, int, int], dict[str, Any]] = {}
    candidate_chunks: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    candidate_questions: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    candidate_observations: dict[tuple[str, int, int], set[str]] = defaultdict(set)

    for record in (baseline_record, no_op_record):
        _add_graph_trace(graph_nodes, graph_edges, record)
        chunks, retrievals = _trace_parts(record)
        condition = record["condition"]
        for retrieval in retrievals:
            question_id = retrieval["question_id"]
            if question_id not in questions:
                continue
            for retrieved in retrieval.get("output", []):
                chunk = chunks.get(retrieved["chunk_id"])
                if chunk is None or len(chunk.get("source_block_ids", [])) != 1:
                    raise ValueError("A retrieved passthrough chunk must map to one source block")
                block_id = chunk["source_block_ids"][0]
                block = blocks[block_id]
                chunk_text = chunk["text"]
                for match in NUMERIC_PATTERN.finditer(chunk_text):
                    start = chunk["start"] + match.start()
                    end = chunk["start"] + match.end()
                    observed = block["text"][start:end]
                    if observed != match.group(0):
                        raise ValueError("Candidate span does not match the frozen source block")
                    key = (block_id, start, end)
                    candidate_rows[key] = {
                        "candidate_id": _candidate_id(
                            block["document_id"], block_id, start, end, observed
                        ),
                        "candidate_type": "numeric_text_span",
                        "document_id": block["document_id"],
                        "block_id": block_id,
                        "page_number": block["page_number"],
                        "start": start,
                        "end": end,
                        "observed_text": observed,
                    }
                    candidate_chunks[key].add(chunk["chunk_id"])
                    candidate_questions[key].add(question_id)
                    candidate_observations[key].add(condition)

    instability = _question_instability(baseline_record, no_op_record, question_ids)
    candidates = []
    for key, base in candidate_rows.items():
        descendants = sorted(candidate_questions[key])
        risk = (1.0 + sum(instability[q] for q in descendants)) / (
            2.0 + len(descendants)
        )
        reach = len(descendants) / len(question_ids)
        repairability = 1.0
        cost = 1
        candidate = {
            **base,
            "descendant_question_ids": descendants,
            "overlapping_chunk_ids": sorted(candidate_chunks[key]),
            "observed_in_conditions": sorted(candidate_observations[key]),
            "features": {
                "error_risk": round(risk, 8),
                "risk_source": "laplace_smoothed_baseline_no_op_instability",
                "structural_reach": round(reach, 8),
                "expected_repairability": repairability,
                "repairability_source": "ideal_exact_repair_conditional_constant",
                "verification_cost": cost,
                "parser_disagreement": None,
                "parser_confidence": None,
            },
            "scores": {
                "uncertainty": round(risk / cost, 8),
                "individual_impact": round(
                    risk * repairability * reach / cost, 8
                ),
            },
        }
        candidates.append(candidate)
        candidate_node_id = candidate["candidate_id"]
        graph_nodes[candidate_node_id] = {
            "node_id": candidate_node_id,
            "node_type": "candidate",
            "block_id": candidate["block_id"],
            "start": candidate["start"],
            "end": candidate["end"],
        }
        graph_edges.add((candidate_node_id, candidate["block_id"], "candidate_in_block"))
        for chunk_id in candidate["overlapping_chunk_ids"]:
            graph_edges.add((candidate_node_id, chunk_id, "candidate_to_chunk"))

    candidates.sort(key=lambda row: row["candidate_id"])
    if not candidates:
        raise ValueError("Candidate generation produced no numeric spans")
    graph = {
        "schema_version": 1,
        "spec_id": spec_id,
        "repeat_id": repeat_id,
        "node_count": len(graph_nodes),
        "edge_count": len(graph_edges),
        "nodes": sorted(graph_nodes.values(), key=lambda row: row["node_id"]),
        "edges": [
            {"source": source, "target": target, "edge_type": edge_type}
            for source, target, edge_type in sorted(graph_edges)
        ],
    }
    result = {
        "schema_version": 1,
        "spec_id": spec_id,
        "repeat_id": repeat_id,
        "visible_conditions": ["baseline", "no_op"],
        "question_ids": question_ids,
        "question_instability": instability,
        "candidates": candidates,
        "graph": graph,
    }
    assert_policy_input_safe(result)
    return result


def assert_policy_input_safe(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        forbidden = {str(key).lower() for key in value} & FORBIDDEN_POLICY_KEYS
        if forbidden:
            raise ValueError(f"Forbidden policy-input keys at {path}: {sorted(forbidden)}")
        for key, item in value.items():
            assert_policy_input_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_policy_input_safe(item, f"{path}[{index}]")


def graph_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    first = set(left["descendant_question_ids"])
    second = set(right["descendant_question_ids"])
    union = first | second
    return round(len(first & second) / len(union), 8) if union else 0.0


def _seed(seed_material: list[Any]) -> int:
    encoded = json.dumps(seed_material, sort_keys=True, ensure_ascii=False).encode()
    return int(hashlib.sha256(encoded).hexdigest(), 16)


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    policy: str,
    budget: int,
    seed_material: list[Any],
    question_count: int,
) -> dict[str, Any]:
    if policy not in POLICIES:
        raise ValueError(f"Unknown policy: {policy}")
    if type(budget) is not int or budget < 1:
        raise ValueError("Budget must be a positive integer")
    if question_count < 1:
        raise ValueError("question_count must be positive")
    assert_policy_input_safe(candidates)
    by_id = {row["candidate_id"]: row for row in candidates}
    if len(by_id) != len(candidates):
        raise ValueError("Duplicate candidate IDs")

    selected: list[str] = []
    steps: list[dict[str, Any]] = []
    spent = 0
    if policy == "random":
        ordered = sorted(candidates, key=lambda row: row["candidate_id"])
        random.Random(_seed(seed_material)).shuffle(ordered)
        for row in ordered:
            cost = row["features"]["verification_cost"]
            if spent + cost > budget:
                continue
            selected.append(row["candidate_id"])
            spent += cost
            steps.append(
                {
                    "candidate_id": row["candidate_id"],
                    "score_at_selection": None,
                    "spent_after": spent,
                }
            )
            if spent == budget:
                break
    elif policy in {"uncertainty", "individual_impact"}:
        ordered = sorted(
            candidates,
            key=lambda row: (-row["scores"][policy], row["candidate_id"]),
        )
        for row in ordered:
            cost = row["features"]["verification_cost"]
            if spent + cost > budget:
                continue
            selected.append(row["candidate_id"])
            spent += cost
            steps.append(
                {
                    "candidate_id": row["candidate_id"],
                    "score_at_selection": row["scores"][policy],
                    "spent_after": spent,
                }
            )
            if spent == budget:
                break
    else:
        descendant_counts: dict[str, int] = defaultdict(int)
        remaining = set(by_id)
        while remaining:
            options = []
            for candidate_id in remaining:
                row = by_id[candidate_id]
                cost = row["features"]["verification_cost"]
                if spent + cost > budget:
                    continue
                marginal = (
                    row["features"]["error_risk"]
                    * row["features"]["expected_repairability"]
                    / (cost * question_count)
                    * sum(
                        1.0 / (1.0 + descendant_counts[question_id])
                        for question_id in row["descendant_question_ids"]
                    )
                )
                options.append((round(marginal, 8), candidate_id))
            if not options:
                break
            score, candidate_id = min(options, key=lambda row: (-row[0], row[1]))
            selected.append(candidate_id)
            remaining.remove(candidate_id)
            spent += by_id[candidate_id]["features"]["verification_cost"]
            for question_id in by_id[candidate_id]["descendant_question_ids"]:
                descendant_counts[question_id] += 1
            steps.append(
                {
                    "candidate_id": candidate_id,
                    "score_at_selection": score,
                    "spent_after": spent,
                }
            )
            if spent == budget:
                break

    return {
        "policy": policy,
        "budget": budget,
        "selected_candidate_ids": selected,
        "spent_cost": spent,
        "steps": steps,
        "selected_set_sha256": digest(selected),
    }
