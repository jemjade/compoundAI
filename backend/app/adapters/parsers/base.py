"""추상 Parser Adapter 규약과 원본 실행 결과 모델."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.canonical_document import CanonicalDocument


class ParserExecutionResult(BaseModel):
    raw_data: dict[str, Any] | list[Any] | str | None = None
    raw_result_path: Path | None = None
    markdown: str | None = None
    text: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ParserAdapter(ABC):
    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        raise NotImplementedError
