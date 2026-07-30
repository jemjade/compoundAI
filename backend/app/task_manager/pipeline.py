"""영속적인 Parser 및 비식별화 상태 전이 Pipeline."""

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.deidentifiers.registry import get_deidentifier_adapter
from app.adapters.parsers.registry import get_parser_adapter
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.models.document import Document
from app.db.models.experiment import (
    DeidentificationStatus,
    ExperimentRun,
    ParseStatus,
)
from app.db.models.parser import ParserConnector
from app.db.models.result import DeidentificationResult, RunResult
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


async def execute_run(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
) -> None:
    """Parsing을 실행해 Canonical 산출물을 저장한 뒤 선택적으로 비식별화한다.

    Parsing과 비식별화는 의도적으로 각각 Commit한다. 후속 파수 작업이 실패해도
    성공한 Parser 결과를 Rollback하거나 실패 상태로 바꾸면 안 된다.
    """
    started = monotonic()
    work_dir = None
    should_deidentify = False
    parser_adapter_key: str | None = None
    try:
        async with session_factory() as session:
            run = await session.get(ExperimentRun, run_id)
            if run is None or run.parse_status != ParseStatus.PENDING:
                return
            run.parse_status = ParseStatus.RUNNING
            run.started_at = datetime.now(UTC)
            run.error_code = None
            run.error_message = None
            # Polling Client가 상태 전이를 볼 수 있도록 외부 작업 전에 RUNNING을 Commit한다.
            await session.commit()
            logger.info(
                "parser_run_started",
                extra={
                    "task_id": str(run.id),
                    "document_id": str(run.document_id),
                    "parser_name": run.parser_snapshot.get("name"),
                },
            )

            connector = await session.get(ParserConnector, run.parser_connector_id)
            document = await session.get(Document, run.document_id)
            if connector is None:
                raise AppError("PARSER_NOT_FOUND", "Parser connector no longer exists.")
            if document is None:
                raise AppError("DOCUMENT_NOT_FOUND", "Document no longer exists.")
            if not connector.is_active:
                raise AppError("PARSER_DISABLED", "Parser connector is disabled.")

            parser_adapter_key = connector.adapter_key
            adapter = get_parser_adapter(connector)
            input_path = storage.resolve(document.storage_path)
            work_dir = await storage.prepare_run_work_directory(run_id)
            execution_result = await asyncio.wait_for(
                adapter.parse(input_path, work_dir, run.config_snapshot),
                timeout=connector.timeout_seconds + 1,
            )
            try:
                canonical = await adapter.normalize(
                    execution_result,
                    document_id=str(document.id),
                    run_id=str(run.id),
                )
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    "PARSER_NORMALIZATION_FAILED",
                    f"Parser normalization failed: {type(exc).__name__}.",
                ) from exc
            try:
                paths = await storage.save_parser_results(
                    run.id,
                    execution_result,
                    canonical,
                )
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    "RESULT_STORAGE_FAILED",
                    "Parser results could not be stored.",
                ) from exc
            latency_ms = int((monotonic() - started) * 1000)
            blocks = [block for page in canonical.pages for block in page.blocks]
            result = await session.scalar(select(RunResult).where(RunResult.run_id == run.id))
            result_values = {
                **paths,
                "preview_text": canonical.full_text[:1000],
                "page_count": len(canonical.pages),
                "text_length": len(canonical.full_text),
                "block_count": len(blocks),
                "table_count": sum(block.type == "table" for block in blocks),
                "image_count": sum(block.type == "image" for block in blocks),
                "parser_metrics": execution_result.metrics,
            }
            if result is None:
                result = RunResult(run_id=run.id, **result_values)
                session.add(result)
            else:
                for field, value in result_values.items():
                    setattr(result, field, value)
            run.parse_status = ParseStatus.SUCCEEDED
            run.latency_ms = latency_ms
            run.completed_at = datetime.now(UTC)
            result_size_bytes = sum(storage.resolve(path).stat().st_size for path in paths.values())
            should_deidentify = run.deidentification_status == DeidentificationStatus.PENDING
            # 이 Commit이 Parsing과 파수 작업 사이의 영속성 경계다.
            await session.commit()
            logger.info(
                "parser_run_succeeded",
                extra={
                    "task_id": str(run.id),
                    "document_id": str(run.document_id),
                    "parser_name": connector.name,
                    "device": execution_result.metrics.get("device"),
                    "latency_ms": latency_ms,
                    "page_count": len(canonical.pages),
                    "result_size_bytes": result_size_bytes,
                    "warning_count": execution_result.metrics.get("warning_count", 0),
                    "status": ParseStatus.SUCCEEDED.value,
                },
            )
        if should_deidentify:
            await execute_deidentification(run_id, session_factory, storage)
    except asyncio.CancelledError:
        # 취소 상태를 기록한 다음 TaskManager로 취소 예외를 전달한다.
        await _mark_interrupted(run_id, session_factory)
        raise
    except Exception as exc:
        error_code = (
            exc.code
            if isinstance(exc, AppError)
            else (
                "PARSING_TIMEOUT" if parser_adapter_key == "pp_structure_v3" else "PARSER_TIMEOUT"
            )
            if isinstance(exc, TimeoutError)
            else "PARSER_EXECUTION_FAILED"
        )
        error_message = (
            exc.message
            if isinstance(exc, AppError)
            else f"Parser execution failed: {type(exc).__name__}."
        )
        logger.exception(
            "parser_run_failed",
            extra={
                "task_id": str(run_id),
                "error_code": error_code,
                "status": ParseStatus.FAILED.value,
            },
        )
        try:
            await storage.save_run_error(run_id, f"{error_code}: {error_message}")
        except Exception:
            logger.exception(
                "parser_error_artifact_storage_failed",
                extra={"task_id": str(run_id), "error_code": error_code},
            )
        async with session_factory() as session:
            run = await session.get(ExperimentRun, run_id)
            if run is not None:
                run.parse_status = ParseStatus.FAILED
                if run.deidentification_status in {
                    DeidentificationStatus.PENDING,
                    DeidentificationStatus.RUNNING,
                }:
                    run.deidentification_status = DeidentificationStatus.INTERRUPTED
                run.error_code = error_code
                run.error_message = error_message[:2000]
                run.completed_at = datetime.now(UTC)
                run.latency_ms = int((monotonic() - started) * 1000)
                await session.commit()
    finally:
        # Adapter의 임시 파일은 정리하고 상위 디렉터리의 최종 산출물만 유지한다.
        if work_dir is not None:
            await storage.cleanup_run_work_directory(work_dir)


