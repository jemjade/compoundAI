"""PP-StructureV3 raw 페이지를 공통 Canonical Document로 투영한다."""

from typing import Any

from app.core.exceptions import AppError
from app.schemas.canonical_document import (
    BoundingBox,
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
)

_BLOCK_TYPES = {
    "doc_title": "title",
    "title": "title",
    "paragraph_title": "heading",
    "heading": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list": "list",
    "table": "table",
    "image": "image",
    "figure": "image",
    "figure_title": "caption",
    "table_title": "caption",
    "chart_title": "caption",
    "caption": "caption",
    "formula": "formula",
    "header": "header",
    "footer": "footer",
}


def _payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    value = raw.get("res", raw)
    return value if isinstance(value, dict) else {}


def _bbox(value: Any) -> BoundingBox | None:
    if (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    ):
        return BoundingBox(x1=value[0], y1=value[1], x2=value[2], y2=value[3])
    return None


def _table_htmls(payload: dict[str, Any]) -> list[str]:
    tables = payload.get("table_res_list")
    if not isinstance(tables, list):
        return []
    values: list[str] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        html = table.get("pred_html")
        if isinstance(html, str):
            values.append(html)
    return values


def normalize_paddle_response(
    raw_data: Any,
    *,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
) -> CanonicalDocument:
    if not isinstance(raw_data, dict):
        raise AppError(
            "PARSER_NORMALIZATION_FAILED",
            "PaddleOCR result must be a JSON object.",
        )
    content = raw_data.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("pages"), list):
        raise AppError(
            "PARSER_NORMALIZATION_FAILED",
            "PaddleOCR result did not contain pages.",
        )

    pages: list[DocumentPage] = []
    global_order = 0
    for index, page_result in enumerate(content["pages"]):
        if not isinstance(page_result, dict):
            continue
        payload = _payload(page_result.get("raw"))
        raw_page_index = payload.get("page_index")
        page_number = (
            int(raw_page_index) + 1
            if isinstance(raw_page_index, int)
            else int(page_result.get("page_number", index + 1))
        )
        table_htmls = iter(_table_htmls(payload))
        raw_blocks = payload.get("parsing_res_list")
        blocks: list[DocumentBlock] = []
        if isinstance(raw_blocks, list):
            for block_index, raw_block in enumerate(raw_blocks):
                if not isinstance(raw_block, dict):
                    continue
                label = str(raw_block.get("block_label", "unknown")).lower()
                block_type = _BLOCK_TYPES.get(label, "unknown")
                order = raw_block.get("block_order")
                if not isinstance(order, int):
                    order = global_order
                block = DocumentBlock(
                    id=str(
                        raw_block.get(
                            "block_id",
                            f"p{page_number}-b{block_index + 1}",
                        )
                    ),
                    type=block_type,
                    page_number=page_number,
                    reading_order=order,
                    text=str(raw_block.get("block_content", "")),
                    bbox=_bbox(raw_block.get("block_bbox")),
                    confidence=(
                        float(raw_block["score"])
                        if isinstance(raw_block.get("score"), (int, float))
                        else None
                    ),
                    html=next(table_htmls, None) if block_type == "table" else None,
                    attributes={
                        "paddle_label": label,
                        **(
                            {"paddle_order": raw_block["block_order"]}
                            if raw_block.get("block_order") is not None
                            else {}
                        ),
                    },
                )
                blocks.append(block)
                global_order += 1

        page_text = "\n\n".join(block.text for block in blocks if block.text)
        if not page_text:
            page_text = str(page_result.get("markdown", ""))
        pages.append(
            DocumentPage(
                page_number=page_number,
                width=(
                    float(payload["width"])
                    if isinstance(payload.get("width"), (int, float))
                    else None
                ),
                height=(
                    float(payload["height"])
                    if isinstance(payload.get("height"), (int, float))
                    else None
                ),
                text=page_text,
                blocks=blocks,
            )
        )

    full_text = "\n\n".join(page.text for page in pages if page.text)
    markdown = content.get("markdown")
    parser_metadata = raw_data.get("parser")
    warnings = raw_data.get("warnings")
    return CanonicalDocument(
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        full_text=full_text,
        markdown=str(markdown) if markdown is not None else None,
        pages=pages,
        metadata={
            "source": "paddleocr",
            "parser": parser_metadata if isinstance(parser_metadata, dict) else {},
            "warnings": warnings if isinstance(warnings, list) else [],
        },
    )
