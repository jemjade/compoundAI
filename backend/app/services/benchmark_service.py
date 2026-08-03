"""Ground Truth 관리, Run 정량 평가, 통계 집계를 제공한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, stdev
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.models.benchmark import AutomatedEvaluation, GroundTruth
from app.db.models.document import Document
from app.db.models.experiment import Experiment, ExperimentRun, ParseStatus
from app.db.models.result import DeidentificationResult, RunResult
from app.schemas.benchmark import (
    AutomatedEvaluationResponse,
    BenchmarkRunResult,
    BenchmarkSummary,
    GroundTruthResponse,
    MetricAggregate,
    ParserBenchmark,
    RecomputeResponse,
)
from app.services.benchmark_metrics import EVALUATOR_VERSION, evaluate_documents
from app.services.storage_service import StorageService

T_CRITICAL_95 = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def _config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _aggregate(values: list[float], *, bounded: bool = True) -> MetricAggregate:
    if not values:
        return MetricAggregate()
    average = mean(values)
    if len(values) < 2:
        return MetricAggregate(value=average, sample_count=1)
    degrees_of_freedom = len(values) - 1
    critical = T_CRITICAL_95.get(degrees_of_freedom, 1.96)
    margin = critical * stdev(values) / math.sqrt(len(values))
    lower = average - margin
    upper = average + margin
    if bounded:
        lower = max(0.0, lower)
        upper = min(1.0, upper)
    else:
        lower = max(0.0, lower)
    return MetricAggregate(
        value=average,
        ci95_low=lower,
        ci95_high=upper,
        sample_count=len(values),
    )


def validate_ground_truth(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AppError("INVALID_GROUND_TRUTH", "Ground Truth must be a JSON object.", 422)
    if not isinstance(payload.get("full_text"), str):
        raise AppError(
            "INVALID_GROUND_TRUTH",
            "Ground Truth requires a full_text string.",
            422,
        )
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise AppError(
            "INVALID_GROUND_TRUTH",
            "Ground Truth requires a pages array.",
            422,
        )
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or not isinstance(page.get("blocks", []), list):
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "Each Ground Truth page must be an object with a blocks array.",
                422,
            )
        try:
            page_number = int(page.get("page_number", page_index))
        except (TypeError, ValueError) as exc:
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "Each Ground Truth page_number must be an integer.",
                422,
            ) from exc
        if page_number < 1:
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "Each Ground Truth page_number must be positive.",
                422,
            )
        for block in page.get("blocks", []):
            if not isinstance(block, dict):
                raise AppError(
                    "INVALID_GROUND_TRUTH",
                    "Each Ground Truth block must be an object.",
                    422,
                )
            if not isinstance(block.get("type", "unknown"), str) or not isinstance(
                block.get("text", ""),
                str,
            ):
                raise AppError(
                    "INVALID_GROUND_TRUTH",
                    "Ground Truth block type and text must be strings.",
                    422,
                )
            reading_order = block.get("reading_order")
            if reading_order is not None and (
                not isinstance(reading_order, int) or isinstance(reading_order, bool)
            ):
                raise AppError(
                    "INVALID_GROUND_TRUTH",
                    "Ground Truth block reading_order must be an integer.",
                    422,
                )
            cells = block.get("cells", [])
            if not isinstance(cells, list):
                raise AppError(
                    "INVALID_GROUND_TRUTH",
                    "Ground Truth block cells must be an array.",
                    422,
                )
            for cell in cells:
                if not isinstance(cell, dict):
                    raise AppError(
                        "INVALID_GROUND_TRUTH",
                        "Each Ground Truth table cell must be an object.",
                        422,
                    )
                try:
                    int(cell.get("row", cell.get("row_index", 0)))
                    int(cell.get("column", cell.get("column_index", 0)))
                    int(cell.get("row_span", 1))
                    int(cell.get("column_span", cell.get("col_span", 1)))
                except (TypeError, ValueError) as exc:
                    raise AppError(
                        "INVALID_GROUND_TRUTH",
                        "Ground Truth table cell coordinates and spans must be integers.",
                        422,
                    ) from exc
    entities = payload.get("pii_entities", [])
    if not isinstance(entities, list):
        raise AppError(
            "INVALID_GROUND_TRUTH",
            "pii_entities must be an array when provided.",
            422,
        )
    for entity in entities:
        if not isinstance(entity, dict) or not isinstance(
            entity.get("type", entity.get("label")),
            str,
        ):
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "Each PII entity requires a string type and integer start/end offsets.",
                422,
            )
        try:
            start = int(entity["start"])
            end = int(entity["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "Each PII entity requires a string type and integer start/end offsets.",
                422,
            ) from exc
        if start < 0 or end <= start:
            raise AppError(
                "INVALID_GROUND_TRUTH",
                "PII entity offsets must satisfy 0 <= start < end.",
                422,
            )
    return payload


class BenchmarkService:
    def __init__(self, session: AsyncSession, storage: StorageService) -> None:
        self.session = session
        self.storage = storage

    async def _owned_document(self, document_id: UUID, user_id: UUID) -> Document:
        document = await self.session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.uploaded_by == user_id,
            )
        )
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        return document

    async def upsert_ground_truth(
        self,
        document_id: UUID,
        user_id: UUID,
        payload: dict[str, Any],
        *,
        dataset_name: str,
        dataset_version: str,
        schema_version: str,
        notes: str | None,
    ) -> GroundTruthResponse:
        document = await self._owned_document(document_id, user_id)
        validate_ground_truth(payload)
        content_path = await self.storage.save_ground_truth(document_id, payload)
        ground_truth = await self.session.scalar(
            select(GroundTruth).where(GroundTruth.document_id == document_id)
        )
        if ground_truth is None:
            ground_truth = GroundTruth(
                document_id=document_id,
                created_by=user_id,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                schema_version=schema_version,
                content_path=content_path,
                notes=notes,
            )
            self.session.add(ground_truth)
        else:
            ground_truth.dataset_name = dataset_name
            ground_truth.dataset_version = dataset_version
            ground_truth.schema_version = schema_version
            ground_truth.content_path = content_path
            ground_truth.notes = notes
        await self.session.flush()
        await self.recompute_document(document_id, user_id)
        await self.session.commit()
        return GroundTruthResponse(
            **GroundTruthResponse.model_validate(ground_truth).model_dump(
                exclude={"document_filename"}
            ),
            document_filename=document.original_filename,
        )

    async def list_ground_truths(self, user_id: UUID) -> list[GroundTruthResponse]:
        rows = (
            await self.session.execute(
                select(GroundTruth, Document)
                .join(Document, Document.id == GroundTruth.document_id)
                .where(Document.uploaded_by == user_id)
                .order_by(GroundTruth.updated_at.desc())
            )
        ).all()
        return [
            GroundTruthResponse(
                **GroundTruthResponse.model_validate(ground_truth).model_dump(
                    exclude={"document_filename"}
                ),
                document_filename=document.original_filename,
            )
            for ground_truth, document in rows
        ]

    async def evaluate_run(self, run_id: UUID) -> AutomatedEvaluation | None:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None or run.parse_status != ParseStatus.SUCCEEDED:
            return None
        ground_truth = await self.session.scalar(
            select(GroundTruth).where(GroundTruth.document_id == run.document_id)
        )
        result = await self.session.scalar(select(RunResult).where(RunResult.run_id == run.id))
        if ground_truth is None or result is None:
            return None
        gt_payload = await self.storage.read_text(ground_truth.content_path)
        prediction_payload = await self.storage.read_text(result.canonical_result_path)
        if not gt_payload or not prediction_payload:
            return None
        try:
            loaded_ground_truth = json.loads(gt_payload)
            loaded_prediction = json.loads(prediction_payload)
        except json.JSONDecodeError as exc:
            raise AppError(
                "BENCHMARK_INPUT_INVALID",
                "Ground Truth or Canonical result is not valid JSON.",
            ) from exc
        if not isinstance(loaded_ground_truth, dict) or not isinstance(loaded_prediction, dict):
            raise AppError(
                "BENCHMARK_INPUT_INVALID",
                "Benchmark inputs must be JSON objects.",
            )
        deidentification = await self.session.scalar(
            select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
        )
        deidentification_payload: dict[str, Any] | None = None
        if deidentification and deidentification.result_path:
            stored = await self.storage.read_text(deidentification.result_path)
            if stored:
                try:
                    loaded = json.loads(stored)
                except json.JSONDecodeError:
                    loaded = None
                if isinstance(loaded, dict):
                    deidentification_payload = loaded
        metrics, counts, diagnostics = await asyncio.to_thread(
            evaluate_documents,
            loaded_ground_truth,
            loaded_prediction,
            deidentification_payload,
        )
        evaluation = await self.session.scalar(
            select(AutomatedEvaluation).where(AutomatedEvaluation.run_id == run.id)
        )
        if evaluation is None:
            evaluation = AutomatedEvaluation(
                run_id=run.id,
                ground_truth_id=ground_truth.id,
                evaluator_version=EVALUATOR_VERSION,
            )
            self.session.add(evaluation)
        evaluation.ground_truth_id = ground_truth.id
        evaluation.evaluator_version = EVALUATOR_VERSION
        evaluation.metrics = metrics
        evaluation.sample_counts = counts
        evaluation.diagnostics = diagnostics
        evaluation.created_at = datetime.now(UTC)
        await self.session.flush()
        return evaluation

    async def recompute_document(self, document_id: UUID, user_id: UUID) -> RecomputeResponse:
        await self._owned_document(document_id, user_id)
        runs = list(
            await self.session.scalars(
                select(ExperimentRun).where(
                    ExperimentRun.document_id == document_id,
                    ExperimentRun.parse_status == ParseStatus.SUCCEEDED,
                )
            )
        )
        evaluated = 0
        skipped = 0
        for run in runs:
            if await self.evaluate_run(run.id):
                evaluated += 1
            else:
                skipped += 1
        return RecomputeResponse(evaluated_runs=evaluated, skipped_runs=skipped)

    async def recompute_all(self, user_id: UUID) -> RecomputeResponse:
        runs = list(
            await self.session.scalars(
                select(ExperimentRun)
                .join(Experiment, Experiment.id == ExperimentRun.experiment_id)
                .where(
                    Experiment.created_by == user_id,
                    ExperimentRun.parse_status == ParseStatus.SUCCEEDED,
                )
            )
        )
        evaluated = 0
        skipped = 0
        for run in runs:
            if await self.evaluate_run(run.id):
                evaluated += 1
            else:
                skipped += 1
        await self.session.commit()
        return RecomputeResponse(evaluated_runs=evaluated, skipped_runs=skipped)

    async def get_run_evaluation(
        self,
        run_id: UUID,
        user_id: UUID,
    ) -> AutomatedEvaluationResponse | None:
        row = await self.session.scalar(
            select(AutomatedEvaluation)
            .join(ExperimentRun, ExperimentRun.id == AutomatedEvaluation.run_id)
            .join(Experiment, Experiment.id == ExperimentRun.experiment_id)
            .where(
                AutomatedEvaluation.run_id == run_id,
                Experiment.created_by == user_id,
            )
        )
        return AutomatedEvaluationResponse.model_validate(row) if row else None

    async def summary(self, user_id: UUID) -> BenchmarkSummary:
        rows = (
            await self.session.execute(
                select(
                    AutomatedEvaluation,
                    ExperimentRun,
                    Experiment,
                    Document,
                    GroundTruth,
                    RunResult,
                )
                .join(ExperimentRun, ExperimentRun.id == AutomatedEvaluation.run_id)
                .join(Experiment, Experiment.id == ExperimentRun.experiment_id)
                .join(Document, Document.id == ExperimentRun.document_id)
                .join(GroundTruth, GroundTruth.id == AutomatedEvaluation.ground_truth_id)
                .join(RunResult, RunResult.run_id == ExperimentRun.id)
                .where(Experiment.created_by == user_id)
                .order_by(AutomatedEvaluation.created_at.desc())
            )
        ).all()
        ground_truth_count = len(await self.list_ground_truths(user_id))
        grouped: dict[
            tuple[str, str | None, str],
            list[
                tuple[
                    AutomatedEvaluation,
                    ExperimentRun,
                    Experiment,
                    Document,
                    GroundTruth,
                    RunResult,
                ]
            ],
        ] = defaultdict(list)
        for row in rows:
            evaluation, run, *_ = row
            parser_name = str(run.parser_snapshot.get("name", "Unknown"))
            parser_version = run.parser_snapshot.get("model_version")
            grouped[(parser_name, parser_version, _config_hash(run.config_snapshot))].append(row)

        parser_benchmarks: list[ParserBenchmark] = []
        for (parser_name, parser_version, config_hash), group in grouped.items():
            metric_values: dict[str, list[float]] = defaultdict(list)
            latencies: list[float] = []
            page_count = 0
            total_latency_ms = 0.0
            document_ids: set[UUID] = set()
            for evaluation, run, _, document, _, result in group:
                document_ids.add(document.id)
                for key, value in evaluation.metrics.items():
                    if isinstance(value, (int, float)) and math.isfinite(float(value)):
                        metric_values[key].append(float(value))
                if run.latency_ms is not None:
                    latencies.append(float(run.latency_ms))
                    total_latency_ms += float(run.latency_ms)
                    page_count += result.page_count or 0
            parser_benchmarks.append(
                ParserBenchmark(
                    parser_key=f"{parser_name}:{parser_version or '-'}:{config_hash}",
                    parser_name=parser_name,
                    parser_version=parser_version,
                    config_hash=config_hash,
                    run_count=len(group),
                    document_count=len(document_ids),
                    metrics={
                        key: _aggregate(values, bounded=key != "text_cer")
                        for key, values in sorted(metric_values.items())
                    },
                    latency_p50_ms=_percentile(latencies, 0.5),
                    latency_p95_ms=_percentile(latencies, 0.95),
                    pages_per_minute=(
                        page_count / (total_latency_ms / 60_000)
                        if page_count and total_latency_ms
                        else None
                    ),
                )
            )
        parser_benchmarks.sort(
            key=lambda item: item.metrics.get("overall_quality", MetricAggregate()).value or -1,
            reverse=True,
        )
        recent_results = [
            BenchmarkRunResult(
                run_id=run.id,
                experiment_id=experiment.id,
                experiment_name=experiment.name,
                document_id=document.id,
                document_filename=document.original_filename,
                parser_name=str(run.parser_snapshot.get("name", "Unknown")),
                parser_version=run.parser_snapshot.get("model_version"),
                dataset_name=ground_truth.dataset_name,
                dataset_version=ground_truth.dataset_version,
                metrics=evaluation.metrics,
                latency_ms=run.latency_ms,
                created_at=evaluation.created_at,
            )
            for evaluation, run, experiment, document, ground_truth, _ in rows[:50]
        ]
        return BenchmarkSummary(
            evaluator_version=EVALUATOR_VERSION,
            generated_at=datetime.now(UTC),
            ground_truth_document_count=ground_truth_count,
            evaluated_run_count=len(rows),
            dataset_versions=sorted(
                {
                    f"{ground_truth.dataset_name}@{ground_truth.dataset_version}"
                    for *_, ground_truth, _ in rows
                }
            ),
            parsers=parser_benchmarks,
            recent_results=recent_results,
        )