async def execute_deidentification(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession],
    storage: StorageService,
) -> None:
    """parse_status를 변경하지 않고 비식별화를 실행하고 저장한다."""
    settings = get_settings()
    started = monotonic()
    try:
        async with session_factory() as session:
            run = await session.get(ExperimentRun, run_id)
            if (
                run is None
                or run.parse_status != ParseStatus.SUCCEEDED
                or run.deidentification_status != DeidentificationStatus.PENDING
            ):
                return
            run.deidentification_status = DeidentificationStatus.RUNNING
            await session.commit()

            document = await session.get(Document, run.document_id)
            parser_result = await session.scalar(
                select(RunResult).where(RunResult.run_id == run.id)
            )
            if document is None:
                raise AppError("DOCUMENT_NOT_FOUND", "Document no longer exists.")
            if parser_result is None:
                raise AppError(
                    "FASOO_EXECUTION_FAILED",
                    "Parser result is not available for deidentification.",
                )
            input_path = _deidentification_input_path(
                settings.fasoo_input_type,
                document,
                parser_result,
                storage,
            )
            adapter = get_deidentifier_adapter(settings)
            execution_result = await asyncio.wait_for(
                adapter.deidentify(
                    input_path=input_path,
                    input_type=settings.fasoo_input_type,
                    output_dir=await storage.create_run_directory(run.id),
                    config={},
                ),
                timeout=(settings.fasoo_timeout_seconds + settings.fasoo_artifact_wait_seconds + 1),
            )
            result_paths = await storage.save_deidentification_result(
                run.id,
                execution_result,
            )
            latency_ms = int((monotonic() - started) * 1000)
            metrics = {**execution_result.metrics, "pipeline_latency_ms": latency_ms}
            stored_result = await session.scalar(
                select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
            )
            if stored_result is None:
                stored_result = DeidentificationResult(
                    run_id=run.id,
                    provider=execution_result.provider,
                    input_type=settings.fasoo_input_type,
                )
                session.add(stored_result)
            stored_result.provider = execution_result.provider
            stored_result.input_type = settings.fasoo_input_type
            stored_result.result_path = result_paths["result_path"]
            stored_result.masked_file_path = result_paths["masked_file_path"]
            stored_result.detected_entity_count = execution_result.detected_entity_count
            stored_result.masked_entity_count = execution_result.masked_entity_count
            stored_result.metrics = metrics
            stored_result.error_message = None
            run.deidentification_status = DeidentificationStatus.SUCCEEDED
            await session.commit()
    except asyncio.CancelledError:
        await _mark_interrupted(run_id, session_factory)
        raise
    except Exception as exc:
        # 이 분기는 후속 작업 실패만 기록하며 parse_status는 SUCCEEDED로 유지한다.
        error_code = (
            exc.code
            if isinstance(exc, AppError)
            else "FASOO_TIMEOUT"
            if isinstance(exc, TimeoutError)
            else "FASOO_EXECUTION_FAILED"
        )
        error_message = (
            exc.message
            if isinstance(exc, AppError)
            else f"Deidentification failed: {type(exc).__name__}."
        )
        await storage.save_run_error(
            run_id,
            f"{error_code}: {error_message}",
        )
        async with session_factory() as session:
            run = await session.get(ExperimentRun, run_id)
            if run is None:
                return
            stored_result = await session.scalar(
                select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
            )
            if stored_result is None:
                stored_result = DeidentificationResult(
                    run_id=run.id,
                    provider="FASOO" if settings.fasoo_enabled else "MOCK_FASOO",
                    input_type=settings.fasoo_input_type,
                )
                session.add(stored_result)
            stored_result.result_path = None
            stored_result.masked_file_path = None
            stored_result.metrics = {"error_code": error_code}
            stored_result.error_message = error_message[:2000]
            run.deidentification_status = DeidentificationStatus.FAILED
            await session.commit()


