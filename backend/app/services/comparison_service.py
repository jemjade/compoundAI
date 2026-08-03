"""비교 집계·Text Diff·표 투영·CSV 내보내기."""

import asyncio
import csv
import io
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.models.document import Document
from app.db.models.evaluation import ManualEvaluation
from app.db.models.experiment import Experiment, ExperimentRun
from app.db.models.result import DeidentificationResult, RunResult
from app.schemas.evaluation import EvaluationResponse
from app.schemas.result import (
    ComparisonResponse,
    ComparisonRun,
    DeidentificationSummary,
    RunMetrics,
    TextDiffResponse,
)
from app.services.storage_service import StorageService
from app.utils.text_diff import compare_text_async


def extract_tables(canonical: Any) -> list[dict[str, Any]]:
    """Canonical JSON의 표 블록을 가벼운 UI 규약으로 투영한다."""
    if not isinstance(canonical, dict) or not isinstance(canonical.get("pages"), list):
        return []
    tables: list[dict[str, Any]] = []
    for page in canonical["pages"]:
        if not isinstance(page, dict) or not isinstance(page.get("blocks"), list):
            continue
        for block in page["blocks"]:
            if not isinstance(block, dict) or block.get("type") != "table":
                continue
            tables.append(
                {
                    "id": block.get("id"),
                    "page_number": block.get("page_number", page.get("page_number")),
                    "text": block.get("text", ""),
                    "html": block.get("html"),
                    "cells": block.get("cells") if isinstance(block.get("cells"), list) else [],
                }
            )
    return tables


def page_text_lengths(canonical: Any) -> list[int]:
    """상대적인 Layout 비교를 위해 페이지별 텍스트 길이를 반환한다."""
    if not isinstance(canonical, dict) or not isinstance(canonical.get("pages"), list):
        return []
    return [len(str(page.get("text", ""))) for page in canonical["pages"] if isinstance(page, dict)]


def _paths_size(paths: list[Path]) -> int:
    """파일 내용을 메모리에 올리지 않고 저장된 산출물 크기를 측정한다."""
    return sum(path.stat().st_size for path in paths if path.is_file())


