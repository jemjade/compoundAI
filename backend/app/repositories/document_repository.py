"""소유 문서 조회 및 목록 Query."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, metadata: dict, user_id: UUID, document_id: UUID) -> Document:
        document = Document(id=document_id, uploaded_by=user_id, **metadata)
        self.session.add(document)
        await self.session.flush()
        return document

    async def get_owned(self, document_id: UUID, user_id: UUID) -> Document | None:
        return await self.session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.uploaded_by == user_id,
            )
        )

    async def list_owned(self, user_id: UUID) -> list[Document]:
        result = await self.session.scalars(
            select(Document)
            .where(Document.uploaded_by == user_id)
            .order_by(Document.created_at.desc())
        )
        return list(result)
