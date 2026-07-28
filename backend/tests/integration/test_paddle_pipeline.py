"""Paddle Parser Run이 기존 Task Manager와 저장 상태를 재사용하는지 검증한다."""

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile

from app.adapters.parsers.base import ParserExecutionResult
from app.core.exceptions import AppError
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models.experiment import ExperimentRun, ParseStatus
from app.db.models.parser import ExecutionType
from app.db.models.result import RunResult
from app.schemas.auth import SignupRequest
from app.schemas.canonical_document import CanonicalDocument, DocumentPage
from app.schemas.experiment import ExperimentCreate, ParserRunCreate
from app.schemas.parser import ParserCreate
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.services.experiment_service import ExperimentService, calculate_experiment_status
from app.services.parser_service import ParserService
from app.services.storage_service import StorageService
from app.task_manager.manager import TaskManager


class _PipelineAdapter:
    def __init__(
        self,
        failure: AppError | None = None,
        *,
        wait_until_cancelled: bool = False,
    ) -> None:
        self.failure = failure
        self.wait_until_cancelled = wait_until_cancelled
        self.started = asyncio.Event()

    async def health_check(self) -> dict[str, object]:
        return {"healthy": True}

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, object],
    ) -> ParserExecutionResult:
        del input_path, output_dir, config
        self.started.set()
        if self.wait_until_cancelled:
            await asyncio.Event().wait()
        if self.failure is not None:
            raise self.failure
        return ParserExecutionResult(
            raw_data={
                "parser": {"name": "pp_structure_v3"},
                "document": {"page_count": 1},
                "content": {"pages": [{"page_number": 1, "raw": {}}]},
            },
            markdown="# 테스트 문서",
            text="테스트 문서",
            metrics={
                "device": "cpu",
                "page_count": 1,
                "warning_count": 0,
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        del execution_result
        return CanonicalDocument(
            document_id=document_id,
            run_id=run_id,
            parser_name="PaddleOCR PP-StructureV3",
            parser_version="3.7.0",
            full_text="테스트 문서",
            markdown="# 테스트 문서",
            pages=[DocumentPage(page_number=1, text="테스트 문서")],
        )


class _FailingResultStorage(StorageService):
    async def save_parser_results(self, *args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        raise OSError("synthetic disk failure")


async def _execute_paddle_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter: _PipelineAdapter,
    fail_storage: bool = False,
    cancel_run: bool = False,
) -> tuple[ExperimentRun, RunResult | None, Path]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    storage_class = _FailingResultStorage if fail_storage else StorageService
    data_root = tmp_path / "data"
    storage = storage_class(data_root, 1024 * 1024)
    manager = TaskManager(max_concurrency=1)
    monkeypatch.setattr(
        "app.task_manager.pipeline.get_parser_adapter",
        lambda _connector: adapter,
    )
    try:
        async with session_factory() as session:
            user = await AuthService(session).signup(
                SignupRequest(
                    email=f"admin-{tmp_path.name}@example.com",
                    password="correct-horse-battery",
                    name="Admin",
                )
            )
            upload = UploadFile(
                BytesIO(b"\x89PNG\r\n\x1a\nsynthetic fixture"),
                filename="fixture.png",
                headers=Headers({"content-type": "image/png"}),
            )
            document = await DocumentService(session, storage).upload(upload, user.id)
            connector = await ParserService(session).create(
                ParserCreate(
                    name="PaddleOCR PP-StructureV3",
                    slug="paddle-pipeline-test",
                    execution_type=ExecutionType.BUILTIN,
                    adapter_key="pp_structure_v3",
                    model_name="PP-StructureV3",
                    model_version="3.7.0",
                    supported_formats=["pdf", "png", "jpg", "jpeg", "webp"],
                    config_schema={
                        "type": "object",
                        "properties": {
                            "use_table_recognition": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                    default_config={"use_table_recognition": True},
                ),
                user,
            )
            created = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).create(
                ExperimentCreate(
                    name="Paddle pipeline test",
                    document_id=document.id,
                    parser_runs=[
                        ParserRunCreate(parser_connector_id=connector.id),
                    ],
                ),
                user.id,
            )
            run_id = created.runs[0].run_id
            assert created.runs[0].parse_status == ParseStatus.PENDING

        submitted_tasks = list(manager._tasks.values())  # noqa: SLF001
        if cancel_run:
            await asyncio.wait_for(adapter.started.wait(), timeout=1)
            async with session_factory() as session:
                await ExperimentService(
                    session,
                    session_factory,
                    storage,
                    manager,
                ).cancel(run_id, user.id)
        await asyncio.gather(*submitted_tasks, return_exceptions=cancel_run)
        async with session_factory() as session:
            run = await session.get(ExperimentRun, run_id)
            assert run is not None
            result = await session.scalar(select(RunResult).where(RunResult.run_id == run_id))
            session.expunge(run)
            if result is not None:
                session.expunge(result)
            return run, result, data_root
    finally:
        await manager.shutdown()
        await engine.dispose()


async def test_paddle_run_reaches_succeeded_and_stores_result_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, result, data_root = await _execute_paddle_run(
        tmp_path,
        monkeypatch,
        adapter=_PipelineAdapter(),
    )

    assert run.parse_status == ParseStatus.SUCCEEDED
    assert calculate_experiment_status([run]) == "COMPLETED"
    assert run.error_code is None
    assert result is not None
    for relative_path in (
        result.raw_result_path,
        result.canonical_result_path,
        result.markdown_path,
        result.text_path,
    ):
        assert relative_path is not None
        assert (data_root / relative_path).is_file()


async def test_paddle_run_records_inference_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, result, _ = await _execute_paddle_run(
        tmp_path,
        monkeypatch,
        adapter=_PipelineAdapter(
            AppError("PARSING_FAILED", "Synthetic Paddle inference failure."),
        ),
    )

    assert run.parse_status == ParseStatus.FAILED
    assert run.error_code == "PARSING_FAILED"
    assert result is None


async def test_paddle_run_records_result_storage_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, result, _ = await _execute_paddle_run(
        tmp_path,
        monkeypatch,
        adapter=_PipelineAdapter(),
        fail_storage=True,
    )

    assert run.parse_status == ParseStatus.FAILED
    assert run.error_code == "RESULT_STORAGE_FAILED"
    assert result is None


async def test_paddle_run_records_timeout_with_paddle_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def force_timeout(awaitable: object, **_: object) -> object:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise TimeoutError

    monkeypatch.setattr(
        "app.task_manager.pipeline.asyncio.wait_for",
        force_timeout,
    )
    run, result, _ = await _execute_paddle_run(
        tmp_path,
        monkeypatch,
        adapter=_PipelineAdapter(),
    )

    assert run.parse_status == ParseStatus.FAILED
    assert run.error_code == "PARSING_TIMEOUT"
    assert result is None


async def test_paddle_run_cancellation_records_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, result, _ = await _execute_paddle_run(
        tmp_path,
        monkeypatch,
        adapter=_PipelineAdapter(wait_until_cancelled=True),
        cancel_run=True,
    )

    assert run.parse_status == ParseStatus.INTERRUPTED
    assert run.error_code == "TASK_CANCELLED"
    assert result is None
