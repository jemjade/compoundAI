"""Mock 마스킹과 파수 HTTP 요청·응답 정규화를 검증한다."""

from pathlib import Path

import httpx
import pytest

from app.adapters.deidentifiers.fasoo_http import (
    FasooHttpDeidentifierAdapter,
    build_fasoo_request,
    parse_fasoo_response,
)
from app.adapters.deidentifiers.mock import MockDeidentifierAdapter
from app.core.config import Settings
from app.core.exceptions import AppError


class FakeFasooClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeFasooClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **_: object) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("GET", url))

    async def post(self, url: str, **_: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "deidentifiedText": "연락처 [EMAIL]",
                    "entities": [{"type": "EMAIL"}],
                    "maskedCount": 1,
                    "metrics": {"engine_ms": 12},
                }
            },
            request=httpx.Request("POST", url),
        )


async def test_mock_deidentifier_masks_supported_entities(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text(
        "메일 test@example.com 전화 010-1234-5678 주민번호 900101-1234567",
        encoding="utf-8",
    )

    result = await MockDeidentifierAdapter().deidentify(
        source,
        "TEXT",
        tmp_path,
        {},
    )

    assert result.provider == "MOCK_FASOO"
    assert result.detected_entity_count == 3
    assert "test@example.com" not in result.deidentified_text
    assert "[EMAIL]" in result.deidentified_text
    assert "[PHONE]" in result.deidentified_text
    assert "[RRN]" in result.deidentified_text
    assert all("value" not in entity for entity in result.raw_data["entities"])


async def test_fasoo_http_mapping_and_adapter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeFasooClient)
    settings = Settings(
        fasoo_enabled=True,
        fasoo_base_url="http://fasoo.internal",
        fasoo_api_key="secret",
        fasoo_timeout_seconds=5,
    )
    source = tmp_path / "input.txt"
    source.write_text("연락처 test@example.com", encoding="utf-8")
    adapter = FasooHttpDeidentifierAdapter(settings)

    health = await adapter.health_check()
    result = await adapter.deidentify(source, "TEXT", tmp_path, {"policy": "default"})

    assert health["healthy"] is True
    assert result.deidentified_text == "연락처 [EMAIL]"
    assert result.detected_entity_count == 1
    assert result.masked_entity_count == 1
    assert result.metrics["engine_ms"] == 12
    assert build_fasoo_request("text", "TEXT", {})["content"] == "text"


def test_fasoo_response_requires_deidentified_text() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_fasoo_response({"result": {"entities": []}})

    assert exc_info.value.code == "FASOO_EXECUTION_FAILED"
