"""Mock 마스킹과 실제 파수 NAS 경로 API 계약을 검증한다."""

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.adapters.deidentifiers.fasoo_http import (
    FasooHttpDeidentifierAdapter,
    build_fasoo_request,
    build_fasoo_rule,
    local_to_fasoo_path,
)
from app.adapters.deidentifiers.mock import MockDeidentifierAdapter
from app.core.config import Settings
from app.core.exceptions import AppError


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


async def test_fasoo_path_api_stages_nas_and_reads_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nas_root = tmp_path / "nas"
    nas_root.mkdir()
    requests: list[tuple[str, str, dict[str, Any] | None]] = []

    class FakeFasooClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "FakeFasooClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, url: str, **_: object) -> httpx.Response:
            requests.append(("GET", url, None))
            return httpx.Response(
                200,
                json={"patterns": []},
                request=httpx.Request("GET", url),
            )

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            **_: object,
        ) -> httpx.Response:
            requests.append(("POST", url, json))

            def local_path(remote_path: str) -> Path:
                return nas_root / Path(remote_path).relative_to("/dwp_comp")

            local_path(json["outputPath"]).write_text(
                '{"detectedCount": 2, "maskedCount": 2}',
                encoding="utf-8",
            )
            local_path(json["maskedPath"]).write_text(
                "연락처 [EMAIL]",
                encoding="utf-8",
            )
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeFasooClient)
    settings = Settings(
        fasoo_enabled=True,
        fasoo_base_url="https://fasoo.internal:18443",
        fasoo_timeout_seconds=5,
        fasoo_artifact_wait_seconds=0.1,
        nas_mount_path=nas_root,
        fasoo_nas_path="/dwp_comp",
        fasoo_patterns=["pattern-id"],
        fasoo_labels=["AD_ADDRESS"],
    )
    source = tmp_path / "input.txt"
    source.write_text("연락처 test@example.com", encoding="utf-8")
    output_dir = tmp_path / "run-output"
    output_dir.mkdir()
    adapter = FasooHttpDeidentifierAdapter(settings)

    health = await adapter.health_check()
    result = await adapter.deidentify(source, "ORIGINAL_FILE", output_dir, {})

    assert health["healthy"] is True
    assert result.deidentified_text == "연락처 [EMAIL]"
    assert result.detected_entity_count == 2
    assert result.masked_entity_count == 2
    assert result.masked_file_path == nas_root / "parselab/run-output/masked/masked.txt"
    assert (nas_root / "parselab/run-output/input/input.txt").read_text() == source.read_text()
    assert requests[0][1].endswith("/piiapi/configuration")
    method, url, payload = requests[1]
    assert method == "POST"
    assert url.endswith("/piiapi/detect/system/path")
    assert payload is not None
    assert payload["sync"] == "true"
    assert payload["inputPath"] == "/dwp_comp/parselab/run-output/input/input.txt"
    assert payload["outputPath"] == "/dwp_comp/parselab/run-output/masked/result.json"
    assert payload["maskedPath"] == "/dwp_comp/parselab/run-output/masked/masked.txt"
    assert payload["rule"]["patterns"] == ["pattern-id"]
    assert "callbackUrl" not in payload


def test_fasoo_request_and_rule_match_sync_contract(tmp_path: Path) -> None:
    settings = Settings(
        nas_mount_path=tmp_path,
        fasoo_patterns=["pattern-id"],
        fasoo_labels=[],
    )
    rule = build_fasoo_rule(settings, {})
    payload = build_fasoo_request(
        "/dwp_comp/input.xlsx",
        "/dwp_comp/result.json",
        "/dwp_comp/masked.xlsx",
        rule,
    )

    assert payload == {
        "sync": "true",
        "inputPath": "/dwp_comp/input.xlsx",
        "outputPath": "/dwp_comp/result.json",
        "maskedPath": "/dwp_comp/masked.xlsx",
        "rule": rule,
    }
    assert rule["masking"] is True
    assert rule["maskingChar"] == "*"
    assert rule["version"] == "1.3"


def test_fasoo_rule_requires_pattern_or_label(tmp_path: Path) -> None:
    settings = Settings(nas_mount_path=tmp_path)

    with pytest.raises(AppError) as exc_info:
        build_fasoo_rule(settings, {})

    assert exc_info.value.code == "FASOO_CONFIGURATION_INVALID"


def test_fasoo_path_mapping_rejects_file_outside_mount(tmp_path: Path) -> None:
    with pytest.raises(AppError) as exc_info:
        local_to_fasoo_path(
            tmp_path / "outside.txt",
            tmp_path / "nas",
            "/dwp_comp",
        )

    assert exc_info.value.code == "FASOO_CONFIGURATION_INVALID"


async def test_fasoo_rejects_invalid_result_json(tmp_path: Path, monkeypatch) -> None:
    nas_root = tmp_path / "nas"
    nas_root.mkdir()

    class InvalidResultClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> "InvalidResultClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            json: dict[str, Any],
            **_: object,
        ) -> httpx.Response:
            for key, value in (
                ("outputPath", "not-json"),
                ("maskedPath", "masked"),
            ):
                path = nas_root / Path(json[key]).relative_to("/dwp_comp")
                path.write_text(value, encoding="utf-8")
            return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "AsyncClient", InvalidResultClient)
    source = tmp_path / "input.txt"
    source.write_text("input", encoding="utf-8")
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    adapter = FasooHttpDeidentifierAdapter(
        Settings(
            fasoo_enabled=True,
            fasoo_base_url="http://fasoo.internal",
            nas_mount_path=nas_root,
            fasoo_patterns=["pattern-id"],
            fasoo_artifact_wait_seconds=0.1,
        )
    )

    with pytest.raises(AppError) as exc_info:
        await adapter.deidentify(source, "ORIGINAL_FILE", output_dir, {})

    assert exc_info.value.code == "FASOO_EXECUTION_FAILED"
