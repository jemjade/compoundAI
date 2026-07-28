"""모든 버전 1 Router를 공통 API Prefix 아래에 구성한다."""

from fastapi import APIRouter

from app.api.v1 import auth, documents, evaluations, experiments, parsers, runs, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(parsers.router)
api_router.include_router(parsers.preset_router)
api_router.include_router(documents.router)
api_router.include_router(experiments.router)
api_router.include_router(evaluations.router)
api_router.include_router(runs.router)
