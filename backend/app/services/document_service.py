"""문서 검증·저장·소유권·목록·삭제 Workflow."""

from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.db.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.services.storage_service import StorageService


class DocumentService:
    def __init__(self, session: AsyncSession, storage: StorageService) -> None:
        self.session = session
        self.storage = storage
        self.documents = DocumentRepository(session)

    async def upload(self, file: UploadFile, user_id: UUID) -> Document:
        document_id = uuid4()
        metadata = await self.storage.save_document(document_id, file)
        try:
            document = await self.documents.create(metadata, user_id, document_id)
            await self.session.commit()
            return document
        except Exception:
            path = self.storage.resolve(metadata["storage_path"])
            if path.exists():
                path.unlink()
            raise

    async def get(self, document_id: UUID, user_id: UUID) -> Document:
        document = await self.documents.get_owned(document_id, user_id)
        if document is None:
            raise AppError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        return document
