"""Run 단위 수동 평가 조회 및 저장 Endpoint."""

from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.evaluation import EvaluationResponse, EvaluationUpsert
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/runs", tags=["evaluations"])


@router.get("/{run_id}/evaluation", response_model=EvaluationResponse | None)
async def get_evaluation(
    run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> EvaluationResponse | None:
    evaluation = await EvaluationService(session).get(run_id, user.id)
    return EvaluationResponse.model_validate(evaluation) if evaluation else None


@router.put("/{run_id}/evaluation", response_model=EvaluationResponse)
async def put_evaluation(
    run_id: UUID,
    data: EvaluationUpsert,
    user: CurrentUser,
    session: SessionDep,
) -> EvaluationResponse:
    evaluation = await EvaluationService(session).upsert(run_id, user.id, data)
    return EvaluationResponse.model_validate(evaluation)
