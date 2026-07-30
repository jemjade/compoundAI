"""Parser 전처리 산출물이 파수 입력으로 선택되는지 검증한다."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.services.storage_service import StorageService
from app.task_manager.pipeline import _deidentification_input_path


@pytest.mark.parametrize(
    ("input_type", "relative_path", "content"),
    [
        ("TEXT", "runs/run-id/output.txt", "Parser text"),
        ("MARKDOWN", "runs/run-id/output.md", "# Parser markdown"),
        ("CANONICAL_JSON", "runs/run-id/canonical.json", '{"pages": []}'),
    ],
)
def test_deidentification_uses_each_parser_artifact(
    tmp_path: Path,
    input_type: str,
    relative_path: str,
    content: str,
) -> None:
    storage = StorageService(tmp_path, 1024)
    original_path = tmp_path / "documents/document-id/original.pdf"
    original_path.parent.mkdir(parents=True)
    original_path.write_bytes(b"original")
    parser_path = tmp_path / relative_path
    parser_path.parent.mkdir(parents=True)
    parser_path.write_text(content, encoding="utf-8")
    document = SimpleNamespace(storage_path="documents/document-id/original.pdf")
    result = SimpleNamespace(
        text_path="runs/run-id/output.txt",
        markdown_path="runs/run-id/output.md",
        canonical_result_path="runs/run-id/canonical.json",
    )

    selected = _deidentification_input_path(input_type, document, result, storage)

    assert selected == parser_path
    assert selected != original_path


def test_deidentification_rejects_empty_parser_artifact(tmp_path: Path) -> None:
    storage = StorageService(tmp_path, 1024)
    parser_path = tmp_path / "runs/run-id/output.txt"
    parser_path.parent.mkdir(parents=True)
    parser_path.touch()
    document = SimpleNamespace(storage_path="documents/document-id/original.pdf")
    result = SimpleNamespace(
        text_path="runs/run-id/output.txt",
        markdown_path="runs/run-id/output.md",
        canonical_result_path="runs/run-id/canonical.json",
    )

    with pytest.raises(AppError) as exc_info:
        _deidentification_input_path("TEXT", document, result, storage)

    assert exc_info.value.code == "FASOO_EXECUTION_FAILED"
    assert "parser output is empty" in exc_info.value.message
