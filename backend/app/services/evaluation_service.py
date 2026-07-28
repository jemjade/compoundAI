"""사용자 범위의 수동 평가와 선호 Run Workflow."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.models.evaluation import ManualEvaluation
from app.db.models.experiment import Experiment, ExperimentRun
from app.schemas.evaluation import EvaluationUpsert


class EvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _authorize(self, run_id: UUID, user_id: UUID) -> ExperimentRun:
        run = await self.session.get(ExperimentRun, run_id)
        if run is None:
            raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
        experiment = await self.session.scalar(
            select(Experiment).where(
                Experiment.id == run.experiment_id,
                Experiment.created_by == user_id,
            )
        )
        if experiment is None:
            raise AppError("RUN_NOT_FOUND", "Run not found.", 404)
        return run

    async def get(self, run_id: UUID, user_id: UUID) -> ManualEvaluation | None:
        await self._authorize(run_id, user_id)
        return await self.session.scalar(
            select(ManualEvaluation).where(
                ManualEvaluation.run_id == run_id,
                ManualEvaluation.evaluator_id == user_id,
            )
        )

    async def upsert(
        self,
        run_id: UUID,
        user_id: UUID,
        data: EvaluationUpsert,
    ) -> ManualEvaluation:
        run = await self._authorize(run_id, user_id)
        if data.is_preferred:
            # 선호 결과는 사용자 범위이며 하나의 실험 안에서 한 개만 허용한다.
            experiment_run_ids = select(ExperimentRun.id).where(
                ExperimentRun.experiment_id == run.experiment_id
            )
            await self.session.execute(
                update(ManualEvaluation)
                .where(
                    ManualEvaluation.evaluator_id == user_id,
                    ManualEvaluation.run_id.in_(experiment_run_ids),
                )
                .values(is_preferred=False)
            )
        evaluation = await self.session.scalar(
            select(ManualEvaluation).where(
                ManualEvaluation.run_id == run_id,
                ManualEvaluation.evaluator_id == user_id,
            )
        )
        if evaluation is None:
            evaluation = ManualEvaluation(
                run_id=run_id,
                evaluator_id=user_id,
                **data.model_dump(),
            )
            self.session.add(evaluation)
        else:
            for key, value in data.model_dump().items():
                setattr(evaluation, key, value)
        await self.session.commit()
        return evaluation
