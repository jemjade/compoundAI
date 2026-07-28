"""실험 생명주기·비교·Diff·CSV 내보내기 Endpoint."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, SessionDep, StorageDep
from app.db.session import async_session_factory
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentCreatedResponse,
    ExperimentDetail,
    ExperimentListItem,
)
from app.schemas.result import ComparisonResponse, TextDiffResponse
from app.services.comparison_service import ComparisonService
from app.services.experiment_service import ExperimentService
from app.task_manager.manager import TaskManager

router = APIRouter(prefix="/experiments", tags=["experiments"])


def service(
    request: Request,
    session: SessionDep,
    storage: StorageDep,
) -> ExperimentService:
    manager: TaskManager = request.app.state.task_manager
    return ExperimentService(session, async_session_factory, storage, manager)


@router.post("", response_model=ExperimentCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_experiment(
    data: ExperimentCreate,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> ExperimentCreatedResponse:
    return await service(request, session, storage).create(data, user.id)


@router.get("", response_model=list[ExperimentListItem])
async def list_experiments(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> list[ExperimentListItem]:
    return await service(request, session, storage).list(user.id)


@router.get("/{experiment_id}", response_model=ExperimentDetail)
async def get_experiment(
    experiment_id: UUID,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> ExperimentDetail:
    return await service(request, session, storage).detail(experiment_id, user.id)


@router.get("/{experiment_id}/comparison", response_model=ComparisonResponse)
async def comparison(
    experiment_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> ComparisonResponse:
    return await ComparisonService(session, storage).comparison(experiment_id, user.id)


@router.get("/{experiment_id}/text-diff", response_model=TextDiffResponse)
async def text_diff(
    experiment_id: UUID,
    base_run_id: UUID,
    target_run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    normalize_whitespace: bool = Query(default=True),
) -> TextDiffResponse:
    return await ComparisonService(session, storage).text_diff(
        experiment_id,
        base_run_id,
        target_run_id,
        user.id,
        normalize_whitespace,
    )


@router.get("/{experiment_id}/export.csv")
async def export_comparison_csv(
    experiment_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> Response:
    content = await ComparisonService(session, storage).export_csv(
        experiment_id,
        user.id,
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="parselab-comparison-{experiment_id}.csv"'
            )
        },
    )
