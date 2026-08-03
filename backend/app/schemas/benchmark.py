"""Ground Truth 등록과 자동 벤치마크 조회 API 스키마."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroundTruthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    document_filename: str = ""
    dataset_name: str
    dataset_version: str
    schema_version: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AutomatedEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    ground_truth_id: UUID
    evaluator_version: str
    metrics: dict[str, float | None]
    sample_counts: dict[str, int]
    diagnostics: dict[str, Any]
    created_at: datetime


class MetricAggregate(BaseModel):
    value: float | None = None
    ci95_low: float | None = None
    ci95_high: float | None = None
    sample_count: int = 0


class ParserBenchmark(BaseModel):
    parser_key: str
    parser_name: str
    parser_version: str | None
    config_hash: str
    run_count: int
    document_count: int
    metrics: dict[str, MetricAggregate]
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    pages_per_minute: float | None = None


class BenchmarkRunResult(BaseModel):
    run_id: UUID
    experiment_id: UUID
    experiment_name: str
    document_id: UUID
    document_filename: str
    parser_name: str
    parser_version: str | None
    dataset_name: str
    dataset_version: str
    metrics: dict[str, float | None]
    latency_ms: int | None
    created_at: datetime


class BenchmarkSummary(BaseModel):
    evaluator_version: str
    generated_at: datetime
    ground_truth_document_count: int
    evaluated_run_count: int
    dataset_versions: list[str] = Field(default_factory=list)
    parsers: list[ParserBenchmark] = Field(default_factory=list)
    recent_results: list[BenchmarkRunResult] = Field(default_factory=list)


class RecomputeResponse(BaseModel):
    evaluated_runs: int
    skipped_runs: int
