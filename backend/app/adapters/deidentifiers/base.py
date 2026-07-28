"""추상 비식별화 규약과 전송 방식에 독립적인 실행 결과."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DeidentificationExecutionResult(BaseModel):
    provider: str
    deidentified_text: str
    raw_data: dict[str, Any] | list[Any] | str | None = None
    detected_entity_count: int | None = None
    masked_entity_count: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class DeidentifierAdapter(ABC):
    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def deidentify(
        self,
        input_path: Path,
        input_type: str,
        output_dir: Path,
        config: dict[str, Any],
    ) -> DeidentificationExecutionResult:
        raise NotImplementedError
