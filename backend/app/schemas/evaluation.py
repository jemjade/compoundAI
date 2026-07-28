"""검증된 수동 평가 요청 및 응답 스키마."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EvaluationUpsert(BaseModel):
    text_score: int | None = Field(default=None, ge=1, le=5)
    table_score: int | None = Field(default=None, ge=1, le=5)
    reading_order_score: int | None = Field(default=None, ge=1, le=5)
    deidentification_score: int | None = Field(default=None, ge=1, le=5)
    is_preferred: bool = False
    notes: str | None = Field(default=None, max_length=4000)


class EvaluationResponse(EvaluationUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    evaluator_id: UUID
