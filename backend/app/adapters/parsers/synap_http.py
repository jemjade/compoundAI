"""사이냅 인증과 구조화 응답 정규화."""

from pathlib import Path
from typing import Any

from app.adapters.parsers.base import ParserExecutionResult
from app.adapters.parsers.generic_http import GenericHttpParserAdapter
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.normalizers.synap_normalizer import normalize_synap_response
from app.schemas.canonical_document import CanonicalDocument


def build_synap_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def parse_synap_response(
    execution_result: ParserExecutionResult,
    *,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
) -> CanonicalDocument:
    if not isinstance(execution_result.raw_data, dict):
        raise AppError(
            "PARSER_NORMALIZATION_FAILED",
            "Synap parser response must be a JSON object.",
        )
    return normalize_synap_response(
        execution_result.raw_data,
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        fallback_text=execution_result.text or "",
        fallback_markdown=execution_result.markdown,
    )


class SynapHttpAdapter(GenericHttpParserAdapter):
    parse_path = "/parse"
    health_path = "/health"

    def request_headers(self) -> dict[str, str]:
        return build_synap_headers(get_settings().synap_api_key)

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        return await super().parse(input_path, output_dir, config)

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        return parse_synap_response(
            execution_result,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
        )
