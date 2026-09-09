import json
from pathlib import Path
from typing import ClassVar

import pytest

from research.budgeted_ollama import BudgetedOllamaGenerator
from research.calculator_qa import (
    ShortCalculatorError,
    build_short_source_registry,
    execute_plan,
    execute_short_plan,
    extract_numeric_sources,
    prepare_short_planner_contract,
    run_short_calculator_qa,
)
from research.development_v1_4 import build_amd_repair_state
from research.pipeline_runner import Generation, PipelineError, RunnerConfig


def _amd_block() -> list[dict]:
    cells = [
        {
            "id": "year",
            "row": 0,
            "column": 1,
            "text": "2022",
            "attributes": {"column_header": True},
        },
        {
            "id": "cash-label",
            "row": 1,
            "column": 0,
            "text": "Cash and cash equivalents",
            "attributes": {"row_header": True},
        },
        {"id": "cash", "row": 1, "column": 1, "text": "4,835", "attributes": {}},
        {
            "id": "ar-label",
            "row": 2,
            "column": 0,
            "text": "Accounts receivable, net",
            "attributes": {"row_header": True},
        },
        {"id": "ar", "row": 2, "column": 1, "text": "4,126", "attributes": {}},
    ]
    return [
        {
            "block_id": "table",
            "document_id": "AMD",
            "page_number": 56,
            "text": "",
            "cells": cells,
        }
    ]


def test_repair_changes_only_current_state_cells():
    damaged, labels = build_amd_repair_state(_amd_block(), ())
    restored, _ = build_amd_repair_state(_amd_block(), ("A",))
    damaged_sources = {
        row["cell_id"]: row["value"] for row in extract_numeric_sources(damaged)
    }
    restored_sources = {
        row["cell_id"]: row["value"] for row in extract_numeric_sources(restored)
    }
    assert labels["A"]["observed_text"] == "835"
    assert damaged_sources["cash"] == "835"
    assert damaged_sources["ar"] == "126"
    assert restored_sources["cash"] == "4835"
    assert restored_sources["ar"] == "126"


def test_executor_records_operands_and_rejects_unknown_sources():
    sources = [
        {"source_id": "a", "value": "4", "row_label": "x"},
        {"source_id": "b", "value": "2", "row_label": "y"},
    ]
    plan = {
        "metric_name": "test",
        "metric_definition_id": "relative_change_v1",
        "metric_definition": "change",
        "inputs": [
            {
                "alias": "new",
                "source_id": "a",
                "role": "new",
                "row_label": "x",
                "period": "2022",
                "unit": "",
            },
            {
                "alias": "old",
                "source_id": "b",
                "role": "old",
                "row_label": "y",
                "period": "2021",
                "unit": "",
            },
        ],
        "steps": [
            {
                "step_id": "change",
                "operation": "percent_change",
                "operands": ["new", "old"],
            }
        ],
        "outputs": [{"name": "change_percent", "ref": "change"}],
    }
    result = execute_plan(plan, sources)
    assert result["steps"][0]["operands"] == ["4", "2"]
    assert result["steps"][0]["result"] == "100"
    plan["inputs"][0]["source_id"] = "gold-value-not-present"
    with pytest.raises(PipelineError):
        execute_plan(plan, sources)


def test_budget_counts_failed_attempt_before_call(tmp_path: Path):
    config = RunnerConfig(
        provider="ollama_generate",
        model="llama3:latest",
        base_url="http://127.0.0.1:11434",
        api_key_env=None,
        max_retries=0,
    )
    generator = BudgetedOllamaGenerator.__new__(BudgetedOllamaGenerator)
    generator.config = config
    generator.ledger_dir = tmp_path
    generator.hard_limit = 1
    generator.call_count = 0

    class Failing:
        provider_runtime: ClassVar = {"injected": True}
        sdk_version = "test"

        def generate_with_schema(self, **_kwargs):
            raise RuntimeError("boom")

    generator.adapter = Failing()
    with pytest.raises(RuntimeError):
        generator.generate_structured(
            stage="plan",
            instructions="x",
            input_text="{}",
            max_output_tokens=1,
            response_schema={},
        )
    assert generator.call_count == 1
    assert json.loads((tmp_path / "call-001.json").read_text())["status"] == "failed"
    with pytest.raises(PipelineError):
        generator.generate_structured(
            stage="plan",
            instructions="x",
            input_text="{}",
            max_output_tokens=1,
            response_schema={},
        )


