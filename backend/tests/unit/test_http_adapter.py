"""범용 및 사이냅 HTTP Parser Adapter 동작을 검증한다."""

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import pytest

from app.adapters.parsers.generic_http import GenericHttpParserAdapter
from app.adapters.parsers.synap_http import SynapHttpAdapter
from app.core.exceptions import AppError


class FakeGenericClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeGenericClient":
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
                    "full_text": "parsed over http",
                    "markdown": "# parsed over http",
                    "pages": [],
                }
            },
            request=httpx.Request("POST", url),
        )


class FakeSynapClient:
    calls: list[tuple[str, str]] = []
    status_calls = 0

    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeSynapClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get(self, url: str, **_: object) -> httpx.Response:
        path = urlparse(url).path
        self.calls.append(("GET", path))
        return httpx.Response(
            200,
            json={
                "status": 200,
                "result": {
                    "da_engine_status": 200,
                    "msg": "DA engine is available.",
                },
            },
            request=httpx.Request("GET", url),
        )

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        path = urlparse(url).path
        self.calls.append(("POST", path))
        request = httpx.Request("POST", url)
        if path == "/da":
            data = kwargs["data"]
            assert isinstance(data, dict)
            assert data["api_key"] == "synap-secret"
            assert data["type"] == "upload"
            assert data["use_image_ocr"] == "true"
            assert "file" in kwargs["files"]
            return httpx.Response(
                200,
                json={"status": 200, "result": {"fid": "synap-fid"}},
                request=request,
            )
        if path == "/filestatus/synap-fid":
            assert kwargs["json"] == {"api_key": "synap-secret"}
            FakeSynapClient.status_calls += 1
            if FakeSynapClient.status_calls == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": 200,
                        "result": {
                            "filestatus": "LOADING",
                        },
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "result": {
                        "filestatus": "SUCCESS",
                        "returncode": 0,
                        "total_pages": 2,
                    },
                },
                request=request,
            )
        if path == "/result/synap-fid":
            body = kwargs["json"]
            assert isinstance(body, dict)
            page_number = body["page_index"]
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "result": {
                        "text": f"{page_number} 페이지",
                        "blocks": [
                            {
                                "type": "paragraph",
                                "text": f"{page_number} 페이지",
                            }
                        ],
                    },
                },
                request=request,
            )
        if path == "/delete/synap-fid":
            assert kwargs["json"] == {"api_key": "synap-secret"}
            return httpx.Response(
                200,
                json={"status": 200, "result": "successfully delete directory."},
                request=request,
            )
        raise AssertionError(f"Unexpected Synap path: {path}")


class RejectingSynapClient(FakeSynapClient):
    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        if urlparse(url).path == "/da":
            return httpx.Response(
                200,
                json={"status": 401, "result": "Check your License Code or API Key"},
                request=httpx.Request("POST", url),
            )
        return await super().post(url, **kwargs)


async def test_generic_http_adapter_calls_health_and_parse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeGenericClient)
    connector = SimpleNamespace(
        name="HTTP",
        model_version="1",
        base_url="http://parser.internal",
        timeout_seconds=5,
        default_config={},
    )
    adapter = GenericHttpParserAdapter(connector)
    source = tmp_path / "sample.txt"
    source.write_text("source", encoding="utf-8")

    health = await adapter.health_check()
    result = await adapter.parse(source, tmp_path, {})
    canonical = await adapter.normalize(result, "document", "run")

    assert health["healthy"] is True
    assert result.text == "parsed over http"
    assert canonical.full_text == "parsed over http"


async def test_synap_http_adapter_uses_structured_normalizer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    FakeSynapClient.calls = []
    FakeSynapClient.status_calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", FakeSynapClient)
    monkeypatch.setattr(
        "app.adapters.parsers.synap_http.get_settings",
        lambda: SimpleNamespace(synap_api_key="synap-secret"),
    )
    connector = SimpleNamespace(
        name="Synap",
        model_version="internal",
        base_url="http://synap.internal",
        timeout_seconds=5,
        default_config={},
    )
    adapter = SynapHttpAdapter(connector)
    source = tmp_path / "sample.txt"
    source.write_text("source", encoding="utf-8")

    health = await adapter.health_check()
    result = await adapter.parse(source, tmp_path, {"use_image_ocr": True})
    canonical = await adapter.normalize(result, "document", "run")

    assert health["healthy"] is True
    assert result.text == "1 페이지\n\n2 페이지"
    assert result.metrics["poll_count"] == 2
    assert result.metrics["page_requests"] == 2
    assert result.metrics["cleanup_succeeded"] is True
    assert canonical.full_text == "1 페이지\n\n2 페이지"
    assert [page.page_number for page in canonical.pages] == [1, 2]
    assert FakeSynapClient.calls == [
        ("GET", "/health-check"),
        ("POST", "/da"),
        ("POST", "/filestatus/synap-fid"),
        ("POST", "/filestatus/synap-fid"),
        ("POST", "/result/synap-fid"),
        ("POST", "/result/synap-fid"),
        ("POST", "/delete/synap-fid"),
    ]


async def test_synap_http_adapter_requires_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.adapters.parsers.synap_http.get_settings",
        lambda: SimpleNamespace(synap_api_key=None),
    )
    connector = SimpleNamespace(
        name="Synap",
        model_version="internal",
        base_url="http://synap.internal",
        timeout_seconds=5,
        default_config={},
    )
    source = tmp_path / "sample.txt"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(AppError) as exc_info:
        await SynapHttpAdapter(connector).parse(source, tmp_path, {})

    assert exc_info.value.code == "PARSER_CONFIGURATION_INVALID"


async def test_synap_http_adapter_maps_body_status_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", RejectingSynapClient)
    monkeypatch.setattr(
        "app.adapters.parsers.synap_http.get_settings",
        lambda: SimpleNamespace(synap_api_key="invalid"),
    )
    connector = SimpleNamespace(
        name="Synap",
        model_version="internal",
        base_url="http://synap.internal",
        timeout_seconds=5,
        default_config={},
    )
    source = tmp_path / "sample.txt"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(AppError) as exc_info:
        await SynapHttpAdapter(connector).parse(source, tmp_path, {})

    assert exc_info.value.code == "PARSER_EXECUTION_FAILED"
    assert exc_info.value.details == {"synap_status": 401}
