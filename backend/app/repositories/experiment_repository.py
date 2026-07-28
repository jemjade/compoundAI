"""실험 소유권·목록·하위 Run Query."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.experiment import Experiment, ExperimentRun


class ExperimentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_owned(self, experiment_id: UUID, user_id: UUID) -> Experiment | None:
        return await self.session.scalar(
            select(Experiment).where(
                Experiment.id == experiment_id,
                Experiment.created_by == user_id,
            )
        )

    async def list_owned(self, user_id: UUID) -> list[Experiment]:
        result = await self.session.scalars(
            select(Experiment)
            .where(Experiment.created_by == user_id)
            .order_by(Experiment.created_at.desc())
        )
        return list(result)

    async def list_runs(self, experiment_id: UUID) -> list[ExperimentRun]:
        result = await self.session.scalars(
            select(ExperimentRun)
            .where(ExperimentRun.experiment_id == experiment_id)
            .order_by(ExperimentRun.created_at)
        )
        return list(result)
