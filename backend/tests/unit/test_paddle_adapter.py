"""실제 모델 다운로드 없이 PP-StructureV3 Adapter 경계를 검증한다."""

import asyncio
import threading
import time
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.parsers.paddle_structure import (
    PPStructureRuntime,
    PPStructureV3Adapter,
    json_safe,
    validate_paddle_input,
)
from app.core.config import Settings
from app.core.exceptions import AppError
from app.normalizers.paddle_normalizer import normalize_paddle_response


class _Value(Enum):
    READY = "ready"


class _Array:
    def tolist(self) -> list[list[float]]:
        return [[1.0, 2.0], [3.0, 4.0]]


class _NestedJson:
    json = {"block_label": "table", "block_content": "kept"}


class _Result:
    def __init__(self, page_index: int = 0) -> None:
        self.json = {
            "res": {
                "page_index": page_index,
                "width": 100,
                "height": 200,
                "parsing_res_list": [
                    {
                        "block_id": 7,
                        "block_label": "doc_title",
                        "block_content": "테스트 제목",
                        "block_bbox": [1, 2, 30, 40],
                        "block_order": 0,
                        "score": 0.99,
                    },
                    {
                        "block_label": "table",
                        "block_content": "A B",
                        "block_bbox": [1, 50, 90, 100],
                        "block_order": 1,
                    },
                ],
                "table_res_list": [
                    {
                        "pred_html": "<table><tr><td>A</td></tr></table>",
                        "cell_box_list": [[1, 50, 20, 70]],
                    }
                ],
                "array": _Array(),
            }
        }
        self.markdown = {"markdown_texts": "# 테스트 제목\n\n|A|\n|-|"}


class _InvalidResult:
    @property
    def json(self) -> object:
        raise RuntimeError("synthetic result conversion failure")

    @property
    def markdown(self) -> dict[str, str]:
        return {}


class _MarkdownFailureResult(_Result):
    @property
    def markdown(self) -> dict[str, str]:
        raise KeyError("page_continuation_flags")

    @markdown.setter
    def markdown(self, _value: object) -> None:
        pass


class _Pipeline:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        delay: float = 0,
        results: list[object] | None = None,
    ) -> None:
        self.failure = failure
        self.delay = delay
        self.results = results
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.calls: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> list[object]:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.calls.append(kwargs)
            if self.delay:
                time.sleep(self.delay)
            if self.failure is not None:
                raise self.failure
            return self.results if self.results is not None else [_Result()]
        finally:
            with self._lock:
                self.active -= 1

    def concatenate_markdown_pages(self, pages: list[object]) -> str:
        return "\n\n".join(
            str(page["markdown_texts"])
            for page in pages
            if isinstance(page, dict) and page.get("markdown_texts")
        )


def _settings(**overrides: object) -> Settings:
    values = {
        "paddleocr_enabled": True,
        "paddleocr_device": "cpu",
        "paddleocr_max_concurrency": 1,
        "paddleocr_use_doc_orientation": True,
        "paddleocr_use_doc_unwarping": True,
        "paddleocr_use_textline_orientation": True,
        "paddleocr_use_table_recognition": True,
        "paddleocr_use_formula_recognition": False,
        "paddleocr_use_chart_recognition": False,
        "paddleocr_use_seal_recognition": False,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def _connector() -> SimpleNamespace:
    return SimpleNamespace(
        name="PaddleOCR PP-StructureV3",
        model_version="3.7.0",
        adapter_key="pp_structure_v3",
    )


def _pdf(tmp_path: Path, name: str = "sample.pdf") -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4\nsynthetic test fixture")
    return path


async def test_adapter_is_lazy_reuses_pipeline_and_normalizes(tmp_path: Path) -> None:
    created: list[dict[str, object]] = []
    pipeline = _Pipeline()

    def factory(**kwargs: object) -> _Pipeline:
        created.append(kwargs)
        return pipeline

    settings = _settings()
    runtime = PPStructureRuntime(settings, pipeline_factory=factory)
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)
    second_adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)
    input_path = _pdf(tmp_path)

    assert runtime.initialized is False
    first = await adapter.parse(input_path, tmp_path, {})
    second = await second_adapter.parse(input_path, tmp_path, {})

    assert runtime.initialized is True
    assert runtime.initialization_count == 1
    assert len(created) == 1
    assert created[0]["device"] == "cpu"
    assert created[0]["engine"] == "paddle"
    assert len(pipeline.calls) == 2
    assert first.raw_data["document"]["page_count"] == 1
    assert first.markdown == "# 테스트 제목\n\n|A|\n|-|"
    assert first.text == "테스트 제목\n\nA B"
    assert second.metrics["device"] == "cpu"

    canonical = await adapter.normalize(first, document_id="document-1", run_id="run-1")
    assert canonical.full_text == "테스트 제목\n\nA B"
    assert canonical.pages[0].blocks[0].type == "title"
    assert canonical.pages[0].blocks[1].type == "table"
    assert canonical.pages[0].blocks[1].html == "<table><tr><td>A</td></tr></table>"
    assert canonical.pages[0].blocks[1].cells[0].text == "A"
    assert canonical.pages[0].blocks[1].cells[0].bbox is not None
    assert (
        canonical.pages[0].blocks[1].cells[0].attributes["coordinate_alignment_verified"] is False
    )
    assert canonical.pages[0].blocks[0].bbox is not None


