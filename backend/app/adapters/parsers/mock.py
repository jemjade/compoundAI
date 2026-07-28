"""개발 및 Vertical Slice 테스트에 사용하는 결정론적 내장 Parser."""

import asyncio
import re
from pathlib import Path
from typing import Any

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.schemas.canonical_document import (
    CanonicalDocument,
    DocumentBlock,
    DocumentPage,
)


class MockParserAdapter(ParserAdapter):
    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "mode": "in-process mock"}

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        del output_dir
        self._last_config = config
        await asyncio.sleep(float(config.get("delay_seconds", 0.15)))
        payload = await asyncio.to_thread(input_path.read_bytes)
        decoded = payload.decode("utf-8", errors="ignore")
        printable = "".join(
            character for character in decoded if character.isprintable() or character == "\n"
        )
        printable = re.sub(r"\n{3,}", "\n\n", printable).strip()
        if len(printable) < 20:
            printable = (
                f"Mock parser extracted a {len(payload):,}-byte document.\n"
                "Binary formats are represented by deterministic sample text in Phase 1."
            )

        mode = config.get("mode", "standard")
        if mode == "uppercase":
            text = printable.upper()
        elif mode == "line-numbered":
            text = "\n".join(
                f"{index + 1:03d} | {line}" for index, line in enumerate(printable.splitlines())
            )
        else:
            text = printable

        prefix = str(config.get("prefix", "")).strip()
        if prefix:
            text = f"{prefix}\n\n{text}"
        markdown = "\n\n".join(f"{line}" for line in text.splitlines() if line.strip())
        return ParserExecutionResult(
            raw_data={
                "adapter": "mock_parser",
                "mode": mode,
                "source_size": len(payload),
                "content": text,
            },
            text=text,
            markdown=markdown,
            metrics={"source_size": len(payload), "mode": mode},
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        text = execution_result.text or ""
        blocks = [
            DocumentBlock(
                id=f"block-{index + 1}",
                type="paragraph",
                page_number=1,
                reading_order=index,
                text=paragraph,
                confidence=1.0,
            )
            for index, paragraph in enumerate(filter(None, text.split("\n\n")))
        ]
        return CanonicalDocument(
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            full_text=text,
            markdown=execution_result.markdown,
            pages=[DocumentPage(page_number=1, text=text, blocks=blocks)],
            metadata={"mock": True},
        )
