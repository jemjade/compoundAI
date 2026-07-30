"""임시 비동기 데이터베이스에서 ParseLab 전체 Workflow를 검증한다."""

import asyncio
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers, UploadFile

from app.adapters.deidentifiers.mock import MockDeidentifierAdapter
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import decode_access_token
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models.experiment import DeidentificationStatus, ExperimentRun, ParseStatus
from app.db.models.parser import ExecutionType
from app.db.models.result import RunResult
from app.repositories.document_repository import DocumentRepository
from app.repositories.parser_repository import ParserRepository
from app.schemas.auth import LoginRequest, SignupRequest
from app.schemas.evaluation import EvaluationUpsert
from app.schemas.experiment import ExperimentCreate, ParserRunCreate
from app.schemas.parser import ParserCreate, ParserPresetCreate, ParserPresetUpdate
from app.services.auth_service import AuthService
from app.services.comparison_service import ComparisonService
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.experiment_service import ExperimentService
from app.services.parser_service import ParserService
from app.services.storage_service import StorageService
from app.task_manager.manager import TaskManager


async def test_mock_parser_vertical_slice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.auth_service.get_settings",
        lambda: Settings(_env_file=None),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    storage = StorageService(tmp_path / "data", 1024 * 1024)
    manager = TaskManager(max_concurrency=2)
    try:
        async with session_factory() as session:
            user = await AuthService(session).signup(
                SignupRequest(
                    email="admin@example.com",
                    password="correct-horse-battery",
                    name="Admin",
                )
            )
            token = await AuthService(session).login(
                LoginRequest(email="admin@example.com", password="correct-horse-battery")
            )
            assert decode_access_token(token) == user.id

            upload = UploadFile(
                BytesIO("첫 문단 test@example.com\n\n연락처 010-1234-5678".encode()),
                filename="contract.txt",
                headers=Headers({"content-type": "text/plain"}),
            )
            document = await DocumentService(session, storage).upload(upload, user.id)
            assert (tmp_path / "data" / document.storage_path).is_file()

            parsers = await ParserRepository(session).list_active()
            assert [parser.slug for parser in parsers] == [
                "mock-line-reader",
                "mock-standard",
                "pp-structure-v3",
            ]
            preset_service = ParserService(session)
            preset = await preset_service.create_preset(
                parsers[0].id,
                ParserPresetCreate(
                    name="Uppercase",
                    config={"prefix": "PRESET"},
                ),
                user,
            )
            preset = await preset_service.update_preset(
                preset.id,
                ParserPresetUpdate(description="Integration preset"),
                user,
            )
            assert preset.description == "Integration preset"
            created = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).create(
                ExperimentCreate(
                    name="계약서 비교",
                    document_id=document.id,
                    run_deidentification=True,
                    parser_runs=[
                        ParserRunCreate(
                            parser_connector_id=parser.id,
                            parser_preset_id=preset.id if parser.id == parsers[0].id else None,
                        )
                        for parser in parsers
                        if document.extension in parser.supported_formats
                    ],
                ),
                user.id,
            )
            assert len(created.runs) == 2

        await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001

        async with session_factory() as session:
            comparison = await ComparisonService(session, storage).comparison(
                created.experiment_id,
                user.id,
            )
            assert len(comparison.runs) == 2
            assert all(run.parse_status == ParseStatus.SUCCEEDED for run in comparison.runs)
            assert comparison.runs[0].text != comparison.runs[1].text
            assert all(run.metrics.text_length > 0 for run in comparison.runs)
            assert all(run.metrics.result_size_bytes > 0 for run in comparison.runs)
            assert all(run.metrics.page_text_lengths for run in comparison.runs)
            assert all(isinstance(run.canonical, dict) for run in comparison.runs)
            assert all(
                run.deidentification_status == DeidentificationStatus.SUCCEEDED
                for run in comparison.runs
            )
            assert all("[EMAIL]" in (run.deidentified or "") for run in comparison.runs)
            assert all(
                run.deidentification and run.deidentification.masked_entity_count == 2
                for run in comparison.runs
            )

            stored_document = await DocumentRepository(session).get_owned(document.id, user.id)
            assert stored_document is not None
            for run in comparison.runs:
                run_dir = tmp_path / "data" / "runs" / str(run.run_id)
                assert (run_dir / "raw.json").is_file()
                assert (run_dir / "canonical.json").is_file()
                assert (run_dir / "output.md").is_file()
                assert (run_dir / "output.txt").is_file()
                assert (run_dir / "deidentified.json").is_file()
                assert not (run_dir / "work").exists()

            evaluation = await EvaluationService(session).upsert(
                comparison.runs[0].run_id,
                user.id,
                EvaluationUpsert(
                    text_score=4,
                    table_score=3,
                    reading_order_score=5,
                    is_preferred=True,
                    notes="Phase 1 통합 테스트",
                ),
            )
            assert evaluation.text_score == 4
            assert evaluation.is_preferred is True
            diff = await ComparisonService(session, storage).text_diff(
                created.experiment_id,
                comparison.runs[0].run_id,
                comparison.runs[1].run_id,
                user.id,
                normalize_whitespace=True,
            )
            assert 0 <= diff.similarity_ratio < 1
            assert diff.added_count + diff.removed_count > 0

            second_evaluation = await EvaluationService(session).upsert(
                comparison.runs[1].run_id,
                user.id,
                EvaluationUpsert(
                    text_score=5,
                    table_score=4,
                    reading_order_score=5,
                    deidentification_score=5,
                    is_preferred=True,
                    notes="Phase 4 선호 결과",
                ),
            )
            first_evaluation = await EvaluationService(session).get(
                comparison.runs[0].run_id,
                user.id,
            )
            assert first_evaluation is not None
            assert first_evaluation.is_preferred is False
            assert second_evaluation.is_preferred is True

            evaluated_comparison = await ComparisonService(
                session,
                storage,
            ).comparison(created.experiment_id, user.id)
            assert evaluated_comparison.runs[0].evaluation is not None
            assert evaluated_comparison.runs[0].evaluation.text_score == 4
            assert evaluated_comparison.runs[1].evaluation is not None
            assert evaluated_comparison.runs[1].evaluation.is_preferred is True
            exported = await ComparisonService(session, storage).export_csv(
                created.experiment_id,
                user.id,
            )
            assert exported.startswith("\ufeffrun_id,parser_name")
            assert "Phase 4 선호 결과" in exported

            command_connector = await ParserService(session).create(
                ParserCreate(
                    name="UV Command",
                    slug="uv-command",
                    execution_type=ExecutionType.COMMAND,
                    adapter_key="generic_command",
                    command_template=["uv", "--version"],
                    supported_formats=["txt"],
                ),
                user,
            )
            command_experiment = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).create(
                ExperimentCreate(
                    name="Command adapter",
                    document_id=document.id,
                    parser_runs=[
                        ParserRunCreate(parser_connector_id=command_connector.id),
                    ],
                ),
                user.id,
            )

        await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001
        async with session_factory() as session:
            command_comparison = await ComparisonService(session, storage).comparison(
                command_experiment.experiment_id,
                user.id,
            )
            assert command_comparison.runs[0].parse_status == ParseStatus.SUCCEEDED
            assert command_comparison.runs[0].text.startswith("uv ")

        class FailingDeidentifier:
            async def deidentify(self, **_: object):
                raise AppError("FASOO_EXECUTION_FAILED", "Synthetic Fasoo failure.")

        monkeypatch.setattr(
            "app.task_manager.pipeline.get_deidentifier_adapter",
            lambda _settings: FailingDeidentifier(),
        )
        async with session_factory() as session:
            failed_deidentification_experiment = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).create(
                ExperimentCreate(
                    name="Independent deidentification failure",
                    document_id=document.id,
                    run_deidentification=True,
                    parser_runs=[
                        ParserRunCreate(parser_connector_id=parsers[0].id),
                    ],
                ),
                user.id,
            )

        await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001
        async with session_factory() as session:
            failed_comparison = await ComparisonService(session, storage).comparison(
                failed_deidentification_experiment.experiment_id,
                user.id,
            )
            failed_run = failed_comparison.runs[0]
            assert failed_run.parse_status == ParseStatus.SUCCEEDED
            assert failed_run.deidentification_status == DeidentificationStatus.FAILED
            assert failed_run.deidentification is not None
            assert failed_run.deidentification.error_message == "Synthetic Fasoo failure."

        monkeypatch.setattr(
            "app.task_manager.pipeline.get_deidentifier_adapter",
            lambda _settings: MockDeidentifierAdapter(),
        )
        async with session_factory() as session:
            retried_run = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).retry(failed_run.run_id, user.id)
            assert retried_run.deidentification_status == DeidentificationStatus.PENDING

        await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001
        async with session_factory() as session:
            retried_comparison = await ComparisonService(session, storage).comparison(
                failed_deidentification_experiment.experiment_id,
                user.id,
            )
            assert (
                retried_comparison.runs[0].deidentification_status
                == DeidentificationStatus.SUCCEEDED
            )

        # 성공 상태만 남고 Parser 산출물이 비어 있으면 Fasoo만 반복하지 않고
        # Parsing부터 재실행하며 기존 RunResult를 중복 생성하지 않는다.
        async with session_factory() as session:
            empty_run = await session.get(ExperimentRun, failed_run.run_id)
            parser_result = await session.scalar(
                select(RunResult).where(RunResult.run_id == failed_run.run_id)
            )
            assert empty_run is not None
            assert parser_result is not None
            storage.resolve(parser_result.text_path).write_text("", encoding="utf-8")
            empty_run.deidentification_status = DeidentificationStatus.FAILED
            await session.commit()

            reparsed_run = await ExperimentService(
                session,
                session_factory,
                storage,
                manager,
            ).retry(failed_run.run_id, user.id)
            assert reparsed_run.parse_status == ParseStatus.PENDING
            assert reparsed_run.deidentification_status == DeidentificationStatus.PENDING

        await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001
        async with session_factory() as session:
            reparsed_run = await session.get(ExperimentRun, failed_run.run_id)
            parser_results = list(
                await session.scalars(
                    select(RunResult).where(RunResult.run_id == failed_run.run_id)
                )
            )
            assert reparsed_run is not None
            assert reparsed_run.parse_status == ParseStatus.SUCCEEDED
            assert reparsed_run.deidentification_status == DeidentificationStatus.SUCCEEDED
            assert len(parser_results) == 1
            assert storage.resolve(parser_results[0].text_path).stat().st_size > 0
    finally:
        await manager.shutdown()
        await engine.dispose()
