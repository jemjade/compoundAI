"""Ground Truth 등록, 자동 평가 재계산, 정량 Benchmark 조회 Endpoint."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from app.api.dependencies import CurrentUser, SessionDep, StorageDep
from app.core.exceptions import AppError
from app.schemas.benchmark import (
    AutomatedEvaluationResponse,
    BenchmarkSummary,
    GroundTruthResponse,
    RecomputeResponse,
)
from app.services.benchmark_service import BenchmarkService

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])
MAX_GROUND_TRUTH_BYTES = 25 * 1024 * 1024


@router.get("/summary", response_model=BenchmarkSummary)
async def benchmark_summary(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> BenchmarkSummary:
    return await BenchmarkService(session, storage).summary(user.id)


@router.post("/recompute", response_model=RecomputeResponse)
async def recompute_benchmarks(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> RecomputeResponse:
    return await BenchmarkService(session, storage).recompute_all(user.id)


@router.get("/ground-truths", response_model=list[GroundTruthResponse])
async def list_ground_truths(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> list[GroundTruthResponse]:
    return await BenchmarkService(session, storage).list_ground_truths(user.id)


@router.put(
    "/documents/{document_id}/ground-truth",
    response_model=GroundTruthResponse,
)
async def put_ground_truth(
    document_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    dataset_name: Annotated[str, Form(min_length=1, max_length=200)],
    dataset_version: Annotated[str, Form(min_length=1, max_length=100)],
    schema_version: Annotated[str, Form(min_length=1, max_length=30)] = "1.0",
    notes: Annotated[str | None, Form(max_length=4000)] = None,
) -> GroundTruthResponse:
    content = await file.read(MAX_GROUND_TRUTH_BYTES + 1)
    await file.close()
    if len(content) > MAX_GROUND_TRUTH_BYTES:
        raise AppError(
            "GROUND_TRUTH_TOO_LARGE",
            "Ground Truth exceeds the 25 MB limit.",
            413,
        )
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(
            "INVALID_GROUND_TRUTH",
            "Ground Truth file must be valid UTF-8 JSON.",
            422,
        ) from exc
    return await BenchmarkService(session, storage).upsert_ground_truth(
        document_id,
        user.id,
        payload,
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        schema_version=schema_version,
        notes=notes,
    )


@router.get(
    "/runs/{run_id}",
    response_model=AutomatedEvaluationResponse | None,
)
async def get_run_benchmark(
    run_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> AutomatedEvaluationResponse | None:
    return await BenchmarkService(session, storage).get_run_evaluation(run_id, user.id)
