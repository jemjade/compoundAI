"""Parser와 독립적인 문서·페이지·블록·Bounding Box·표 스키마."""

from typing import Any, Literal

from pydantic import BaseModel, Field

BlockType = Literal[
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
    "unknown",
]


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class TableCell(BaseModel):
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1
    text: str = ""


class DocumentBlock(BaseModel):
    id: str
    type: BlockType
    page_number: int
    reading_order: int | None = None
    text: str = ""
    bbox: BoundingBox | None = None
    confidence: float | None = None
    html: str | None = None
    cells: list[TableCell] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class DocumentPage(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    text: str = ""
    blocks: list[DocumentBlock] = Field(default_factory=list)


class CanonicalDocument(BaseModel):
    schema_version: str = "1.0"
    document_id: str
    run_id: str
    parser_name: str
    parser_version: str | None = None
    parser_config: dict[str, Any] = Field(default_factory=dict)
    full_text: str = ""
    markdown: str | None = None
    pages: list[DocumentPage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
