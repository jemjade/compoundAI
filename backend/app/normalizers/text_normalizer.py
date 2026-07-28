"""일반 텍스트 또는 Markdown을 최소 Canonical Document로 변환한다."""

import re
from typing import Any

from app.schemas.canonical_document import (
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
)


def text_to_canonical(
    *,
    text: str,
    markdown: str | None,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> CanonicalDocument:
    paragraphs = [
        paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()
    ]
    blocks = [
        DocumentBlock(
            id=f"block-{index + 1}",
            type="paragraph",
            page_number=1,
            reading_order=index,
            text=paragraph,
        )
        for index, paragraph in enumerate(paragraphs)
    ]
    return CanonicalDocument(
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        full_text=text,
        markdown=markdown,
        pages=[DocumentPage(page_number=1, text=text, blocks=blocks)] if text else [],
        metadata=metadata or {},
    )
