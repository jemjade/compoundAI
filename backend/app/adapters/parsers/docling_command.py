"""Generic Command Adapter에 Docling 전용 정규화를 더한다."""

from app.adapters.parsers.base import ParserExecutionResult
from app.adapters.parsers.generic_command import GenericCommandParserAdapter
from app.normalizers.text_normalizer import text_to_canonical
from app.schemas.canonical_document import CanonicalDocument


class DoclingCommandAdapter(GenericCommandParserAdapter):
    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        raw = execution_result.raw_data
        metadata = {"transport": "command", "format": "docling"}
        if isinstance(raw, dict):
            metadata["docling_keys"] = sorted(raw.keys())
        return text_to_canonical(
            text=execution_result.text or "",
            markdown=execution_result.markdown,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            metadata=metadata,
        )
