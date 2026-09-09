"""Convert a backend CanonicalDocument JSON snapshot to research input JSONL files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from research.pilot import digest, read_jsonl, sha256, write_json, write_jsonl


def canonical_to_blocks(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    required = ("document_id", "run_id", "parser_name", "pages")
    if any(key not in canonical for key in required):
        raise ValueError("CanonicalDocument is missing identity or pages")
    if not all(isinstance(canonical[key], str) for key in required[:-1]):
        raise ValueError("CanonicalDocument identity fields must be strings")
    if not isinstance(canonical["pages"], list):
        raise ValueError("CanonicalDocument pages must be an array")
    blocks: list[dict[str, Any]] = []
    for page in canonical["pages"]:
        if not isinstance(page, dict) or type(page.get("page_number")) is not int:
            raise ValueError("CanonicalDocument contains an invalid page")
        page_number = page["page_number"]
        if page_number < 1:
            raise ValueError("CanonicalDocument page_number must be positive")
        page_blocks = page.get("blocks", [])
        if not isinstance(page_blocks, list):
            raise ValueError("CanonicalDocument page blocks must be an array")
        if not page_blocks and isinstance(page.get("text"), str) and page["text"]:
            page_blocks = [
                {
                    "id": (
                        f"{canonical['document_id']}:{canonical['run_id']}:"
                        f"page-{page_number}-text"
                    ),
                    "type": "unknown",
                    "page_number": page_number,
                    "text": page["text"],
                    "reading_order": None,
                    "bbox": None,
                }
            ]
        for block in page_blocks:
            if not isinstance(block, dict) or not isinstance(block.get("id"), str):
                raise ValueError("CanonicalDocument block IDs must be strings")
            if not isinstance(block.get("text", ""), str):
                raise ValueError("CanonicalDocument block text must be a string")
            if type(block.get("page_number")) is not int:
                raise ValueError("CanonicalDocument block page_number must be an integer")
            if block["page_number"] != page_number:
                raise ValueError("CanonicalDocument block/page relationship is inconsistent")
            blocks.append(
                {
                    "block_id": block["id"],
                    "canonical_block_id": block["id"],
                    "document_id": canonical["document_id"],
                    "run_id": canonical["run_id"],
                    "page_number": page_number,
                    "text": block.get("text", ""),
                    "source_kind": "canonical_parser",
                    "block_type": block.get("type", "unknown"),
                    "reading_order": block.get("reading_order"),
                    "bbox": block.get("bbox"),
                    "parser_name": canonical["parser_name"],
                    "parser_version": canonical.get("parser_version"),
                    "page_width": page.get("width"),
                    "page_height": page.get("height"),
                    "html": block.get("html"),
                    "cells": block.get("cells", []),
                    "attributes": block.get("attributes", {}),
                }
            )
    ids = [block["block_id"] for block in blocks]
    if not blocks or len(ids) != len(set(ids)):
        raise ValueError("CanonicalDocument needs nonempty, unique block IDs")
    return blocks


def convert(canonical_path: Path, questions_path: Path, out: Path) -> dict[str, Any]:
    if out.exists():
        raise ValueError("Output already exists; use a new snapshot path")
    canonical_bytes = canonical_path.read_bytes()
    canonical = json.loads(canonical_bytes)
    if not isinstance(canonical, dict):
        raise ValueError("CanonicalDocument JSON must be an object")
    blocks = canonical_to_blocks(canonical)
    questions = read_jsonl(questions_path)
    allowed_question_keys = ("question_id", "document_id", "question")
    clean_questions = []
    for question in questions:
        if not set(allowed_question_keys) <= set(question):
            raise ValueError("Question input is missing an ID, document ID, or question")
        if question["document_id"] != canonical["document_id"]:
            continue
        clean_questions.append({key: question[key] for key in allowed_question_keys})
    if not clean_questions:
        raise ValueError("No questions match the CanonicalDocument document_id")
    manifest = {
        "schema_version": 1,
        "source_kind": "canonical_parser",
        "document_id": canonical["document_id"],
        "run_id": canonical["run_id"],
        "parser_name": canonical["parser_name"],
        "parser_version": canonical.get("parser_version"),
        "canonical_sha256": sha256(canonical_bytes),
        "block_count": len(blocks),
        "question_count": len(clean_questions),
        "inputs_sha256": digest({"blocks": blocks, "questions": clean_questions}),
        "note": "Actual parser CanonicalDocument; not the pypdf page-text baseline.",
    }
    out.mkdir(parents=True)
    write_jsonl(out / "inputs/blocks.jsonl", blocks)
    write_jsonl(out / "inputs/questions.jsonl", clean_questions)
    write_json(out / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            convert(args.canonical, args.questions, args.out),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"Canonical conversion stopped: {error}", file=__import__("sys").stderr)
        raise SystemExit(1) from error
