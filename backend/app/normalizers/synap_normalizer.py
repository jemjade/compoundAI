"""유연한 사이냅 페이지·블록·Bounding Box·표 Payload를 매핑한다."""

from typing import Any

from app.core.exceptions import AppError
from app.schemas.canonical_document import (
    BoundingBox,
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
    TableCell,
)

BLOCK_TYPES = {
    "title",
    "heading",
    "paragraph",
    "list",
    "table",
    "image",
    "caption",
    "formula",
    "header",
    "footer",
}


def _bbox(value: Any) -> BoundingBox | None:
    if isinstance(value, list) and len(value) == 4:
        return BoundingBox(x1=value[0], y1=value[1], x2=value[2], y2=value[3])
    if isinstance(value, dict) and {"x1", "y1", "x2", "y2"} <= value.keys():
        return BoundingBox.model_validate(value)
    return None


def _cells(value: Any) -> list[TableCell]:
    if not isinstance(value, list):
        return []
    cells: list[TableCell] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        cells.append(
            TableCell(
                row=int(item.get("row", item.get("row_index", 0))),
                column=int(item.get("column", item.get("column_index", 0))),
                row_span=int(item.get("row_span", 1)),
                column_span=int(item.get("column_span", item.get("col_span", 1))),
                text=str(item.get("text", "")),
            )
        )
    return cells


def normalize_synap_response(
    raw_data: dict[str, Any],
    *,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
    fallback_text: str = "",
    fallback_markdown: str | None = None,
) -> CanonicalDocument:
    payload = raw_data.get("result", raw_data)
    if not isinstance(payload, dict):
        raise AppError(
            "PARSER_NORMALIZATION_FAILED",
            "Synap response result must be a JSON object.",
        )
    full_text = str(
        payload.get("full_text") or payload.get("text") or payload.get("content") or fallback_text
    )
    markdown_value = payload.get("markdown", fallback_markdown)
    markdown = str(markdown_value) if markdown_value is not None else None
    pages_data = payload.get("pages")
    if not isinstance(pages_data, list):
        pages_data = [{"page_number": 1, "text": full_text, "blocks": payload.get("blocks", [])}]

    pages: list[DocumentPage] = []
    reading_order = 0
    for page_index, page_data in enumerate(pages_data):
        if not isinstance(page_data, dict):
            continue
        page_number = int(page_data.get("page_number", page_data.get("page", page_index + 1)))
        blocks_data = page_data.get("blocks", page_data.get("elements", []))
        blocks: list[DocumentBlock] = []
        if isinstance(blocks_data, list):
            for block_index, block_data in enumerate(blocks_data):
                if not isinstance(block_data, dict):
                    continue
                raw_type = str(block_data.get("type", "unknown")).lower()
                block_type = raw_type if raw_type in BLOCK_TYPES else "unknown"
                blocks.append(
                    DocumentBlock(
                        id=str(block_data.get("id", f"p{page_number}-b{block_index + 1}")),
                        type=block_type,
                        page_number=page_number,
                        reading_order=int(block_data.get("reading_order", reading_order)),
                        text=str(block_data.get("text", block_data.get("content", ""))),
                        bbox=_bbox(block_data.get("bbox", block_data.get("bounding_box"))),
                        confidence=block_data.get("confidence"),
                        html=block_data.get("html"),
                        cells=_cells(block_data.get("cells")),
                        attributes={
                            key: value
                            for key, value in block_data.items()
                            if key
                            not in {
                                "id",
                                "type",
                                "page_number",
                                "reading_order",
                                "text",
                                "content",
                                "bbox",
                                "bounding_box",
                                "confidence",
                                "html",
                                "cells",
                            }
                        },
                    )
                )
                reading_order += 1
        page_text = str(page_data.get("text", ""))
        if not page_text:
            page_text = "\n".join(block.text for block in blocks if block.text)
        pages.append(
            DocumentPage(
                page_number=page_number,
                width=page_data.get("width"),
                height=page_data.get("height"),
                text=page_text,
                blocks=blocks,
            )
        )
    if not full_text:
        full_text = "\n\n".join(page.text for page in pages if page.text)
    return CanonicalDocument(
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        full_text=full_text,
        markdown=markdown,
        pages=pages,
        metadata=payload.get("metadata", {}),
    )
