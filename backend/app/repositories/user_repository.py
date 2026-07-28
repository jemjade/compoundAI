"""사용자 조회·개수 계산·초기 역할 설정 Query."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(User)) or 0

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email.lower()))

    async def create(
        self,
        email: str,
        password_hash: str,
        name: str,
        role: UserRole,
    ) -> User:
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            name=name,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        return user
