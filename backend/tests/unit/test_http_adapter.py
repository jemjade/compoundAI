"""범용 및 사이냅 HTTP Parser Adapter 동작을 검증한다."""

from pathlib import Path
from types import SimpleNamespace

import httpx

from app.adapters.parsers.generic_http import GenericHttpParserAdapter
from app.adapters.parsers.synap_http import SynapHttpAdapter


class FakeAsyncClient:
    def __init__(self, **_: object) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
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


async def test_generic_http_adapter_calls_health_and_parse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
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
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
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

    result = await adapter.parse(source, tmp_path, {})
    canonical = await adapter.normalize(result, "document", "run")

    assert canonical.full_text == "parsed over http"
    assert canonical.markdown == "# parsed over http"
