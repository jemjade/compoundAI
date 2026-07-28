"""인증된 문서 업로드·목록·다운로드·삭제 Endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, UploadFile, status
from fastapi.responses import FileResponse

from app.api.dependencies import CurrentUser, SessionDep, StorageDep
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentResponse
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    document = await DocumentService(session, storage).upload(file, user.id)
    return DocumentResponse.model_validate(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(user: CurrentUser, session: SessionDep) -> list[DocumentResponse]:
    documents = await DocumentRepository(session).list_owned(user.id)
    return [DocumentResponse.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> DocumentResponse:
    document = await DocumentService(session, storage).get(document_id, user.id)
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download", response_class=FileResponse)
async def download_document(
    document_id: UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
) -> FileResponse:
    document = await DocumentService(session, storage).get(document_id, user.id)
    return FileResponse(
        storage.resolve(document.storage_path),
        media_type=document.mime_type,
        filename=document.original_filename,
    )
