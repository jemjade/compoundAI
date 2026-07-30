"""FastAPI 애플리케이션 구성과 프로세스 생명주기 복구 처리."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api.dependencies import get_storage
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import install_exception_handlers
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models.experiment import (
    DeidentificationStatus,
    ExperimentRun,
    ParseStatus,
)
from app.db.session import async_session_factory, engine
from app.services.parser_catalog import seed_enabled_parser_connectors
from app.task_manager.manager import TaskManager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_storage().data_root.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        # 프로세스 내부 작업은 재시작 후 복구할 수 없으므로 DB에 중단 상태를 기록한다.
        await session.execute(
            update(ExperimentRun)
            .where(ExperimentRun.parse_status == ParseStatus.RUNNING)
            .values(parse_status=ParseStatus.INTERRUPTED)
        )
        await session.execute(
            update(ExperimentRun)
            .where(ExperimentRun.deidentification_status == DeidentificationStatus.RUNNING)
            .values(deidentification_status=DeidentificationStatus.INTERRUPTED)
        )
        await session.commit()
        await seed_enabled_parser_connectors(session, settings)
    app.state.task_manager = TaskManager(settings.max_concurrent_runs)
    yield
    await app.state.task_manager.shutdown()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_exception_handlers(app)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
