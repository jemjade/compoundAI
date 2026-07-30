"""MinerU 3.x ``mineru-api`` HTTP Adapter와 Canonical 정규화."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.core.exceptions import AppError
from app.schemas.canonical_document import (
    BoundingBox,
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
)

MINERU_ADAPTER_KEY = "mineru_http"
MINERU_SUPPORTED_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".jp2",
    ".docx",
    ".pptx",
    ".xlsx",
}
MINERU_BACKENDS = {
    "pipeline",
    "vlm-engine",
    "hybrid-engine",
}
MINERU_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "backend": {"type": "string", "enum": sorted(MINERU_BACKENDS)},
        "effort": {"type": "string", "enum": ["medium", "high"]},
        "parse_method": {"type": "string", "enum": ["auto", "txt", "ocr"]},
        "lang_list": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
        "formula_enable": {"type": "boolean"},
        "table_enable": {"type": "boolean"},
        "image_analysis": {"type": "boolean"},
        "start_page_id": {"type": "integer", "minimum": 0},
        "end_page_id": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}
MINERU_DEFAULT_CONFIG: dict[str, Any] = {
    "backend": "pipeline",
    "effort": "medium",
    "parse_method": "auto",
    "lang_list": ["korean"],
    "formula_enable": True,
    "table_enable": True,
    "image_analysis": False,
    "start_page_id": 0,
    "end_page_id": 99999,
}

_MINERU_BLOCK_TYPES = {
    "title": "title",
    "heading": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list": "list",
    "table": "table",
    "image": "image",
    "figure": "image",
    "caption": "caption",
    "equation": "formula",
    "interline_equation": "formula",
    "formula": "formula",
    "header": "header",
    "footer": "footer",
}


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "MinerU requires an http(s) base_url.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _form_bool(value: bool) -> str:
    return "true" if value else "false"


def _validated_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = {**MINERU_DEFAULT_CONFIG, **config}
    unknown = set(merged) - set(MINERU_CONFIG_SCHEMA["properties"])
    if unknown:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            f"Unsupported MinerU options: {', '.join(sorted(unknown))}.",
            422,
        )
    if merged["backend"] not in MINERU_BACKENDS:
        raise AppError("PARSER_CONFIG_INVALID", "Unsupported MinerU backend.", 422)
    if merged["effort"] not in {"medium", "high"}:
        raise AppError("PARSER_CONFIG_INVALID", "Unsupported MinerU effort.", 422)
    if merged["parse_method"] not in {"auto", "txt", "ocr"}:
        raise AppError("PARSER_CONFIG_INVALID", "Unsupported MinerU parse_method.", 422)
    languages = merged["lang_list"]
    if (
        not isinstance(languages, list)
        or not languages
        or not all(isinstance(item, str) and item for item in languages)
    ):
        raise AppError("PARSER_CONFIG_INVALID", "MinerU lang_list must not be empty.", 422)
    for name in ("formula_enable", "table_enable", "image_analysis"):
        if not isinstance(merged[name], bool):
            raise AppError(
                "PARSER_CONFIG_INVALID",
                f"MinerU {name} must be boolean.",
                422,
            )
    for name in ("start_page_id", "end_page_id"):
        value = merged[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AppError(
                "PARSER_CONFIG_INVALID",
                f"MinerU {name} must be a non-negative integer.",
                422,
            )
    if merged["end_page_id"] < merged["start_page_id"]:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            "MinerU end_page_id must be greater than or equal to start_page_id.",
            422,
        )
    return merged


def _select_document_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results")
    if not isinstance(results, dict):
        return payload
    for result in results.values():
        if isinstance(result, dict):
            return result
    return {}


def _decode_content_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _item_text(item: dict[str, Any]) -> str:
    for key in ("text", "content", "table_body", "html"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("table_caption", "image_caption"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            text = "\n".join(str(part).strip() for part in value if str(part).strip())
            if text:
                return text
    return ""


def _item_bbox(item: dict[str, Any]) -> BoundingBox | None:
    value = item.get("bbox")
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(number) for number in value)
    except (TypeError, ValueError):
        return None
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def _content_list_text(items: list[dict[str, Any]]) -> str:
    return "\n\n".join(text for item in items if (text := _item_text(item)))


class MinerUHttpAdapter(ParserAdapter):
    """MinerU 3.x의 공식 ``mineru-api`` 동기 Endpoint를 호출한다."""

    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    async def health_check(self) -> dict[str, Any]:
        url = _endpoint_url(self.connector.base_url, "/health")
        try:
            async with httpx.AsyncClient(
                timeout=min(self.connector.timeout_seconds, 10),
                follow_redirects=False,
            ) as client:
                response = await client.get(url)
            payload = response.json() if "json" in response.headers.get("content-type", "") else {}
            status = payload.get("status") if isinstance(payload, dict) else None
            return {
                "healthy": response.is_success and status in {None, "healthy", "ok"},
                "status_code": response.status_code,
                "url": url,
                "version": payload.get("version") if isinstance(payload, dict) else None,
                "protocol_version": (
                    payload.get("protocol_version") if isinstance(payload, dict) else None
                ),
            }
        except (httpx.HTTPError, ValueError) as exc:
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
        if input_path.suffix.lower() not in MINERU_SUPPORTED_SUFFIXES:
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                f"MinerU does not support {input_path.suffix or 'this file type'}.",
                415,
            )
        effective = _validated_config(config)
        self._last_config = effective
        url = _endpoint_url(self.connector.base_url, "/file_parse")
        form_data: dict[str, str | list[str]] = {
            "backend": str(effective["backend"]),
            "effort": str(effective["effort"]),
            "parse_method": str(effective["parse_method"]),
            "formula_enable": _form_bool(effective["formula_enable"]),
            "table_enable": _form_bool(effective["table_enable"]),
            "image_analysis": _form_bool(effective["image_analysis"]),
            "return_md": "true",
            "return_middle_json": "false",
            "return_model_output": "false",
            "return_content_list": "true",
            "return_images": "false",
            "response_format_zip": "false",
            "return_original_file": "false",
            "start_page_id": str(effective["start_page_id"]),
            "end_page_id": str(effective["end_page_id"]),
            "lang_list": effective["lang_list"],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.connector.timeout_seconds,
                follow_redirects=False,
            ) as client:
                with input_path.open("rb") as document:
                    response = await client.post(
                        url,
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
                f"MinerU exceeded {self.connector.timeout_seconds} seconds.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"MinerU returned status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"MinerU request failed: {type(exc).__name__}.",
            ) from exc

        try:
            raw_data = response.json()
        except ValueError as exc:
            raise AppError("PARSER_OUTPUT_NOT_FOUND", "MinerU returned invalid JSON.") from exc
        result = _select_document_result(raw_data)
        markdown = result.get("md_content")
        markdown = markdown if isinstance(markdown, str) else ""
        content_list = _decode_content_list(result.get("content_list"))
        text = _content_list_text(content_list) or markdown
        if not text.strip():
            raise AppError(
                "PARSER_OUTPUT_NOT_FOUND",
                "MinerU returned neither Markdown nor content-list text.",
            )
        return ParserExecutionResult(
            raw_data=raw_data,
            markdown=markdown or None,
            text=text,
            metrics={
                "http_status": response.status_code,
                "response_bytes": len(response.content),
                "content_block_count": len(content_list),
                "backend": effective["backend"],
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        result = _select_document_result(execution_result.raw_data)
        items = _decode_content_list(result.get("content_list"))
        pages: dict[int, list[DocumentBlock]] = {}
        for index, item in enumerate(items):
            raw_page = item.get("page_idx", item.get("page_index", 0))
            page_number = raw_page + 1 if isinstance(raw_page, int) else 1
            raw_type = str(item.get("type", "unknown")).lower()
            block = DocumentBlock(
                id=f"mineru-block-{index + 1}",
                type=_MINERU_BLOCK_TYPES.get(raw_type, "unknown"),
                page_number=page_number,
                reading_order=index,
                text=_item_text(item),
                bbox=_item_bbox(item),
                html=item.get("table_body") if raw_type == "table" else None,
                attributes={
                    key: value
                    for key, value in item.items()
                    if key
                    not in {
                        "text",
                        "content",
                        "html",
                        "table_body",
                        "bbox",
                    }
                },
            )
            pages.setdefault(page_number, []).append(block)
        canonical_pages = [
            DocumentPage(
                page_number=page_number,
                text="\n\n".join(block.text for block in blocks if block.text),
                blocks=blocks,
            )
            for page_number, blocks in sorted(pages.items())
        ]
        return CanonicalDocument(
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            full_text=execution_result.text or "",
            markdown=execution_result.markdown,
            pages=canonical_pages,
            metadata={
                "transport": "http",
                "format": "mineru-content-list",
                "content_block_count": len(items),
            },
        )
