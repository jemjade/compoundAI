"""비교 지표, Canonical 투영, Text Diff 응답 스키마."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.evaluation import EvaluationResponse


class RunMetrics(BaseModel):
    latency_ms: int | None = None
    page_count: int | None = None
    text_length: int = 0
    block_count: int = 0
    table_count: int = 0
    image_count: int = 0
    result_size_bytes: int = 0
    page_text_lengths: list[int] = Field(default_factory=list)


class DeidentificationSummary(BaseModel):
    provider: str
    input_type: str
    detected_entity_count: int | None = None
    masked_entity_count: int | None = None
    latency_ms: int | None = None
    error_message: str | None = None


class ComparisonRun(BaseModel):
    run_id: UUID
    parser_name: str
    parser_version: str | None
    parse_status: str
    deidentification_status: str
    metrics: RunMetrics
    preview_text: str | None
    text: str | None = None
    markdown: str | None = None
    deidentified: str | None = None
    deidentification: DeidentificationSummary | None = None
    canonical: dict[str, Any] | list[Any] | None = None
    tables: list[dict[str, Any]] = Field(default_factory=list)
    evaluation: EvaluationResponse | None = None


class ComparisonResponse(BaseModel):
    experiment_id: UUID
    document: dict[str, Any]
    runs: list[ComparisonRun]


class TextDiffPart(BaseModel):
    type: str
    text: str


class TextDiffResponse(BaseModel):
    base_run_id: UUID
    target_run_id: UUID
    similarity_ratio: float
    added_count: int
    removed_count: int
    diff: list[TextDiffPart]
