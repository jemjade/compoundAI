"""Run 상태·재실행·취소·산출물 다운로드 Endpoint."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.dependencies import CurrentUser, SessionDep, StorageDep
from app.core.exceptions import AppError
from app.db.models.experiment import Experiment, ExperimentRun
from app.db.models.result import DeidentificationResult, RunResult
from app.db.session import async_session_factory
from app.schemas.experiment import RunSummary
from app.schemas.result import DeidentificationSummary
from app.services.experiment_service import ExperimentService
from app.task_manager.manager import TaskManager

router = APIRouter(prefix="/runs", tags=["runs"])


async def owned_run(run_id: UUID, user_id: UUID, session: SessionDep) -> ExperimentRun:
    run = await session.get(ExperimentRun, run_id)
    if run is None:
        raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
    experiment = await session.scalar(
        select(Experiment).where(
            Experiment.id == run.experiment_id,
            Experiment.created_by == user_id,
        )
    )
    if experiment is None:
        raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
    return run


@router.get("/{run_id}", response_model=RunSummary)
async def get_run(run_id: UUID, user: CurrentUser, session: SessionDep) -> RunSummary:
    run = await owned_run(run_id, user.id, session)
    summary = RunSummary.model_validate(run)
    result = await session.scalar(
        select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
    )
    if result is None:
        return summary
    return summary.model_copy(
        update={
            "deidentification": DeidentificationSummary(
                provider=result.provider,
                input_type=result.input_type,
                detected_entity_count=result.detected_entity_count,
                masked_entity_count=result.masked_entity_count,
                masked_file_available=result.masked_file_path is not None,
                latency_ms=result.metrics.get("pipeline_latency_ms"),
                error_message=result.error_message,
            )
        }
    )


@router.post("/{run_id}/retry", response_model=RunSummary)
async def retry_run(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> RunSummary:
    manager: TaskManager = request.app.state.task_manager
    run = await ExperimentService(session, async_session_factory, storage, manager).retry(
        run_id, user.id
    )
    return RunSummary.model_validate(run)


@router.post("/{run_id}/cancel", response_model=RunSummary)
async def cancel_run(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> RunSummary:
    manager: TaskManager = request.app.state.task_manager
    run = await ExperimentService(session, async_session_factory, storage, manager).cancel(
        run_id, user.id
    )
    return RunSummary.model_validate(run)


@router.get("/{run_id}/{artifact}", response_class=FileResponse)
async def get_artifact(
    run_id: UUID,
    artifact: str,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> FileResponse:
    await owned_run(run_id, user.id, session)
    if artifact in {"deidentified", "masked"}:
        deidentification_result = await session.scalar(
            select(DeidentificationResult).where(DeidentificationResult.run_id == run_id)
        )
        if artifact == "masked":
            if (
                deidentification_result is None
                or deidentification_result.masked_file_path is None
                or not storage.resolve(deidentification_result.masked_file_path).is_file()
            ):
                raise AppError(
                    "ARTIFACT_NOT_FOUND",
                    "Masked file is not available.",
                    404,
                )
            masked_path = storage.resolve(deidentification_result.masked_file_path)
            return FileResponse(
                masked_path,
                media_type="application/octet-stream",
                filename=masked_path.name,
            )
        if (
            deidentification_result is None
            or deidentification_result.result_path is None
            or not storage.resolve(deidentification_result.result_path).is_file()
        ):
            raise AppError(
                "ARTIFACT_NOT_FOUND",
                "Deidentified result is not available.",
                404,
            )
        return FileResponse(
            storage.resolve(deidentification_result.result_path),
            media_type="application/json",
            filename="deidentified.json",
        )
    result = await session.scalar(select(RunResult).where(RunResult.run_id == run_id))
    if result is None:
        raise AppError("RUN_RESULT_NOT_FOUND", "Run result is not available.", 404)
    mapping = {
        "raw": (result.raw_result_path, "application/json", "raw.json"),
        "canonical": (
            result.canonical_result_path,
            "application/json",
            "canonical.json",
        ),
        "markdown": (result.markdown_path, "text/markdown", "output.md"),
        "text": (result.text_path, "text/plain", "output.txt"),
    }
    selected = mapping.get(artifact)
    if selected is None:
        raise AppError("ARTIFACT_NOT_FOUND", "Unknown run artifact.", 404)
    path, media_type, filename = selected
    if path is None or not storage.resolve(path).is_file():
        raise AppError("ARTIFACT_NOT_FOUND", "Run artifact is not available.", 404)
    return FileResponse(storage.resolve(path), media_type=media_type, filename=filename)
