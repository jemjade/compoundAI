"""Parser Adapter Registry 탐색과 미지원 Key 오류를 검증한다."""

from types import SimpleNamespace

import pytest

from app.adapters.parsers.docling_http import DoclingHttpAdapter
from app.adapters.parsers.mineru_http import MinerUHttpAdapter
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


def test_registry_returns_mineru_adapter() -> None:
    connector = SimpleNamespace(
        adapter_key="mineru_http",
        name="MinerU 3.x",
        model_version="3.x",
        base_url="http://mineru.internal",
        timeout_seconds=900,
        default_config={},
    )

    assert isinstance(get_parser_adapter(connector), MinerUHttpAdapter)


def test_registry_returns_docling_http_adapter() -> None:
    connector = SimpleNamespace(
        adapter_key="docling_http",
        name="Docling",
        model_version="2.x",
        base_url="http://docling.internal",
        timeout_seconds=900,
        default_config={},
    )

    assert isinstance(get_parser_adapter(connector), DoclingHttpAdapter)


def test_registry_rejects_unknown_adapter() -> None:
    connector = SimpleNamespace(adapter_key="uploaded_python")

    with pytest.raises(AppError, match="Unsupported parser adapter"):
        get_parser_adapter(connector)