async def test_inference_concurrency_is_bounded_to_one(tmp_path: Path) -> None:
    pipeline = _Pipeline(delay=0.05)
    settings = _settings()
    runtime = PPStructureRuntime(settings, pipeline_factory=lambda **_: pipeline)
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)
    one = _pdf(tmp_path, "one.pdf")
    two = _pdf(tmp_path, "two.pdf")

    await asyncio.gather(
        adapter.parse(one, tmp_path, {}),
        adapter.parse(two, tmp_path, {}),
    )

    assert pipeline.max_active == 1


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        ("sample.txt", b"plain text", "UNSUPPORTED_FILE_TYPE"),
        ("empty.pdf", b"", "INVALID_INPUT_FILE"),
        ("corrupt.pdf", b"not-pdf", "INVALID_INPUT_FILE"),
        ("corrupt.png", b"not-png", "INVALID_INPUT_FILE"),
    ],
)
def test_input_validation_rejects_invalid_files(
    tmp_path: Path,
    filename: str,
    content: bytes,
    code: str,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)

    with pytest.raises(AppError) as caught:
        validate_paddle_input(path)

    assert caught.value.code == code


def test_input_validation_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AppError) as caught:
        validate_paddle_input(tmp_path / "missing.pdf")

    assert caught.value.code == "INPUT_FILE_NOT_FOUND"


@pytest.mark.parametrize(
    ("config", "expected_code"),
    [
        ({"unknown": True}, "PARSER_CONFIG_INVALID"),
        ({"use_table_recognition": "true"}, "PARSER_CONFIG_INVALID"),
        ({"use_formula_recognition": True}, "PARSER_CONFIG_INVALID"),
    ],
)
async def test_adapter_rejects_invalid_options(
    tmp_path: Path,
    config: dict[str, object],
    expected_code: str,
) -> None:
    settings = _settings()
    runtime = PPStructureRuntime(settings, pipeline_factory=lambda **_: _Pipeline())
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    with pytest.raises(AppError) as caught:
        await adapter.parse(_pdf(tmp_path), tmp_path, config)

    assert caught.value.code == expected_code
    assert runtime.initialized is False


