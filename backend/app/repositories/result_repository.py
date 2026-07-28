"""Parser 결과 메타데이터 조회 Query."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.result import RunResult


class ResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_run(self, run_id: UUID) -> RunResult | None:
        return await self.session.scalar(select(RunResult).where(RunResult.run_id == run_id))
