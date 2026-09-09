import json
from pathlib import Path
from typing import ClassVar

import pytest

from research.budgeted_ollama import BudgetedOllamaGenerator
from research.calculator_qa import execute_plan, extract_numeric_sources
from research.development_v1_4 import build_amd_repair_state
from research.pipeline_runner import PipelineError, RunnerConfig


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