def test_short_registry_keeps_full_provenance_outside_compact_prompt():
    blocks = _amd_block()
    blocks[0]["cells"][2]["bbox"] = {"x1": 1, "y1": 2, "x2": 3, "y2": 4}
    question = {
        "question_id": "hidden-id",
        "document_id": "hidden-document",
        "question": "Calculate a ratio from the evidence.",
    }
    prepared = prepare_short_planner_contract(
        question=question, blocks=blocks, num_ctx=8192
    )
    assert prepared["candidate_reduction"].startswith("none")
    assert "hidden-id" not in prepared["input_text"]
    assert "hidden-document" not in prepared["input_text"]
    assert "bbox" not in prepared["input_text"]
    cash = next(
        row
        for row in prepared["registry"]
        if row["full_source"].get("cell_id") == "cash"
    )
    assert cash["short_id"].startswith("s")
    assert cash["original_source_id"] == cash["full_source"]["source_id"]
    assert cash["full_source"]["bbox"] == {"x1": 1, "y1": 2, "x2": 3, "y2": 4}
    assert prepared["token_estimate"]["fits"] is True
    assert prepared["token_estimate"]["maximum_plan_fits_output_budget"] is True


def test_short_executor_uses_current_sources_and_rejects_forward_reference():
    registry = build_short_source_registry(_amd_block())
    cash = next(row["short_id"] for row in registry if row["full_source"].get("cell_id") == "cash")
    receivable = next(
        row["short_id"]
        for row in registry
        if row["full_source"].get("cell_id") == "ar"
    )
    plan = {
        "metric_id": "quick_ratio_liquid_components_v1",
        "inputs": [
            {"role": "component", "source": cash},
            {"role": "component", "source": receivable},
        ],
        "steps": [{"op": "add", "args": [cash, receivable]}],
        "outputs": ["r0"],
    }
    result = execute_short_plan(plan, registry)
    assert result["steps"][0]["operands"] == ["4835", "4126"]
    assert result["steps"][0]["result"] == "8961"
    plan["steps"][0]["args"] = ["r0"]
    with pytest.raises(PipelineError, match="forward/cyclic"):
        execute_short_plan(plan, registry)


def test_short_pipeline_records_source_operation_result_answer_chain():
    blocks = _amd_block()
    registry = build_short_source_registry(blocks)
    cash = next(row["short_id"] for row in registry if row["full_source"].get("cell_id") == "cash")
    receivable = next(
        row["short_id"]
        for row in registry
        if row["full_source"].get("cell_id") == "ar"
    )
    outputs = iter(
        [
            {
                "metric_id": "quick_ratio_liquid_components_v1",
                "inputs": [
                    {"role": "component", "source": cash},
                    {"role": "component", "source": receivable},
                ],
                "steps": [{"op": "add", "args": [cash, receivable]}],
                "outputs": ["r0"],
            },
            {
                "conclusion": "The calculated total is 8,961.",
                "explanation": "The program added the two current sources.",
                "calculations": [f"r0 = {cash} + {receivable} = 8961"],
                "sources": [cash, receivable],
                "results": ["r0"],
            },
        ]
    )

    class FakeGenerator:
        call_count = 0

        def generate_structured(self, **_kwargs):
            self.call_count += 1
            value = next(outputs)
            return Generation(
                text=json.dumps(value),
                response_id=f"fake-{self.call_count}",
                model="fake",
                usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                status="completed",
            )

    result = run_short_calculator_qa(
        question={
            "question_id": "q",
            "document_id": "AMD",
            "question": "Add the two values.",
        },
        blocks=blocks,
        generator=FakeGenerator(),
        num_ctx=8192,
    )
    assert result["stage_status"] == {
        "planner_call": "COMPLETED",
        "format_validation": "PASSED",
        "reference_validation": "PASSED",
        "arithmetic_execution": "PASSED",
        "answerer_call": "COMPLETED",
        "answer_contract_validation": "PASSED",
    }
    assert any(edge["kind"] == "current_source_calculator_operand" for edge in result["dependency_edges"])
    assert any(edge["kind"] == "answer_declared_program_result" for edge in result["dependency_edges"])


def test_short_pipeline_fail_closes_undeclared_step_source_before_arithmetic():
    blocks = _amd_block()
    registry = build_short_source_registry(blocks)
    cash = next(row["short_id"] for row in registry if row["full_source"].get("cell_id") == "cash")
    receivable = next(
        row["short_id"]
        for row in registry
        if row["full_source"].get("cell_id") == "ar"
    )

    class InvalidGenerator:
        call_count = 0

        def generate_structured(self, **_kwargs):
            self.call_count += 1
            return Generation(
                text=json.dumps(
                    {
                        "metric_id": "quick_ratio_liquid_components_v1",
                        "inputs": [{"role": "component", "source": cash}],
                        "steps": [{"op": "add", "args": [cash, receivable]}],
                        "outputs": ["r0"],
                    }
                ),
                response_id="fake-invalid",
                model="fake",
                usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                status="completed",
            )

    with pytest.raises(ShortCalculatorError) as captured:
        run_short_calculator_qa(
            question={
                "question_id": "q",
                "document_id": "AMD",
                "question": "Add the two values.",
            },
            blocks=blocks,
            generator=InvalidGenerator(),
            num_ctx=8192,
        )
    assert captured.value.trace["format_validation"] == "PASSED"
    assert captured.value.trace["reference_validation"] == "FAILED"
    assert captured.value.trace["arithmetic_execution"] == "NOT_STARTED"
    assert captured.value.trace["answerer_call"] == "NOT_STARTED"
