"""Pipeline-runner tests use fake generations and are not research results."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from research.canonical_adapter import canonical_to_blocks, convert
from research.pilot import read_jsonl
from research.pipeline_runner import (
    Generation,
    OpenAIResponsesAdapter,
    PipelineError,
    RunnerConfig,
    preflight,
    run_pipeline,
)


class FakeGenerator:
    execution_mode = "test_fake_model"

    def __init__(self) -> None:
        self.calls = []

    def generate(self, *, stage, instructions, input_text, max_output_tokens):
        self.calls.append(
            {
                "stage": stage,
                "instructions": instructions,
                "input_text": input_text,
                "max_output_tokens": max_output_tokens,
            }
        )
        if stage == "synthesis":
            source = json.loads(input_text.splitlines()[0].removeprefix("SOURCE "))
            output = f"[source:{source['block_id']}] revenue was 100."
        else:
            chunk_id = json.loads(input_text)["retrieved_chunks"][0]["chunk_id"]
            output = json.dumps({"answer": "100", "evidence_chunk_ids": [chunk_id]})
        return Generation(
            text=output,
            response_id=f"fake-{len(self.calls)}",
            model="fake-test-model",
            usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        )


@pytest.fixture
def payload():
    return {
        "schema_version": 1,
        "repeat_id": 0,
        "blocks": [
            {
                "block_id": "block-1",
                "canonical_block_id": "block-1",
                "document_id": "doc-1",
                "run_id": "parser-run-1",
                "page_number": 4,
                "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
                "source_kind": "canonical_parser",
                "text": "revenue was 100",
            }
        ],
        "questions": [
            {"question_id": "q1", "document_id": "doc-1", "question": "What was revenue?"}
        ],
    }


def test_pipeline_records_real_stage_io_lineage_retrieval_and_usage(payload):
    fake = FakeGenerator()
    result = run_pipeline(
        payload,
        RunnerConfig(model="fake-test-model", synthesis_batch_chars=1_000),
        fake,
    )
    assert [row["stage"] for row in result["trace"]] == [
        "synthesis",
        "chunking",
        "retrieval",
        "qa",
    ]
    synthesis, chunking, retrieval, qa = result["trace"]
    assert synthesis["input_ids"] == ["block-1"]
    assert synthesis["input_text"].endswith("revenue was 100")
    chunk = chunking["output"][0]
    assert chunk["parent_synthesis_id"] == synthesis["output_id"]
    assert chunk["source_block_ids"] == ["block-1"]
    assert chunk["lineage_mode"] == "explicit_source_markers"
    assert retrieval["output"][0]["score"] >= 0
    assert qa["output"]["evidence_block_ids"] == ["block-1"]
    assert result["answers"][0]["answer"] == "100"
    assert result["metadata"]["call_count"] == 2
    assert result["metadata"]["usage"] == {
        "input_tokens": 4,
        "output_tokens": 2,
        "total_tokens": 6,
    }
    assert result["metadata"]["execution_mode"] == "test_fake_model"
    assert result["metadata"]["source_kinds"] == ["canonical_parser"]


def test_pipeline_rejects_hidden_labels_and_does_not_send_questions_to_synthesis(payload):
    fake = FakeGenerator()
    leaked = {**payload, "condition": "AB"}
    with pytest.raises(ValueError, match="accepts only"):
        run_pipeline(leaked, RunnerConfig(model="fake"), fake)
    run_pipeline(payload, RunnerConfig(model="fake"), fake)
    synthesis_call = next(row for row in fake.calls if row["stage"] == "synthesis")
    assert "What was revenue?" not in synthesis_call["input_text"]
    assert "condition" not in synthesis_call["input_text"]


def test_openai_adapter_fails_closed_on_incomplete_or_empty_response():
    response = SimpleNamespace(
        status="incomplete",
        output_text="partial",
        id="response-1",
        model="fake",
        usage=None,
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **kwargs: response),
    )
    adapter = OpenAIResponsesAdapter(RunnerConfig(model="fake"), client=client)
    with pytest.raises(PipelineError, match="incomplete"):
        adapter.generate(stage="qa", instructions="i", input_text="x", max_output_tokens=10)


def test_openai_adapter_sends_only_configured_supported_generation_settings():
    captured = {}
    response = SimpleNamespace(
        status="completed",
        output_text='{"answer":"ok","evidence_chunk_ids":[]}',
        id="response-1",
        model="fake",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3),
    )

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    adapter = OpenAIResponsesAdapter(
        RunnerConfig(model="fake", reasoning_effort=None, verbosity="low", temperature=0.2),
        client=client,
    )
    generation = adapter.generate(
        stage="qa", instructions="instructions", input_text="input", max_output_tokens=10
    )
    assert captured["store"] is False
    assert captured["temperature"] == 0.2
    assert "reasoning" not in captured and "top_p" not in captured
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert generation.usage["total_tokens"] == 3


def test_config_rejects_conflicting_sampling_controls():
    with pytest.raises(ValueError, match="not both"):
        RunnerConfig(model="fake", temperature=0.2, top_p=0.9).validate()


def test_preflight_counts_all_five_fresh_pipeline_runs(payload):
    case = {
        "schema_version": 1,
        "case_id": "test",
        "blocks": payload["blocks"],
        "questions": payload["questions"],
        "repairs": [
            {
                "candidate_id": "A",
                "block_id": "block-1",
                "start": 12,
                "end": 15,
                "before": "100",
                "after": "101",
                "source_note": "test",
            },
            {
                "candidate_id": "B",
                "block_id": "block-1",
                "start": 0,
                "end": 7,
                "before": "revenue",
                "after": "Revenue",
                "source_note": "test",
            },
        ],
    }
    report = preflight(case, RunnerConfig(model="fake", synthesis_batch_chars=1_000), 1)
    assert report["pipeline_runs"] == 5
    assert report["estimated_model_calls"] == 10
    assert len(report["conditions"]) == 5


def test_canonical_adapter_preserves_document_run_block_page_and_bbox(tmp_path):
    canonical = {
        "schema_version": "1.0",
        "document_id": "doc-1",
        "run_id": "run-9",
        "parser_name": "parser-x",
        "parser_version": "2.1",
        "pages": [
            {
                "page_number": 3,
                "width": 612,
                "height": 792,
                "text": "hello",
                "blocks": [
                    {
                        "id": "original-block-id",
                        "type": "paragraph",
                        "page_number": 3,
                        "reading_order": 7,
                        "text": "hello",
                        "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
                    }
                ],
            }
        ],
    }
    block = canonical_to_blocks(canonical)[0]
    assert (
        block["document_id"],
        block["run_id"],
        block["block_id"],
        block["page_number"],
    ) == ("doc-1", "run-9", "original-block-id", 3)
    assert block["bbox"] == {"x1": 1, "y1": 2, "x2": 3, "y2": 4}
    assert block["source_kind"] == "canonical_parser"

    canonical_path = tmp_path / "canonical.json"
    canonical_path.write_text(json.dumps(canonical))
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        json.dumps({"question_id": "q", "document_id": "doc-1", "question": "Hello?"})
        + "\n"
    )
    out = tmp_path / "converted"
    manifest = convert(canonical_path, questions_path, out)
    assert manifest["source_kind"] == "canonical_parser"
    assert read_jsonl(out / "inputs/blocks.jsonl")[0]["run_id"] == "run-9"

    canonical["pages"][0]["blocks"][0]["page_number"] = 4
    with pytest.raises(ValueError, match="relationship"):
        canonical_to_blocks(canonical)