def csv_safe(value: Any) -> Any:
    """Spreadsheet가 내보낸 Cell을 수식으로 실행하지 못하게 방지한다."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


class ComparisonService:
    """저장된 산출물로 사용자 범위의 비교·Diff·내보내기 View를 구성한다."""

    def __init__(self, session: AsyncSession, storage: StorageService) -> None:
        self.session = session
        self.storage = storage

    async def _owned_experiment(self, experiment_id: UUID, user_id: UUID) -> Experiment:
        experiment = await self.session.scalar(
            select(Experiment).where(
                Experiment.id == experiment_id,
                Experiment.created_by == user_id,
            )
        )
        if experiment is None:
            raise AppError("EXPERIMENT_NOT_FOUND", "Experiment not found.", 404)
        return experiment

    async def comparison(self, experiment_id: UUID, user_id: UUID) -> ComparisonResponse:
        """비교 화면을 위해 DB 지표와 파일 기반 내용을 결합한다."""
        experiment = await self._owned_experiment(experiment_id, user_id)
        document = await self.session.get(Document, experiment.document_id)
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "Experiment document not found.", 404)
        runs = list(
            await self.session.scalars(
                select(ExperimentRun)
                .where(ExperimentRun.experiment_id == experiment.id)
                .order_by(ExperimentRun.created_at)
            )
        )
        comparison_runs: list[ComparisonRun] = []
        for run in runs:
            result = await self.session.scalar(select(RunResult).where(RunResult.run_id == run.id))
            text = await self.storage.read_text(result.text_path) if result else None
            markdown = await self.storage.read_text(result.markdown_path) if result else None
            canonical: dict[str, Any] | list[Any] | None = None
            if result is not None:
                # Canonical JSON은 클 수 있으므로 PostgreSQL에는 경로만 저장한다.
                canonical_payload = await self.storage.read_text(result.canonical_result_path)
                if canonical_payload:
                    try:
                        loaded_canonical = json.loads(canonical_payload)
                    except json.JSONDecodeError:
                        loaded_canonical = None
                    if isinstance(loaded_canonical, (dict, list)):
                        canonical = loaded_canonical
            deidentification_result = await self.session.scalar(
                select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
            )
            deidentified = None
            deidentification_summary = None
            if deidentification_result is not None:
                stored_payload = await self.storage.read_text(deidentification_result.result_path)
                if stored_payload:
                    try:
                        parsed_payload = json.loads(stored_payload)
                    except json.JSONDecodeError:
                        parsed_payload = {}
                    if isinstance(parsed_payload, dict):
                        value = parsed_payload.get("deidentified_text")
                        deidentified = value if isinstance(value, str) else None
                deidentification_summary = DeidentificationSummary(
                    provider=deidentification_result.provider,
                    input_type=deidentification_result.input_type,
                    detected_entity_count=(deidentification_result.detected_entity_count),
                    masked_entity_count=deidentification_result.masked_entity_count,
                    masked_file_available=(deidentification_result.masked_file_path is not None),
                    latency_ms=deidentification_result.metrics.get("pipeline_latency_ms"),
                    error_message=deidentification_result.error_message,
                )
            evaluation = await self.session.scalar(
                select(ManualEvaluation).where(
                    ManualEvaluation.run_id == run.id,
                    ManualEvaluation.evaluator_id == user_id,
                )
            )
            result_paths = (
                [
                    self.storage.resolve(path)
                    for path in {
                        result.raw_result_path,
                        result.canonical_result_path,
                        result.markdown_path,
                        result.text_path,
                        (deidentification_result.result_path if deidentification_result else None),
                        (
                            deidentification_result.masked_file_path
                            if deidentification_result
                            else None
                        ),
                        *(
                            item.get("path")
                            for item in result.artifact_manifest
                            if isinstance(item, dict)
                        ),
                    }
                    if path is not None
                ]
                if result
                else []
            )
            result_size_bytes = await asyncio.to_thread(_paths_size, result_paths)
            comparison_runs.append(
                ComparisonRun(
                    run_id=run.id,
                    parser_name=run.parser_snapshot["name"],
                    parser_version=run.parser_snapshot.get("model_version"),
                    parse_status=run.parse_status.value,
                    deidentification_status=run.deidentification_status.value,
                    metrics=RunMetrics(
                        latency_ms=run.latency_ms,
                        page_count=result.page_count if result else None,
                        text_length=result.text_length if result else 0,
                        block_count=result.block_count if result else 0,
                        table_count=result.table_count if result else 0,
                        image_count=result.image_count if result else 0,
                        result_size_bytes=result_size_bytes,
                        page_text_lengths=page_text_lengths(canonical),
                    ),
                    preview_text=result.preview_text if result else None,
                    text=text,
                    markdown=markdown,
                    deidentified=deidentified,
                    deidentification=deidentification_summary,
                    canonical=canonical,
                    tables=extract_tables(canonical),
                    artifacts=(result.artifact_manifest if result else []),
                    evaluation=(
                        EvaluationResponse.model_validate(evaluation) if evaluation else None
                    ),
                )
            )
        return ComparisonResponse(
            experiment_id=experiment.id,
            document={
                "id": str(document.id),
                "filename": document.original_filename,
            },
            runs=comparison_runs,
        )

    async def text_diff(
        self,
        experiment_id: UUID,
        base_run_id: UUID,
        target_run_id: UUID,
        user_id: UUID,
        normalize_whitespace: bool,
    ) -> TextDiffResponse:
        """두 Run이 소유한 실험에 속하는지 확인한 후에만 비교한다."""
        await self._owned_experiment(experiment_id, user_id)
        texts: list[str] = []
        for run_id in (base_run_id, target_run_id):
            run = await self.session.get(ExperimentRun, run_id)
            if run is None or run.experiment_id != experiment_id:
                raise AppError("RUN_NOT_FOUND", "Run is not part of this experiment.", 404)
            result = await self.session.scalar(select(RunResult).where(RunResult.run_id == run_id))
            if result is None:
                raise AppError("RUN_RESULT_NOT_FOUND", "Run result is not available.", 409)
            texts.append(await self.storage.read_text(result.text_path) or "")
        diff = await compare_text_async(texts[0], texts[1], normalize_whitespace)
        return TextDiffResponse(
            base_run_id=base_run_id,
            target_run_id=target_run_id,
            **diff,
        )

    async def export_csv(self, experiment_id: UUID, user_id: UUID) -> str:
        """운영 지표와 현재 사용자 평가를 UTF-8 CSV로 내보낸다."""
        comparison = await self.comparison(experiment_id, user_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "run_id",
                "parser_name",
                "parser_version",
                "parse_status",
                "deidentification_status",
                "latency_ms",
                "page_count",
                "text_length",
                "block_count",
                "table_count",
                "image_count",
                "result_size_bytes",
                "detected_entity_count",
                "masked_entity_count",
                "text_score",
                "table_score",
                "reading_order_score",
                "deidentification_score",
                "is_preferred",
                "notes",
            ]
        )
        for run in comparison.runs:
            evaluation = run.evaluation
            writer.writerow(
                [
                    run.run_id,
                    csv_safe(run.parser_name),
                    csv_safe(run.parser_version),
                    run.parse_status,
                    run.deidentification_status,
                    run.metrics.latency_ms,
                    run.metrics.page_count,
                    run.metrics.text_length,
                    run.metrics.block_count,
                    run.metrics.table_count,
                    run.metrics.image_count,
                    run.metrics.result_size_bytes,
                    (run.deidentification.detected_entity_count if run.deidentification else None),
                    (run.deidentification.masked_entity_count if run.deidentification else None),
                    evaluation.text_score if evaluation else None,
                    evaluation.table_score if evaluation else None,
                    evaluation.reading_order_score if evaluation else None,
                    evaluation.deidentification_score if evaluation else None,
                    evaluation.is_preferred if evaluation else False,
                    csv_safe(evaluation.notes) if evaluation else None,
                ]
            )
        # BOM을 추가해 일반적인 Spreadsheet에서 한글이 올바르게 열리도록 한다.
        return f"\ufeff{output.getvalue()}"
