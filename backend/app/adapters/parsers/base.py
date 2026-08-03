"""추상 Parser Adapter 규약과 원본 실행 결과 모델."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.canonical_document import CanonicalDocument


class ParserArtifact(BaseModel):
    """Parser가 반환한 원본 파일을 저장 계층으로 전달하는 안전한 중간 표현."""

    name: str
    media_type: str = "application/octet-stream"
    content: bytes | None = Field(default=None, exclude=True)
    source_path: Path | None = Field(default=None, exclude=True)
    source: str = "parser"


class ParserExecutionResult(BaseModel):
    raw_data: dict[str, Any] | list[Any] | str | None = None
    raw_result_path: Path | None = None
    markdown: str | None = None
    text: str | None = None
    artifacts: list[ParserArtifact] = Field(default_factory=list)
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