async def test_disabled_adapter_fails_before_model_initialization(tmp_path: Path) -> None:
    settings = _settings(paddleocr_enabled=False)
    runtime = PPStructureRuntime(settings, pipeline_factory=lambda **_: _Pipeline())
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    with pytest.raises(AppError) as caught:
        await adapter.parse(_pdf(tmp_path), tmp_path, {})

    assert caught.value.code == "PADDLEOCR_DISABLED"
    assert runtime.initialized is False


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (RuntimeError("synthetic inference error"), "PARSING_FAILED"),
        (RuntimeError("CUDA out of memory"), "OUT_OF_MEMORY"),
    ],
)
async def test_inference_errors_have_stable_codes(
    tmp_path: Path,
    failure: Exception,
    expected_code: str,
) -> None:
    settings = _settings()
    runtime = PPStructureRuntime(
        settings,
        pipeline_factory=lambda **_: _Pipeline(failure=failure),
    )
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    with pytest.raises(AppError) as caught:
        await adapter.parse(_pdf(tmp_path), tmp_path, {})

    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("factory_failure", "expected_code"),
    [
        (ValueError("synthetic model config failure"), "MODEL_INITIALIZATION_FAILED"),
        (ConnectionError("synthetic model download failure"), "MODEL_DOWNLOAD_FAILED"),
    ],
)
async def test_model_initialization_errors_have_stable_codes(
    tmp_path: Path,
    factory_failure: Exception,
    expected_code: str,
) -> None:
    def failing_factory(**_: object) -> object:
        raise factory_failure

    settings = _settings()
    runtime = PPStructureRuntime(settings, pipeline_factory=failing_factory)
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    with pytest.raises(AppError) as caught:
        await adapter.parse(_pdf(tmp_path), tmp_path, {})

    assert caught.value.code == expected_code
    assert runtime.initialization_count == 0


async def test_result_conversion_failure_has_stable_code(tmp_path: Path) -> None:
    settings = _settings()
    runtime = PPStructureRuntime(
        settings,
        pipeline_factory=lambda **_: _Pipeline(results=[_InvalidResult()]),
    )
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    with pytest.raises(AppError) as caught:
        await adapter.parse(_pdf(tmp_path), tmp_path, {})

    assert caught.value.code == "RESULT_SERIALIZATION_FAILED"


async def test_optional_markdown_failure_preserves_json_result(tmp_path: Path) -> None:
    settings = _settings()
    runtime = PPStructureRuntime(
        settings,
        pipeline_factory=lambda **_: _Pipeline(results=[_MarkdownFailureResult()]),
    )
    adapter = PPStructureV3Adapter(_connector(), settings=settings, runtime=runtime)

    result = await adapter.parse(_pdf(tmp_path), tmp_path, {})

    assert result.raw_data["content"]["pages"][0]["raw"]["res"]["width"] == 100
    assert result.raw_data["warnings"] == ["page 1: Markdown result was unavailable (KeyError)"]


def test_json_safe_handles_non_standard_values(tmp_path: Path) -> None:
    converted = json_safe(
        {
            "array": _Array(),
            "input_img": _Array(),
            "nested": _NestedJson(),
            "enum": _Value.READY,
            "path": tmp_path,
            "nan": float("nan"),
            "bytes": "한글".encode(),
        }
    )

    assert converted == {
        "array": [[1.0, 2.0], [3.0, 4.0]],
        "input_img": {
            "omitted": True,
            "reason": "intermediate_raster_payload_not_embedded_in_json",
            "python_type": "_Array",
        },
        "nested": {"block_label": "table", "block_content": "kept"},
        "enum": "ready",
        "path": str(tmp_path),
        "nan": None,
        "bytes": "한글",
    }


def test_normalizer_preserves_string_serialized_paddle_blocks() -> None:
    raw = {
        "content": {
            "markdown": "",
            "pages": [
                {
                    "page_number": 1,
                    "markdown": "",
                    "raw": {
                        "page_index": 0,
                        "width": 100,
                        "height": 200,
                        "parsing_res_list": [
                            "#################\nindex:\t3\nlabel:\ttable\n"
                            "region_label:\ttable\nbbox:\t[1, 2, 90, 100]\n"
                            "content:\tA B\n#################"
                        ],
                        "table_res_list": [
                            {
                                "pred_html": "<table><tr><td>A</td><td>B</td></tr></table>",
                                "cell_box_list": [[1, 2, 10, 10], [11, 2, 20, 10]],
                            }
                        ],
                    },
                }
            ],
        }
    }
    canonical = normalize_paddle_response(
        raw,
        document_id="d",
        run_id="r",
        parser_name="pp_structure_v3",
        parser_version="3.7.0",
        parser_config={},
    )

    block = canonical.pages[0].blocks[0]
    assert block.type == "table"
    assert block.text == "A B"
    assert [cell.text for cell in block.cells] == ["A", "B"]
    assert block.attributes["serialized_source"] == "paddle_parsing_result_text"


def test_invalid_device_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="PADDLEOCR_DEVICE"):
        _settings(paddleocr_device="tpu")
