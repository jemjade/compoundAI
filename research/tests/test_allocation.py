"""Validity-critical tests for the frozen dependency-aware pilot."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import ClassVar

import pytest

from research.allocation import (
    assert_policy_input_safe,
    build_policy_input,
    graph_overlap,
    select_candidates,
)
from research.allocation_pilot import (
    _condition_record,
    _outcome,
    _validate_live_response,
    deterministic_judgments,
    preflight,
)
from research.pipeline_runner import Generation, RunnerConfig, run_pipeline


class LiveFakeGenerator:
    execution_mode = "live_local_model"
    sdk = "test-live-transport"
    sdk_version = "1"
    provider_runtime: ClassVar[dict[str, str]] = {"model_digest": "test-digest"}

    def generate(self, *, stage, instructions, input_text, max_output_tokens):
        del instructions, max_output_tokens
        assert stage == "qa"
        value = json.loads(input_text)
        chunk_id = value["retrieved_chunks"][0]["chunk_id"]
        answer = "6,608" if "revenue" in value["question"].lower() else "0.62%"
        return Generation(
            text=json.dumps(
                {"answer": answer, "evidence_chunk_ids": [chunk_id]}
            ),
            response_id=f"response-{chunk_id}",
            model="live-fake",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        )


@pytest.fixture
def case():
    return {
        "schema_version": 1,
        "case_id": "allocation-test",
        "blocks": [
            {
                "block_id": "doc:p1",
                "document_id": "doc",
                "page_number": 1,
                "source_kind": "pypdf_page_text",
                "text": "2022 revenue 6,608 cost 6,106 prior 62,286 tax 0.62% 2021 -14.76%",
            }
        ],
        "questions": [
            {
                "question_id": "q1",
                "document_id": "doc",
                "question": "What was revenue in 2022?",
            },
            {
                "question_id": "q2",
                "document_id": "doc",
                "question": "What was the tax rate?",
            },
        ],
        "repairs": [
            {
                "candidate_id": "A",
                "block_id": "doc:p1",
                "start": 13,
                "end": 18,
                "before": "6,608",
                "after": "66,608",
                "source_note": "test-only ideal correction",
            },
            {
                "candidate_id": "B",
                "block_id": "doc:p1",
                "start": 24,
                "end": 29,
                "before": "6,106",
                "after": "63,106",
                "source_note": "test-only ideal correction",
            },
        ],
    }


def _record(case, condition):
    payload = {
        "schema_version": 1,
        "repeat_id": 0,
        "blocks": case["blocks"],
        "questions": case["questions"],
    }
    response = run_pipeline(
        payload,
        RunnerConfig(
            provider="ollama_generate",
            model="live-fake",
            base_url="http://127.0.0.1:11434",
            api_key_env=None,
            synthesis_mode="passthrough",
            chunk_chars=500,
            chunk_overlap_chars=10,
            retrieval_top_k=1,
        ),
        LiveFakeGenerator(),
    )
    return {
        "execution_id": f"execution-{condition}",
        "condition": condition,
        "repeat_id": 0,
        "response": response,
    }


def test_policy_input_enumerates_normal_candidates_without_repair_leakage(case):
    result = build_policy_input(
        case=case,
        baseline_record=_record(case, "baseline"),
        no_op_record=_record(case, "no_op"),
        question_ids=["q1", "q2"],
        spec_id="test-v1",
        repeat_id=0,
    )

    serialized = json.dumps(result)
    assert len(result["candidates"]) > len(case["repairs"])
    assert "66,608" not in serialized and "63,106" not in serialized
    assert "source_note" not in serialized and '"repairs"' not in serialized
    assert all(row["features"]["verification_cost"] == 1 for row in result["candidates"])
    assert all(row["features"]["parser_disagreement"] is None for row in result["candidates"])
    assert result["graph"]["edge_count"] > 0


def _candidate(candidate_id, risk, descendants):
    reach = len(descendants) / 3
    return {
        "candidate_id": candidate_id,
        "descendant_question_ids": descendants,
        "features": {
            "error_risk": risk,
            "expected_repairability": 1.0,
            "verification_cost": 1,
        },
        "scores": {
            "uncertainty": risk,
            "individual_impact": risk * reach,
        },
    }


def test_graph_aware_recomputes_marginal_gain_while_individual_is_fixed():
    candidates = [
        _candidate("c1", 0.9, ["q1", "q2"]),
        _candidate("c2", 1.0, ["q1"]),
        _candidate("c3", 0.9, ["q3"]),
    ]
    individual = select_candidates(
        candidates,
        policy="individual_impact",
        budget=2,
        seed_material=["fixed"],
        question_count=3,
    )
    graph = select_candidates(
        candidates,
        policy="graph_aware",
        budget=2,
        seed_material=["fixed"],
        question_count=3,
    )

    assert individual["selected_candidate_ids"] == ["c1", "c2"]
    assert graph["selected_candidate_ids"] == ["c1", "c3"]
    assert individual["spent_cost"] == graph["spent_cost"] == 2


def test_random_is_seeded_and_every_policy_respects_budget():
    candidates = [_candidate(f"c{i}", 0.5, ["q1"]) for i in range(5)]
    first = select_candidates(
        candidates,
        policy="random",
        budget=2,
        seed_material=["same"],
        question_count=3,
    )
    second = select_candidates(
        candidates,
        policy="random",
        budget=2,
        seed_material=["same"],
        question_count=3,
    )
    assert first == second
    for policy in ("uncertainty", "individual_impact", "graph_aware"):
        selected = select_candidates(
            candidates,
            policy=policy,
            budget=1,
            seed_material=[policy],
            question_count=3,
        )
        assert selected["spent_cost"] == 1
        assert len(selected["selected_candidate_ids"]) == 1


def test_forbidden_evaluation_fields_are_rejected():
    with pytest.raises(ValueError, match="Forbidden"):
        assert_policy_input_safe({"candidates": [{"repair": "secret"}]})
    with pytest.raises(ValueError, match="Forbidden"):
        select_candidates(
            [{"candidate_id": "c", "gold": True}],
            policy="random",
            budget=1,
            seed_material=["x"],
            question_count=1,
        )


def test_graph_overlap_is_structural_only():
    left = {"descendant_question_ids": ["q1", "q2"]}
    right = {"descendant_question_ids": ["q2", "q3"]}
    assert graph_overlap(left, right) == pytest.approx(1 / 3)


def test_selected_normal_candidate_costs_and_reruns_without_edit(monkeypatch, case):
    policy_input = build_policy_input(
        case=case,
        baseline_record=_record(case, "baseline"),
        no_op_record=_record(case, "no_op"),
        question_ids=["q1", "q2"],
        spec_id="test-v1",
        repeat_id=0,
    )
    repaired_spans = {(row["block_id"], row["start"], row["end"]) for row in case["repairs"]}
    normal = next(
        row
        for row in policy_input["candidates"]
        if (row["block_id"], row["start"], row["end"]) not in repaired_spans
    )
    captured = {}

    def fake_run(_command, payload, _timeout):
        captured["payload"] = copy.deepcopy(payload)
        return _record(case, "baseline")["response"]

    monkeypatch.setattr("research.allocation_pilot._run_payload", fake_run)
    selection = {
        "repeat_id": 0,
        "policy": "random",
        "budget": 1,
        "spent_cost": 1,
        "selected_candidate_ids": [normal["candidate_id"]],
        "selected_set_sha256": "set-hash",
    }
    record = _condition_record(
        selection=selection,
        policy_input=policy_input,
        case=case,
        command=["runner"],
        timeout=1,
    )

    assert record["actions"][0]["action"] == "inspected_no_change"
    assert captured["payload"]["blocks"] == case["blocks"]
    assert record["spent_cost"] == 1


def test_selected_repair_candidate_applies_exact_edit_before_fresh_rerun(monkeypatch, case):
    policy_input = build_policy_input(
        case=case,
        baseline_record=_record(case, "baseline"),
        no_op_record=_record(case, "no_op"),
        question_ids=["q1", "q2"],
        spec_id="test-v1",
        repeat_id=0,
    )
    repair = case["repairs"][0]
    selected = next(
        row
        for row in policy_input["candidates"]
        if (row["block_id"], row["start"], row["end"], row["observed_text"])
        == (repair["block_id"], repair["start"], repair["end"], repair["before"])
    )
    captured = {}

    def fake_run(_command, payload, _timeout):
        captured["payload"] = copy.deepcopy(payload)
        return _record(case, "baseline")["response"]

    monkeypatch.setattr("research.allocation_pilot._run_payload", fake_run)
    record = _condition_record(
        selection={
            "repeat_id": 0,
            "policy": "uncertainty",
            "budget": 1,
            "spent_cost": 1,
            "selected_candidate_ids": [selected["candidate_id"]],
            "selected_set_sha256": "set-hash",
        },
        policy_input=policy_input,
        case=case,
        command=["runner"],
        timeout=1,
    )

    assert record["actions"] == [
        {
            "candidate_id": selected["candidate_id"],
            "action": "ideal_exact_repair",
            "repair_candidate_id": "A",
        }
    ]
    assert captured["payload"]["blocks"][0]["text"].startswith("2022 revenue 66,608")
    assert captured["payload"]["blocks"][0]["text"] != case["blocks"][0]["text"]


def test_live_result_gate_rejects_mock_or_incomplete_metadata(case):
    response = _record(case, "baseline")["response"]
    _validate_live_response(response)
    response["metadata"]["execution_mode"] = "test_fake_model"
    with pytest.raises(ValueError, match="live model"):
        _validate_live_response(response)
    response["metadata"]["execution_mode"] = "live_local_model"
    del response["metadata"]["prompt_versions"]
    with pytest.raises(ValueError, match="missing"):
        _validate_live_response(response)


def test_preflight_enforces_frozen_26_call_plan(tmp_path: Path, case):
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps(case))
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "test-v1",
                "status": "FROZEN_EXPLORATORY_PILOT",
                "frozen_before_live_run": True,
                "dataset": {"question_ids": ["q1", "q2"]},
                "initial_runs": {
                    "policy_visible_conditions": ["baseline", "no_op"],
                    "repeats": 1,
                },
                "policies": {"budgets": [1, 2]},
            }
        )
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "ollama_generate",
                "model": "live-fake",
                "base_url": "http://127.0.0.1:11434",
                "api_key_env": None,
                "synthesis_mode": "passthrough",
            }
        )
    )

    report = preflight(case_path, spec_path, config_path, max_total_calls=26)
    assert report["total_pipeline_executions"] == 13
    assert report["estimated_model_calls"] == 26
    assert report["within_call_budget"] is True
    assert preflight(case_path, spec_path, config_path, 25)["within_call_budget"] is False


def test_strict_deterministic_judge_and_recovery_aggregation():
    template = [
        {
            "judgment_id": "j1",
            "prediction": "Yes, improved from 4.8% in 2021 to 5.3% in 2022; 3,017 to 3,502.",
            "reference_answer": "Yes, 3,017 in 2021, 3,502 in 2022, 4.8% to 5.3%.",
            "prediction_evidence_block_ids": ["p55"],
            "reference_evidence": [{"block_id": "p55"}],
        },
        {
            "judgment_id": "j2",
            "prediction": "It improved to 5.3%.",
            "reference_answer": "Yes, 3,017 in 2021, 3,502 in 2022, 4.8% to 5.3%.",
            "prediction_evidence_block_ids": [],
            "reference_evidence": [{"block_id": "p55"}],
        },
    ]
    judged = deterministic_judgments(template)
    assert judged[0]["answer_correct"] is True
    assert judged[0]["evidence_correct"] is True
    assert judged[1]["answer_correct"] is False
    assert judged[1]["evidence_correct"] is False

    baseline = {"q1": False, "q2": True}
    assert _outcome({"q1": True, "q2": False}, baseline) == {
        "correct_count": 1,
        "question_count": 2,
        "accuracy": 0.5,
        "recovered_question_ids": ["q1"],
        "regressed_question_ids": ["q2"],
        "net_recovery": 0,
    }