def _deidentification_input_path(
    input_type: str,
    document: Document,
    result: RunResult,
    storage: StorageService,
) -> Path:
    """설정된 파수 입력을 이미 저장된 산출물 경로로 변환한다."""
    relative_path = {
        "ORIGINAL_FILE": document.storage_path,
        "TEXT": result.text_path,
        "MARKDOWN": result.markdown_path,
        "CANONICAL_JSON": result.canonical_result_path,
    }[input_type]
    if relative_path is None:
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            f"{input_type} input is not available for deidentification.",
        )
    path = storage.resolve(relative_path)
    if not path.is_file():
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            f"{input_type} input file is not available for deidentification.",
        )
    if input_type != "ORIGINAL_FILE" and path.stat().st_size == 0:
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            f"{input_type} parser output is empty and cannot be deidentified.",
        )
    return path


async def _mark_interrupted(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """프로세스 내부 작업 취소 시 실행 중이던 단계를 중단 상태로 표시한다."""
    async with session_factory() as session:
        run = await session.scalar(select(ExperimentRun).where(ExperimentRun.id == run_id))
        if run is not None:
            if run.parse_status in {ParseStatus.PENDING, ParseStatus.RUNNING}:
                run.parse_status = ParseStatus.INTERRUPTED
            if run.deidentification_status in {
                DeidentificationStatus.PENDING,
                DeidentificationStatus.RUNNING,
            }:
                run.deidentification_status = DeidentificationStatus.INTERRUPTED
            run.error_code = "TASK_CANCELLED"
            run.error_message = "Task was cancelled before completion."
            run.completed_at = datetime.now(UTC)
            await session.commit()
