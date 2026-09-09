"""Run the frozen v1.4 source pages through real open-source parser adapters.

This command is intentionally page-scoped.  The selected pages are oracle evidence for a
development diagnostic, not a measurement of end-to-end retrieval performance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from pypdf import PdfReader, PdfWriter

from research.pilot import sha256, write_json

SPEC_STATUS = "FROZEN_DEVELOPMENT_DIAGNOSTIC"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _source_pdf(source_dir: Path, document_id: str) -> Path:
    path = source_dir / f"{document_id}.pdf"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _remap_single_page(canonical: dict[str, Any], source_page: int) -> dict[str, Any]:
    pages = canonical.get("pages")
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError(
            "PP-StructureV3 page extraction must normalize to exactly one page"
        )
    page = pages[0]
    old_page = page["page_number"]
    page["page_number"] = source_page
    for block in page.get("blocks", []):
        old_id = block["id"]
        block["id"] = f"source-p{source_page}:{old_id}"
        block["page_number"] = source_page
        for cell in block.get("cells", []):
            if cell.get("id"):
                cell["id"] = f"source-p{source_page}:{cell['id']}"
    canonical.setdefault("metadata", {})["page_remapping"] = {
        "single_page_pdf_page": old_page,
        "source_pdf_page": source_page,
    }
    return canonical


def _split_page(source: Path, page: int, destination: Path) -> None:
    reader = PdfReader(source)
    if page < 1 or page > len(reader.pages):
        raise ValueError(f"Page {page} is outside {source.name}")
    writer = PdfWriter()
    writer.add_page(reader.pages[page - 1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        writer.write(stream)


async def _run_docling(
    *, source: Path, document_id: str, page: int, output: Path, executable: Path
) -> dict[str, Any]:
    from app.adapters.parsers.docling_command import DoclingCommandAdapter

    page_out = output / "parser-output" / f"{document_id}-p{page}"
    page_out.mkdir(parents=True)
    connector = SimpleNamespace(
        name="docling",
        model_version="2.126.0",
        timeout_seconds=900,
        command_template=[
            str(executable),
            "convert",
            "{input_path}",
            "--from",
            "pdf",
            "--to",
            "json",
            "--to",
            "md",
            "--output",
            "{output_dir}",
            "--page-range",
            str(page),
            "--device",
            "cpu",
            "--no-ocr",
            "--table-mode",
            "accurate",
        ],
    )
    adapter = DoclingCommandAdapter(connector)
    result = await adapter.parse(source, page_out, {"source_page": page})
    run_id = f"docling-v1_4-{uuid4()}"
    canonical = await adapter.normalize(result, document_id, run_id)
    raw_path = output / "raw" / f"{document_id}-p{page}.json"
    canonical_path = output / "canonical" / f"{document_id}-p{page}.json"
    write_json(raw_path, result.raw_data)
    write_json(canonical_path, canonical.model_dump(mode="json"))
    return {
        "document_id": document_id,
        "source_page": page,
        "status": "VERIFIED",
        "execution": "actual_docling_command_adapter",
        "run_id": run_id,
        "metrics": result.metrics,
        "raw_path": str(raw_path),
        "raw_sha256": sha256(raw_path.read_bytes()),
        "canonical_path": str(canonical_path),
        "canonical_sha256": sha256(canonical_path.read_bytes()),
        "block_count": sum(len(item.blocks) for item in canonical.pages),
        "table_count": sum(
            block.type == "table" for item in canonical.pages for block in item.blocks
        ),
        "cell_count": sum(
            len(block.cells) for item in canonical.pages for block in item.blocks
        ),
    }


async def _run_paddle(
    *, source: Path, document_id: str, page: int, output: Path, cache: Path
) -> dict[str, Any]:
    from app.adapters.parsers.paddle_structure import (
        PPStructureRuntime,
        PPStructureV3Adapter,
    )
    from app.core.config import Settings

    input_path = output / "inputs" / f"{document_id}-p{page}.pdf"
    _split_page(source, page, input_path)
    settings = Settings(
        paddleocr_enabled=True,
        paddleocr_device="cpu",
        paddleocr_max_concurrency=1,
        paddleocr_model_cache_dir=cache,
    )
    runtime = PPStructureRuntime(settings)
    connector = SimpleNamespace(name="pp_structure_v3", model_version="3.7.0")
    adapter = PPStructureV3Adapter(connector, settings=settings, runtime=runtime)
    result = await adapter.parse(input_path, output, {})
    run_id = f"pp-structure-v3-v1_4-{uuid4()}"
    canonical = await adapter.normalize(result, document_id, run_id)
    value = _remap_single_page(canonical.model_dump(mode="json"), page)
    raw_path = output / "raw" / f"{document_id}-p{page}.json"
    canonical_path = output / "canonical" / f"{document_id}-p{page}.json"
    write_json(raw_path, result.raw_data)
    write_json(canonical_path, value)
    blocks = value["pages"][0].get("blocks", [])
    return {
        "document_id": document_id,
        "source_page": page,
        "status": "VERIFIED",
        "execution": "actual_pp_structure_v3_runtime_adapter",
        "run_id": run_id,
        "metrics": result.metrics,
        "raw_path": str(raw_path),
        "raw_sha256": sha256(raw_path.read_bytes()),
        "canonical_path": str(canonical_path),
        "canonical_sha256": sha256(canonical_path.read_bytes()),
        "block_count": len(blocks),
        "table_count": sum(item.get("type") == "table" for item in blocks),
        "cell_count": sum(len(item.get("cells", [])) for item in blocks),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output.exists():
        raise ValueError("Output directory exists; parser runs are append-only")
    spec = _load(args.spec)
    if (
        spec.get("status") != SPEC_STATUS
        or spec.get("frozen_before_comparison_run") is not True
    ):
        raise ValueError("v1.4 spec is not frozen")
    args.output.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "parser": args.parser,
        "scope": "oracle_source_pages_development_diagnostic",
        "spec_sha256": sha256(args.spec.read_bytes()),
        "platform": platform.platform(),
        "python": sys.version,
        "results": [],
        "failures": [],
    }
    write_json(args.output / "manifest.json", manifest)
    expected = {
        row["document_id"]: (row["pdf_sha256"], row["pages"])
        for row in spec["source_pages"]
    }
    for document_id, (expected_hash, pages) in expected.items():
        source = _source_pdf(args.source_dir, document_id)
        if sha256(source.read_bytes()) != expected_hash:
            raise ValueError(f"Frozen PDF hash mismatch: {document_id}")
        for page in pages:
            try:
                if args.parser == "docling":
                    row = await _run_docling(
                        source=source,
                        document_id=document_id,
                        page=page,
                        output=args.output,
                        executable=args.docling_executable,
                    )
                else:
                    row = await _run_paddle(
                        source=source,
                        document_id=document_id,
                        page=page,
                        output=args.output,
                        cache=args.paddle_cache,
                    )
                manifest["results"].append(row)
            except Exception as error:  # noqa: BLE001 - preserve each actual parser failure
                failure = {
                    "document_id": document_id,
                    "source_page": page,
                    "status": "BLOCKED",
                    "failure_type": type(error).__name__,
                    "failure_message": str(error),
                }
                manifest["failures"].append(failure)
            write_json(args.output / "manifest.json", manifest)
    manifest["status"] = (
        "complete_with_failures" if manifest["failures"] else "complete"
    )
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    manifest["verified_page_count"] = len(manifest["results"])
    manifest["failed_page_count"] = len(manifest["failures"])
    if args.parser == "docling":
        process = await asyncio.create_subprocess_exec(
            str(args.docling_executable),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await process.communicate()
        manifest["command_identity"] = stdout.decode(errors="replace").strip()
    else:
        manifest["command_identity"] = (
            "paddleocr=3.7.0;paddlepaddle=3.3.1;paddlex=3.7.2"
        )
    write_json(args.output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parser", choices=("docling", "pp-structure-v3"), required=True
    )
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--docling-executable",
        type=Path,
        default=Path("/private/tmp/compoundai-docling-v1_4/bin/docling"),
    )
    parser.add_argument(
        "--paddle-cache",
        type=Path,
        default=Path("research/work/model-cache/paddlex-v1_4"),
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
