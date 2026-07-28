"""경로 이탈을 방지하는 문서 및 Run 산출물 로컬 저장소."""

import asyncio
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import UploadFile

from app.adapters.deidentifiers.base import DeidentificationExecutionResult
from app.adapters.parsers.base import ParserExecutionResult
from app.core.exceptions import AppError
from app.schemas.canonical_document import CanonicalDocument

ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "txt",
    "md",
    "png",
    "jpg",
    "jpeg",
    "webp",
}
MIME_BY_EXTENSION = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    "pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/zip",
    },
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    },
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
}
CHUNK_SIZE = 1024 * 1024


class StorageService:
    def __init__(self, data_root: Path, max_upload_size_bytes: int) -> None:
        self.data_root = data_root.resolve()
        self.max_upload_size_bytes = max_upload_size_bytes

    def _safe_path(self, relative_path: str | Path) -> Path:
        """저장 경로를 해석하고 DATA_ROOT 외부로의 경로 이탈을 차단한다."""
        path = (self.data_root / relative_path).resolve()
        if path != self.data_root and self.data_root not in path.parents:
            raise AppError("INVALID_STORAGE_PATH", "Storage path escaped the configured root.")
        return path

    async def save_document(self, document_id: UUID, upload: UploadFile) -> dict[str, Any]:
        original_name = Path(upload.filename or "document").name
        original_name = re.sub(r"[^A-Za-z0-9가-힣._ -]", "_", original_name)[:500]
        extension = Path(original_name).suffix.lower().lstrip(".")
        if extension not in ALLOWED_EXTENSIONS:
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                f"Unsupported file extension: {extension or '(none)'}",
                status_code=415,
            )
        content_type = (upload.content_type or "application/octet-stream").split(";", 1)[0]
        if (
            content_type != "application/octet-stream"
            and content_type not in MIME_BY_EXTENSION[extension]
        ):
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                f"Content type {content_type} does not match .{extension}.",
                status_code=415,
            )

        relative_path = Path("documents") / str(document_id) / f"original.{extension}"
        target = self._safe_path(relative_path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with target.open("wb") as output:
                while chunk := await upload.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > self.max_upload_size_bytes:
                        raise AppError(
                            "UPLOAD_TOO_LARGE",
                            "The uploaded file exceeds the configured size limit.",
                            status_code=413,
                        )
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            if size == 0:
                raise AppError(
                    "INVALID_INPUT_FILE",
                    "The uploaded file is empty.",
                    status_code=422,
                )
        except Exception:
            if target.exists():
                await asyncio.to_thread(target.unlink)
            raise
        finally:
            await upload.close()

        return {
            "original_filename": original_name,
            "stored_filename": target.name,
            "mime_type": content_type,
            "extension": extension,
            "file_size": size,
            "sha256": digest.hexdigest(),
            "storage_path": relative_path.as_posix(),
        }

    def resolve(self, relative_path: str) -> Path:
        return self._safe_path(relative_path)

    async def create_run_directory(self, run_id: UUID) -> Path:
        path = self._safe_path(Path("runs") / str(run_id))
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        return path

    async def prepare_run_work_directory(self, run_id: UUID) -> Path:
        """하나의 Run 범위에서 깨끗한 일회성 작업 디렉터리를 만든다."""
        run_dir = await self.create_run_directory(run_id)
        work_dir = run_dir / "work"
        if work_dir.exists():
            await asyncio.to_thread(shutil.rmtree, work_dir)
        await asyncio.to_thread(work_dir.mkdir, parents=True, exist_ok=True)
        return work_dir

    async def cleanup_run_work_directory(self, work_dir: Path) -> None:
        """검증된 run/work 디렉터리만 삭제하고 상위 경로는 삭제하지 않는다."""
        safe_work_dir = self._safe_path(work_dir.relative_to(self.data_root))
        if safe_work_dir.name != "work":
            raise AppError("INVALID_STORAGE_PATH", "Only run work directories can be cleaned.")
        if safe_work_dir.exists():
            await asyncio.to_thread(shutil.rmtree, safe_work_dir)

    async def save_parser_results(
        self,
        run_id: UUID,
        execution_result: ParserExecutionResult,
        canonical_document: CanonicalDocument,
    ) -> dict[str, str]:
        """큰 Parser 산출물을 PostgreSQL 외부에 저장하고 상대 경로를 반환한다."""
        output_dir = await self.create_run_directory(run_id)
        raw_path = output_dir / "raw.json"
        canonical_path = output_dir / "canonical.json"
        markdown_path = output_dir / "output.md"
        text_path = output_dir / "output.txt"

        def write_results() -> None:
            raw_path.write_text(
                json.dumps(execution_result.raw_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            canonical_path.write_text(
                canonical_document.model_dump_json(indent=2),
                encoding="utf-8",
            )
            markdown_path.write_text(execution_result.markdown or "", encoding="utf-8")
            text_path.write_text(execution_result.text or "", encoding="utf-8")

        await asyncio.to_thread(write_results)
        return {
            "raw_result_path": raw_path.relative_to(self.data_root).as_posix(),
            "canonical_result_path": canonical_path.relative_to(self.data_root).as_posix(),
            "markdown_path": markdown_path.relative_to(self.data_root).as_posix(),
            "text_path": text_path.relative_to(self.data_root).as_posix(),
        }

    async def read_text(self, relative_path: str | None) -> str | None:
        if relative_path is None:
            return None
        path = self._safe_path(relative_path)
        if not path.is_file():
            return None
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def save_deidentification_result(
        self,
        run_id: UUID,
        execution_result: DeidentificationExecutionResult,
    ) -> dict[str, str | None]:
        output_dir = await self.create_run_directory(run_id)
        result_path = output_dir / "deidentified.json"
        masked_path: Path | None = None
        if execution_result.masked_file_path is not None:
            source = execution_result.masked_file_path.resolve()
            if not source.is_file():
                raise AppError(
                    "FASOO_ARTIFACT_NOT_FOUND",
                    "Fasoo masked file is not available for storage.",
                )
            masked_path = output_dir / f"masked{source.suffix.lower()}"
            if source != masked_path.resolve():
                await asyncio.to_thread(shutil.copy2, source, masked_path)
        await asyncio.to_thread(
            result_path.write_text,
            execution_result.model_dump_json(indent=2),
            "utf-8",
        )
        return {
            "result_path": result_path.relative_to(self.data_root).as_posix(),
            "masked_file_path": (
                masked_path.relative_to(self.data_root).as_posix()
                if masked_path is not None
                else None
            ),
        }

    async def save_run_error(self, run_id: UUID, message: str) -> str:
        output_dir = await self.create_run_directory(run_id)
        error_path = output_dir / "error.log"
        await asyncio.to_thread(error_path.write_text, message[:4000], "utf-8")
        return error_path.relative_to(self.data_root).as_posix()
