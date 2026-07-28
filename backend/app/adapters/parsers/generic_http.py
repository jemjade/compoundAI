"""범용 Multipart HTTP Parser 전송과 텍스트 정규화."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.core.exceptions import AppError
from app.normalizers.text_normalizer import text_to_canonical
from app.schemas.canonical_document import CanonicalDocument


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url:
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "HTTP parser requires base_url.",
        )
    if not base_url.startswith(("http://", "https://")):
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "HTTP parser base_url must use http or https.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _extract_content(payload: Any) -> tuple[str, str | None]:
    if isinstance(payload, str):
        return payload, None
    if not isinstance(payload, dict):
        return "", None
    result = payload.get("result", payload)
    if isinstance(result, str):
        return result, None
    if not isinstance(result, dict):
        return "", None
    text = result.get("full_text") or result.get("text") or result.get("content") or ""
    markdown = result.get("markdown")
    return str(text), str(markdown) if markdown is not None else None


class GenericHttpParserAdapter(ParserAdapter):
    parse_path = "/parse"
    health_path = "/health"

    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    def request_headers(self) -> dict[str, str]:
        return {}

    async def health_check(self) -> dict[str, Any]:
        path = str(self.connector.default_config.get("health_endpoint", self.health_path))
        url = _endpoint_url(self.connector.base_url, path)
        try:
            async with httpx.AsyncClient(
                timeout=min(self.connector.timeout_seconds, 10),
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers=self.request_headers())
            return {
                "healthy": response.is_success,
                "status_code": response.status_code,
                "url": url,
            }
        except httpx.TimeoutException:
            return {"healthy": False, "error": "timeout", "url": url}
        except httpx.HTTPError as exc:
            return {
                "healthy": False,
                "error": type(exc).__name__,
                "url": url,
            }

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        del output_dir
        self._last_config = config
        path = str(config.get("http_endpoint", self.parse_path))
        file_field = str(config.get("file_field", "file"))
        url = _endpoint_url(self.connector.base_url, path)
        parser_config = {
            key: value
            for key, value in config.items()
            if key not in {"http_endpoint", "health_endpoint", "file_field"}
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.connector.timeout_seconds,
                follow_redirects=False,
            ) as client:
                with input_path.open("rb") as document:
                    response = await client.post(
                        url,
                        headers=self.request_headers(),
                        files={
                            file_field: (
                                input_path.name,
                                document,
                                "application/octet-stream",
                            )
                        },
                        data={"config": json.dumps(parser_config, ensure_ascii=False)},
                    )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppError(
                "PARSER_TIMEOUT",
                f"HTTP parser exceeded {self.connector.timeout_seconds} seconds.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"HTTP parser returned status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"HTTP parser request failed: {type(exc).__name__}.",
            ) from exc

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                raw_data: dict[str, Any] | list[Any] | str = response.json()
            except ValueError as exc:
                raise AppError(
                    "PARSER_OUTPUT_NOT_FOUND",
                    "HTTP parser returned invalid JSON.",
                ) from exc
        else:
            raw_data = response.text
        text, markdown = _extract_content(raw_data)
        return ParserExecutionResult(
            raw_data=raw_data,
            text=text,
            markdown=markdown,
            metrics={
                "http_status": response.status_code,
                "response_bytes": len(response.content),
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        return text_to_canonical(
            text=execution_result.text or "",
            markdown=execution_result.markdown,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            metadata={"transport": "http"},
        )
