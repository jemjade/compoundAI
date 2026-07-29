"""실험 생성·상태 계산·재실행·취소 Workflow."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import AppError
from app.db.models.document import Document
from app.db.models.experiment import (
    DeidentificationStatus,
    Experiment,
    ExperimentRun,
    ParseStatus,
)
from app.db.models.result import DeidentificationResult
from app.repositories.document_repository import DocumentRepository
from app.repositories.experiment_repository import ExperimentRepository
from app.repositories.parser_repository import ParserRepository
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentCreatedResponse,
    ExperimentCreatedRun,
    ExperimentDetail,
    ExperimentListItem,
    RunSummary,
)
from app.schemas.result import DeidentificationSummary
from app.services.storage_service import StorageService
from app.task_manager.manager import TaskManager
from app.task_manager.pipeline import execute_deidentification, execute_run
from app.utils.config import merge_config
from app.utils.config_validation import validate_parser_config


def calculate_experiment_status(runs: list[ExperimentRun]) -> str:
    """Parser 및 요청된 비식별화 단계에서 실험 상태를 계산한다."""
    statuses = [run.parse_status for run in runs]
    if not statuses or all(status == ParseStatus.PENDING for status in statuses):
        return "PENDING"
    if any(status in {ParseStatus.PENDING, ParseStatus.RUNNING} for status in statuses):
        return "RUNNING"
    succeeded = sum(status == ParseStatus.SUCCEEDED for status in statuses)
    if not succeeded:
        return "FAILED"
    deidentification_statuses = [
        getattr(
            run,
            "deidentification_status",
            DeidentificationStatus.NOT_REQUESTED,
        )
        for run in runs
        if run.parse_status == ParseStatus.SUCCEEDED
    ]
    if any(
        status in {DeidentificationStatus.PENDING, DeidentificationStatus.RUNNING}
        for status in deidentification_statuses
    ):
        return "RUNNING"
    if succeeded != len(statuses) or any(
        status in {DeidentificationStatus.FAILED, DeidentificationStatus.INTERRUPTED}
        for status in deidentification_statuses
    ):
        return "PARTIALLY_COMPLETED"
    return "COMPLETED"


class ExperimentService:
    def __init__(
        self,
        session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
        storage: StorageService,
        task_manager: TaskManager,
    ) -> None:
        self.session = session
        self.session_factory = session_factory
        self.storage = storage
        self.task_manager = task_manager
        self.experiments = ExperimentRepository(session)
        self.documents = DocumentRepository(session)
        self.parsers = ParserRepository(session)

    async def create(self, data: ExperimentCreate, user_id: UUID) -> ExperimentCreatedResponse:
        document = await self.documents.get_owned(data.document_id, user_id)
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        connector_ids = [item.parser_connector_id for item in data.parser_runs]
        if len(set(connector_ids)) != len(connector_ids):
            raise AppError(
                "DUPLICATE_PARSER",
                "Each parser connector can only be selected once per experiment.",
                422,
            )

        experiment = Experiment(
            name=data.name,
            description=data.description,
            document_id=document.id,
            run_deidentification=data.run_deidentification,
            created_by=user_id,
        )
        self.session.add(experiment)
        await self.session.flush()

        created_runs: list[ExperimentRun] = []
        for requested in data.parser_runs:
            connector = await self.parsers.get(requested.parser_connector_id)
            if connector is None:
                raise AppError("PARSER_NOT_FOUND", "Parser not found.", 404)
            if not connector.is_active:
                raise AppError("PARSER_DISABLED", f"{connector.name} is disabled.", 422)
            if document.extension not in connector.supported_formats:
                raise AppError(
                    "UNSUPPORTED_FILE_TYPE",
                    f"{connector.name} does not support .{document.extension}.",
                    422,
                )
            preset_config = None
            if requested.parser_preset_id:
                preset = await self.parsers.get_preset(requested.parser_preset_id)
                if preset is None or preset.parser_connector_id != connector.id:
                    raise AppError("PARSER_PRESET_NOT_FOUND", "Parser preset not found.", 404)
                preset_config = preset.config
            config_snapshot = merge_config(
                connector.default_config,
                preset_config,
                requested.config_override,
            )
            validate_parser_config(connector.config_schema, config_snapshot)
            run = ExperimentRun(
                experiment_id=experiment.id,
                document_id=document.id,
                parser_connector_id=connector.id,
                parser_preset_id=requested.parser_preset_id,
                parser_snapshot={
                    "name": connector.name,
                    "model_name": connector.model_name,
                    "model_version": connector.model_version,
                    "adapter_key": connector.adapter_key,
                    "execution_type": connector.execution_type.value,
                },
                config_snapshot=config_snapshot,
                parse_status=ParseStatus.PENDING,
                deidentification_status=(
                    DeidentificationStatus.PENDING
                    if data.run_deidentification
                    else DeidentificationStatus.NOT_REQUESTED
                ),
            )
            self.session.add(run)
            created_runs.append(run)

        await self.session.commit()
        for run in created_runs:
            self._submit(run.id)
        return ExperimentCreatedResponse(
            experiment_id=experiment.id,
            runs=[
                ExperimentCreatedRun(
                    run_id=run.id,
                    parser_name=run.parser_snapshot["name"],
                    parse_status=run.parse_status,
                )
                for run in created_runs
            ],
        )

    def _submit(self, run_id: UUID) -> None:
        self.task_manager.submit(
            run_id,
            lambda: execute_run(run_id, self.session_factory, self.storage),
        )

    def _submit_deidentification(self, run_id: UUID) -> None:
        self.task_manager.submit(
            run_id,
            lambda: execute_deidentification(
                run_id,
                self.session_factory,
                self.storage,
            ),
        )

    async def get(
        self,
        experiment_id: UUID,
        user_id: UUID,
    ) -> tuple[Experiment, Document, list[ExperimentRun]]:
        experiment = await self.experiments.get_owned(experiment_id, user_id)
        if experiment is None:
            raise AppError("EXPERIMENT_NOT_FOUND", "Experiment not found.", 404)
        document = await self.session.get(Document, experiment.document_id)
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "Experiment document not found.", 404)
        runs = await self.experiments.list_runs(experiment.id)
        return experiment, document, runs

    async def detail(self, experiment_id: UUID, user_id: UUID) -> ExperimentDetail:
        experiment, document, runs = await self.get(experiment_id, user_id)
        run_summaries = [await self._run_summary(run) for run in runs]
        return ExperimentDetail(
            id=experiment.id,
            name=experiment.name,
            description=experiment.description,
            document_id=document.id,
            document_filename=document.original_filename,
            run_deidentification=experiment.run_deidentification,
            created_at=experiment.created_at,
            status=calculate_experiment_status(runs),
            runs=run_summaries,
        )

    async def _run_summary(self, run: ExperimentRun) -> RunSummary:
        summary = RunSummary.model_validate(run)
        result = await self.session.scalar(
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

    async def list(self, user_id: UUID) -> list[ExperimentListItem]:
        items: list[ExperimentListItem] = []
        for experiment in await self.experiments.list_owned(user_id):
            document = await self.session.get(Document, experiment.document_id)
            runs = await self.experiments.list_runs(experiment.id)
            items.append(
                ExperimentListItem(
                    id=experiment.id,
                    name=experiment.name,
                    description=experiment.description,
                    document_id=experiment.document_id,
                    document_filename=document.original_filename if document else "삭제된 문서",
                    created_at=experiment.created_at,
                    status=calculate_experiment_status(runs),
                    run_count=len(runs),
                )
            )
        return items

    async def retry(self, run_id: UUID, user_id: UUID) -> ExperimentRun:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
        experiment = await self.experiments.get_owned(run.experiment_id, user_id)
        if experiment is None:
            raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
        retry_parse = run.parse_status in {
            ParseStatus.FAILED,
            ParseStatus.INTERRUPTED,
        }
        retry_deidentification = (
            run.parse_status == ParseStatus.SUCCEEDED
            and run.deidentification_status
            in {
                DeidentificationStatus.FAILED,
                DeidentificationStatus.INTERRUPTED,
            }
        )
        if not retry_parse and not retry_deidentification:
            raise AppError("RUN_NOT_RETRYABLE", "Only failed or interrupted runs can retry.", 409)
        if retry_parse:
            run.parse_status = ParseStatus.PENDING
            run.deidentification_status = (
                DeidentificationStatus.PENDING
                if experiment.run_deidentification
                else DeidentificationStatus.NOT_REQUESTED
            )
            run.error_code = None
            run.error_message = None
            run.started_at = None
            run.completed_at = None
            run.latency_ms = None
        else:
            # 후속 단계만 재실행할 때는 성공한 Parser 산출물을 재사용한다.
            run.deidentification_status = DeidentificationStatus.PENDING
            stored_result = await self.session.scalar(
                select(DeidentificationResult).where(DeidentificationResult.run_id == run.id)
            )
            if stored_result is not None:
                stored_result.error_message = None
                stored_result.metrics = {}
        await self.session.commit()
        if retry_parse:
            self._submit(run.id)
        else:
            self._submit_deidentification(run.id)
        return run

    async def cancel(self, run_id: UUID, user_id: UUID) -> ExperimentRun:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None or await self.experiments.get_owned(run.experiment_id, user_id) is None:
            raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
        parse_active = run.parse_status in {ParseStatus.PENDING, ParseStatus.RUNNING}
        deidentification_active = run.deidentification_status in {
            DeidentificationStatus.PENDING,
            DeidentificationStatus.RUNNING,
        }
        if not parse_active and not deidentification_active:
            raise AppError("RUN_NOT_RUNNING", "Run is not pending or running.", 409)
        self.task_manager.cancel(run.id)
        if parse_active:
            run.parse_status = ParseStatus.INTERRUPTED
            run.error_code = "TASK_CANCELLED"
            run.error_message = "Task was cancelled before completion."
        if deidentification_active:
            run.deidentification_status = DeidentificationStatus.INTERRUPTED
        await self.session.commit()
        return run
