"""안전한 문서 경로, 파일 검증, 산출물 영속성을 확인한다."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.core.exceptions import AppError
from app.services.storage_service import StorageService


def test_storage_rejects_path_outside_root(tmp_path: Path) -> None:
    storage = StorageService(tmp_path, 1024)

    with pytest.raises(AppError, match="escaped"):
        storage.resolve("../secret.txt")


async def test_storage_rejects_mime_extension_mismatch(tmp_path: Path) -> None:
    storage = StorageService(tmp_path, 1024)
    upload = UploadFile(
        BytesIO(b"<html>not a pdf</html>"),
        filename="fake.pdf",
        headers=Headers({"content-type": "text/html"}),
    )

    with pytest.raises(AppError, match="does not match"):
        await storage.save_document(uuid4(), upload)
