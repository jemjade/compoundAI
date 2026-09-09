"""Project DoclingDocument JSON into CanonicalDocument without inventing structure."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import AppError
from app.schemas.canonical_document import (
    BoundingBox,
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
    TableCell,
)

_LABELS = {
    "title": "title",
    "section_header": "heading",
    "paragraph": "paragraph",
    "text": "paragraph",
    "list_item": "list",
    "table": "table",
    "picture": "image",
    "caption": "caption",
    "formula": "formula",
    "page_header": "header",
    "page_footer": "footer",
}


def _bbox(value: Any) -> tuple[BoundingBox | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    coords = [value.get(key) for key in ("l", "t", "r", "b")]
    if not all(isinstance(item, (int, float)) for item in coords):
        return None, None
    return (
        BoundingBox(
            x1=float(coords[0]),
            y1=float(coords[1]),
            x2=float(coords[2]),
            y2=float(coords[3]),
        ),
        str(value.get("coord_origin")) if value.get("coord_origin") is not None else None,
    )


def _ref_item(document: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    value: Any = document
    for part in ref[2:].split("/"):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if 0 <= index < len(value) else None
        else:
            return None
    return value if isinstance(value, dict) else None


def _ordered_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    body = document.get("body")
    roots = body.get("children", []) if isinstance(body, dict) else []
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(pointer: Any) -> None:
        if not isinstance(pointer, dict) or not isinstance(pointer.get("$ref"), str):
            return
        ref = pointer["$ref"]
        if ref in seen:
            return
        seen.add(ref)
        item = _ref_item(document, ref)
        if item is None:
            return
        children = item.get("children")
        if ref.startswith("#/groups/") and isinstance(children, list):
            for child in children:
                visit(child)
            return
        ordered.append(item)

    for root in roots if isinstance(roots, list) else []:
        visit(root)
    if ordered:
        return ordered
    fallback = []
    for key in ("texts", "tables", "pictures", "form_items", "key_value_items"):
        rows = document.get(key)
        if isinstance(rows, list):
            fallback.extend(row for row in rows if isinstance(row, dict))
    return fallback


def _table_cells(item: dict[str, Any], table_ref: str) -> list[TableCell]:
    data = item.get("data")
    raw_cells = data.get("table_cells", []) if isinstance(data, dict) else []
    cells: list[TableCell] = []
    for index, raw in enumerate(raw_cells if isinstance(raw_cells, list) else []):
        if not isinstance(raw, dict):
            continue
        row = raw.get("start_row_offset_idx")
        column = raw.get("start_col_offset_idx")
        if not isinstance(row, int) or not isinstance(column, int):
            continue
        bbox, origin = _bbox(raw.get("bbox"))
        attributes = {
            key: raw[key]
            for key in ("column_header", "row_header", "row_section", "fillable")
            if isinstance(raw.get(key), bool)
        }
        if origin is not None:
            attributes["coordinate_origin"] = origin
        attributes["coordinate_source"] = "docling_table_cell_bbox"
        cells.append(
            TableCell(
                id=f"{table_ref}/data/table_cells/{index}",
                row=row,
                column=column,
                row_span=int(raw.get("row_span", 1)),
                column_span=int(raw.get("col_span", 1)),
                text=str(raw.get("text", "")),
                bbox=bbox,
                attributes=attributes,
            )
        )
    return cells


def _table_text(cells: list[TableCell]) -> str:
    if not cells:
        return ""
    max_row = max(cell.row + cell.row_span for cell in cells)
    max_column = max(cell.column + cell.column_span for cell in cells)
    grid = [["" for _ in range(max_column)] for _ in range(max_row)]
    for cell in cells:
        if 0 <= cell.row < max_row and 0 <= cell.column < max_column:
            grid[cell.row][cell.column] = cell.text
    return "\n".join(" | ".join(row) for row in grid)


def normalize_docling_document(
    document: Any,
    *,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
    markdown: str | None = None,
) -> CanonicalDocument:
    if not isinstance(document, dict) or document.get("schema_name") != "DoclingDocument":
        raise AppError("PARSER_NORMALIZATION_FAILED", "Docling JSON is not a DoclingDocument.")
    raw_pages = document.get("pages")
    if not isinstance(raw_pages, dict) or not raw_pages:
        raise AppError("PARSER_NORMALIZATION_FAILED", "DoclingDocument did not contain pages.")
    pages: dict[int, DocumentPage] = {}
    for key, raw_page in raw_pages.items():
        if not isinstance(raw_page, dict):
            continue
        number = raw_page.get("page_no")
        if not isinstance(number, int):
            number = int(key) if str(key).isdigit() else None
        if not isinstance(number, int) or number < 1:
            continue
        size = raw_page.get("size") if isinstance(raw_page.get("size"), dict) else {}
        pages[number] = DocumentPage(
            page_number=number,
            width=float(size["width"]) if isinstance(size.get("width"), (int, float)) else None,
            height=float(size["height"]) if isinstance(size.get("height"), (int, float)) else None,
        )
    if not pages:
        raise AppError("PARSER_NORMALIZATION_FAILED", "Docling page identifiers were invalid.")

    global_order = 0
    for item in _ordered_items(document):
        provenance = item.get("prov")
        first = provenance[0] if isinstance(provenance, list) and provenance else None
        if not isinstance(first, dict) or not isinstance(first.get("page_no"), int):
            continue
        page_number = first["page_no"]
        if page_number not in pages:
            continue
        self_ref = str(item.get("self_ref", f"#/items/{global_order}"))
        label = str(item.get("label", "unknown"))
        block_type = _LABELS.get(label, "unknown")
        bbox, origin = _bbox(first.get("bbox"))
        cells = _table_cells(item, self_ref) if block_type == "table" else []
        text = _table_text(cells) if cells else str(item.get("text", item.get("orig", "")))
        attributes: dict[str, Any] = {
            "docling_self_ref": self_ref,
            "docling_label": label,
            "content_layer": item.get("content_layer"),
            "provenance": provenance if isinstance(provenance, list) else [],
        }
        if origin is not None:
            attributes["coordinate_origin"] = origin
        block = DocumentBlock(
            id=f"p{page_number}:{self_ref.removeprefix('#/')}",
            type=block_type,
            page_number=page_number,
            reading_order=global_order,
            text=text,
            bbox=bbox,
            cells=cells,
            attributes=attributes,
        )
        pages[page_number].blocks.append(block)
        global_order += 1

    ordered_pages = [pages[number] for number in sorted(pages)]
    for page in ordered_pages:
        page.text = "\n\n".join(block.text for block in page.blocks if block.text)
    full_text = "\n\n".join(page.text for page in ordered_pages if page.text)
    return CanonicalDocument(
        schema_version="1.1",
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        full_text=full_text,
        markdown=markdown,
        pages=ordered_pages,
        metadata={
            "source": "docling",
            "docling_document_version": document.get("version"),
            "docling_schema_name": document.get("schema_name"),
            "docling_origin": document.get("origin"),
            "table_count": sum(
                block.type == "table" for page in ordered_pages for block in page.blocks
            ),
        },
    )
