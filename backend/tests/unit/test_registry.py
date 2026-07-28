"""Parser Adapter Registry 탐색과 미지원 Key 오류를 검증한다."""

from types import SimpleNamespace

import pytest

from app.adapters.parsers.mock import MockParserAdapter
from app.adapters.parsers.paddle_structure import PPStructureV3Adapter
from app.adapters.parsers.registry import get_parser_adapter
from app.core.exceptions import AppError


def test_registry_returns_registered_adapter() -> None:
    connector = SimpleNamespace(adapter_key="mock_parser")

    assert isinstance(get_parser_adapter(connector), MockParserAdapter)


def test_registry_returns_paddle_adapter() -> None:
    connector = SimpleNamespace(
        adapter_key="pp_structure_v3",
        name="PaddleOCR",
        model_version="3.7.0",
    )

    assert isinstance(get_parser_adapter(connector), PPStructureV3Adapter)


def test_registry_rejects_unknown_adapter() -> None:
    connector = SimpleNamespace(adapter_key="uploaded_python")

    with pytest.raises(AppError, match="Unsupported parser adapter"):
        get_parser_adapter(connector)
