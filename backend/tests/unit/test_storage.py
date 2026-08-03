"""안전한 문서 경로, 파일 검증, 산출물 영속성을 확인한다."""

import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from app.adapters.deidentifiers.base import DeidentificationExecutionResult
from app.adapters.parsers.base import ParserArtifact, ParserExecutionResult
from app.core.exceptions import AppError
from app.schemas.canonical_document import CanonicalDocument
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


async def test_storage_preserves_and_safely_expands_vendor_zip(tmp_path: Path) -> None:
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("output.md", "# 결과")
        archive.writestr("output.xml", "<document />")
        archive.writestr("output.tex", r"\section{결과}")
        archive.writestr("pages/page-1.json", '{"text":"결과"}')
    storage = StorageService(tmp_path, 1024)
    run_id = uuid4()
    canonical = CanonicalDocument(
        document_id="document",
        run_id=str(run_id),
        parser_name="Synap",
        full_text="결과",
    )

    paths = await storage.save_parser_results(
        run_id,
        ParserExecutionResult(
            raw_data={"result": {}},
            text="결과",
            artifacts=[
                ParserArtifact(
                    name="synap-result.zip",
                    media_type="application/zip",
                    content=archive_buffer.getvalue(),
                    source="synap_archive_response",
                )
            ],
        ),
        canonical,
    )

    names = {item["name"] for item in paths["artifact_manifest"]}
    assert names == {
        "synap-result.zip",
        "extracted/output.md",
        "extracted/output.xml",
        "extracted/output.tex",
        "extracted/pages/page-1.json",
    }
    tex_entry = next(
        item for item in paths["artifact_manifest"] if item["name"] == "extracted/output.tex"
    )
    assert storage.resolve(tex_entry["path"]).read_text(encoding="utf-8") == r"\section{결과}"
