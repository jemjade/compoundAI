"""업로드 문서 응답 스키마."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    mime_type: str
    extension: str
    file_size: int
    sha256: str
    page_count: int | None
    uploaded_by: UUID
    created_at: datetime
