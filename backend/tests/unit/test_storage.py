"""안전한 문서 경로, 파일 검증, 산출물 영속성을 확인한다."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.adapters.deidentifiers.base import DeidentificationExecutionResult
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


async def test_storage_accepts_png_upload(tmp_path: Path) -> None:
    storage = StorageService(tmp_path, 1024)
    upload = UploadFile(
        BytesIO(b"\x89PNG\r\n\x1a\nsynthetic"),
        filename="scan.png",
        headers=Headers({"content-type": "image/png"}),
    )

    stored = await storage.save_document(uuid4(), upload)

    assert stored["extension"] == "png"
    assert storage.resolve(stored["storage_path"]).read_bytes().startswith(b"\x89PNG")


async def test_storage_rejects_empty_upload(tmp_path: Path) -> None:
    storage = StorageService(tmp_path, 1024)
    upload = UploadFile(
        BytesIO(b""),
        filename="empty.png",
        headers=Headers({"content-type": "image/png"}),
    )

    with pytest.raises(AppError) as caught:
        await storage.save_document(uuid4(), upload)

    assert caught.value.code == "INVALID_INPUT_FILE"


async def test_storage_copies_masked_file_as_run_artifact(tmp_path: Path) -> None:
    storage = StorageService(tmp_path / "data", 1024)
    masked_source = tmp_path / "nas" / "masked.xlsx"
    masked_source.parent.mkdir()
    masked_source.write_bytes(b"masked spreadsheet")
    run_id = uuid4()

    paths = await storage.save_deidentification_result(
        run_id,
        DeidentificationExecutionResult(
            provider="FASOO",
            deidentified_text="",
            raw_data={"result": {}},
            masked_file_path=masked_source,
        ),
    )

    assert paths["result_path"] == f"runs/{run_id}/deidentified.json"
    assert paths["masked_file_path"] == f"runs/{run_id}/masked.xlsx"
    assert storage.resolve(paths["masked_file_path"]).read_bytes() == b"masked spreadsheet"
    stored_json = storage.resolve(paths["result_path"]).read_text(encoding="utf-8")
    assert str(masked_source) not in stored_json
