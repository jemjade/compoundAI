"""실험 생성, Run 요약, 상세 응답 스키마."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.experiment import DeidentificationStatus, ParseStatus
from app.schemas.result import ArtifactSummary, DeidentificationSummary


class ParserRunCreate(BaseModel):
    parser_connector_id: UUID
    parser_preset_id: UUID | None = None
    config_override: dict[str, Any] = Field(default_factory=dict)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    document_id: UUID
    run_deidentification: bool = False
    parser_runs: list[ParserRunCreate] = Field(min_length=1, max_length=8)


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parser_snapshot: dict[str, Any]
    parse_status: ParseStatus
    deidentification_status: DeidentificationStatus
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    deidentification: DeidentificationSummary | None = None
    artifacts: list[ArtifactSummary] = Field(default_factory=list)


class ExperimentCreatedRun(BaseModel):
    run_id: UUID
    parser_name: str
    parse_status: ParseStatus


class ExperimentCreatedResponse(BaseModel):
    experiment_id: UUID
    runs: list[ExperimentCreatedRun]


class ExperimentListItem(BaseModel):
    id: UUID
    name: str
    description: str | None
    document_id: UUID
    document_filename: str
    created_at: datetime
    status: str
    run_count: int


class ExperimentDetail(BaseModel):
    id: UUID
    name: str
    description: str | None
    document_id: UUID
    document_filename: str
    run_deidentification: bool
    created_at: datetime
    status: str
    runs: list[RunSummary]
