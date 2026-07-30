"""Docling Serve v1 REST API Adapter."""

from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.normalizers.text_normalizer import text_to_canonical
from app.schemas.canonical_document import CanonicalDocument

DOCLING_HTTP_ADAPTER_KEY = "docling_http"
DOCLING_HTTP_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "do_ocr": {"type": "boolean"},
        "force_ocr": {"type": "boolean"},
        "ocr_lang": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "table_mode": {"type": "string", "enum": ["fast", "accurate"]},
        "image_export_mode": {
            "type": "string",
            "enum": ["placeholder", "embedded", "referenced"],
        },
    },
    "additionalProperties": False,
}
DOCLING_HTTP_DEFAULT_CONFIG: dict[str, Any] = {
    "do_ocr": True,
    "force_ocr": False,
    "ocr_lang": ["ko", "en"],
    "table_mode": "accurate",
    "image_export_mode": "placeholder",
}
DOCLING_SUPPORTED_FORMATS = [
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "html",
    "md",
    "txt",
    "png",
    "jpg",
    "jpeg",
    "tiff",
]
_DOCLING_FROM_FORMAT = {
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "tif": "image",
    "tiff": "image",
}


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "Docling Serve requires an http(s) base_url.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _form_bool(value: bool) -> str:
    return "true" if value else "false"


def _validated_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = {**DOCLING_HTTP_DEFAULT_CONFIG, **config}
    unknown = set(merged) - set(DOCLING_HTTP_CONFIG_SCHEMA["properties"])
    if unknown:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            f"Unsupported Docling options: {', '.join(sorted(unknown))}.",
            422,
        )
    for name in ("do_ocr", "force_ocr"):
        if not isinstance(merged[name], bool):
            raise AppError("PARSER_CONFIG_INVALID", f"Docling {name} must be boolean.", 422)
    if merged["table_mode"] not in {"fast", "accurate"}:
        raise AppError("PARSER_CONFIG_INVALID", "Unsupported Docling table_mode.", 422)
    if merged["image_export_mode"] not in {"placeholder", "embedded", "referenced"}:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            "Unsupported Docling image_export_mode.",
            422,
        )
    languages = merged["ocr_lang"]
    if (
        not isinstance(languages, list)
        or not all(isinstance(item, str) and item for item in languages)
    ):
        raise AppError("PARSER_CONFIG_INVALID", "Docling ocr_lang must be a string list.", 422)
    return merged


class DoclingHttpAdapter(ParserAdapter):
    """공식 Docling Serve의 동기 Multipart 변환 Endpoint를 호출한다."""

    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    def request_headers(self) -> dict[str, str]:
        api_key = get_settings().docling_api_key
        return {"X-Api-Key": api_key} if api_key else {}

    async def health_check(self) -> dict[str, Any]:
        url = _endpoint_url(self.connector.base_url, "/health")
        try:
            async with httpx.AsyncClient(
                timeout=min(self.connector.timeout_seconds, 10),
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers=self.request_headers())
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            return {
                "healthy": response.is_success,
                "status_code": response.status_code,
                "url": url,
                "status": payload.get("status") if isinstance(payload, dict) else None,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {"healthy": False, "error": type(exc).__name__, "url": url}

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        del output_dir
        suffix = input_path.suffix.lower().lstrip(".")
        if suffix not in DOCLING_SUPPORTED_FORMATS:
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                f"Docling does not support {input_path.suffix or 'this file type'}.",
                415,
            )
        effective = _validated_config(config)
        self._last_config = effective
        url = _endpoint_url(self.connector.base_url, "/v1/convert/file")
        form_data: dict[str, str | list[str]] = {
            "from_formats": _DOCLING_FROM_FORMAT.get(suffix, suffix),
            "to_formats": ["md", "json", "text"],
            "do_ocr": _form_bool(effective["do_ocr"]),
            "force_ocr": _form_bool(effective["force_ocr"]),
            "table_mode": str(effective["table_mode"]),
            "image_export_mode": str(effective["image_export_mode"]),
            "ocr_lang": effective["ocr_lang"],
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
                            "files": (
                                input_path.name,
                                document,
                                "application/octet-stream",
                            )
                        },
                        data=form_data,
                    )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppError(
                "PARSER_TIMEOUT",
                f"Docling exceeded {self.connector.timeout_seconds} seconds.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Docling returned status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Docling request failed: {type(exc).__name__}.",
            ) from exc

        try:
            raw_data = response.json()
        except ValueError as exc:
            raise AppError("PARSER_OUTPUT_NOT_FOUND", "Docling returned invalid JSON.") from exc
        if not isinstance(raw_data, dict):
            raise AppError("PARSER_OUTPUT_NOT_FOUND", "Docling returned an invalid result.")
        if raw_data.get("status") not in {None, "success", "partial_success"}:
            raise AppError("PARSER_EXECUTION_FAILED", "Docling conversion failed.")
        document_result = raw_data.get("document")
        if not isinstance(document_result, dict):
            raise AppError("PARSER_OUTPUT_NOT_FOUND", "Docling result has no document.")
        markdown = document_result.get("md_content")
        text = document_result.get("text_content")
        markdown = markdown if isinstance(markdown, str) else ""
        text = text if isinstance(text, str) else markdown
        if not text.strip():
            raise AppError(
                "PARSER_OUTPUT_NOT_FOUND",
                "Docling returned neither text nor Markdown.",
            )
        return ParserExecutionResult(
            raw_data=raw_data,
            text=text,
            markdown=markdown or None,
            metrics={
                "http_status": response.status_code,
                "response_bytes": len(response.content),
                "processing_time_seconds": raw_data.get("processing_time"),
                "status": raw_data.get("status"),
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        raw_data = execution_result.raw_data
        document_result = raw_data.get("document", {}) if isinstance(raw_data, dict) else {}
        json_content = (
            document_result.get("json_content") if isinstance(document_result, dict) else None
        )
        return text_to_canonical(
            text=execution_result.text or "",
            markdown=execution_result.markdown,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            metadata={
                "transport": "http",
                "format": "docling-document",
                "docling_json_available": isinstance(json_content, dict),
            },
        )
