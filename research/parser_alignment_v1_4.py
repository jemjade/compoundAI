"""Coordinate-align Docling and PP-StructureV3 cells without assigning error probability."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from research.pilot import sha256, write_json


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _normalized_box(
    bbox: Any, width: Any, height: Any, origin: str | None
) -> tuple[float, float, float, float] | None:
    if (
        not isinstance(bbox, dict)
        or not isinstance(width, (int, float))
        or not isinstance(height, (int, float))
        or width <= 0
        or height <= 0
    ):
        return None
    values = [bbox.get(key) for key in ("x1", "y1", "x2", "y2")]
    if not all(isinstance(value, (int, float)) for value in values):
        return None
    x1, y1, x2, y2 = (float(value) for value in values)
    if origin == "BOTTOMLEFT":
        y1, y2 = float(height) - y2, float(height) - y1
    return (
        min(x1, x2) / width,
        min(y1, y2) / height,
        max(x1, x2) / width,
        max(y1, y2) / height,
    )


def _iou(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_first = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_second = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_first + area_second - intersection
    return intersection / union if union else 0.0


def _flat_cells(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            for cell in block.get("cells", []):
                origin = cell.get("attributes", {}).get("coordinate_origin")
                rows.append(
                    {
                        "parser": document.get("parser_name"),
                        "page_number": page.get("page_number"),
                        "table_id": block.get("id"),
                        "cell_id": cell.get("id"),
                        "row": cell.get("row"),
                        "column": cell.get("column"),
                        "text": cell.get("text", ""),
                        "normalized_bbox": _normalized_box(
                            cell.get("bbox"),
                            page.get("width"),
                            page.get("height"),
                            origin,
                        ),
                        "coordinate_source": cell.get("attributes", {}).get(
                            "coordinate_source"
                        ),
                        "coordinate_alignment_verified": cell.get("attributes", {}).get(
                            "coordinate_alignment_verified"
                        ),
                    }
                )
    return rows


def _compact(value: str) -> str:
    return "".join(re.findall(r"[0-9A-Za-z]+", value)).lower()


def align_page(docling: dict[str, Any], paddle: dict[str, Any]) -> dict[str, Any]:
    left = _flat_cells(docling)
    right = _flat_cells(paddle)
    matches = []
    used: set[int] = set()
    for cell in left:
        if cell["normalized_bbox"] is None:
            matches.append(
                {
                    "docling": cell,
                    "paddle": None,
                    "classification": "alignment_failure_missing_coordinate",
                    "iou": None,
                }
            )
            continue
        ranked = sorted(
            (
                (
                    _iou(cell["normalized_bbox"], candidate["normalized_bbox"]),
                    index,
                    candidate,
                )
                for index, candidate in enumerate(right)
                if index not in used and candidate["normalized_bbox"] is not None
            ),
            reverse=True,
            key=lambda item: item[0],
        )
        if not ranked or ranked[0][0] < 0.05:
            matches.append(
                {
                    "docling": cell,
                    "paddle": None,
                    "classification": "alignment_failure_no_spatial_match",
                    "iou": ranked[0][0] if ranked else None,
                }
            )
            continue
        score, index, candidate = ranked[0]
        used.add(index)
        left_text, right_text = (
            str(cell["text"]).strip(),
            str(candidate["text"]).strip(),
        )
        if left_text == right_text:
            classification = "exact_text_agreement"
        elif _compact(left_text) == _compact(right_text):
            classification = "token_or_whitespace_difference"
        else:
            classification = "parser_content_disagreement_not_gold_labeled"
        matches.append(
            {
                "docling": cell,
                "paddle": candidate,
                "classification": classification,
                "iou": score,
            }
        )
    unmatched_paddle = [cell for index, cell in enumerate(right) if index not in used]
    counts = Counter(row["classification"] for row in matches)
    return {
        "document_id": docling["document_id"],
        "page_number": docling["pages"][0]["page_number"],
        "docling_cell_count": len(left),
        "paddle_cell_count": len(right),
        "classification_counts": dict(counts),
        "unmatched_paddle_cell_count": len(unmatched_paddle),
        "matches": matches,
        "unmatched_paddle_cells": unmatched_paddle,
        "interpretation": "coordinate alignment diagnostic only; disagreement and agreement are not error probabilities or gold correctness",
        "paddle_coordinate_limit": "cell_box_list is paired to HTML cells sequentially and remains coordinate_alignment_verified=false",
    }


def run(docling_dir: Path, paddle_dir: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError("Alignment output exists; use a new path")
    pages = []
    for docling_path in sorted((docling_dir / "canonical").glob("*.json")):
        paddle_path = paddle_dir / "canonical" / docling_path.name
        if not paddle_path.is_file():
            pages.append(
                {
                    "file": docling_path.name,
                    "status": "BLOCKED",
                    "reason": "PP-StructureV3 canonical page missing",
                }
            )
            continue
        pages.append(
            {
                "status": "VERIFIED",
                **align_page(_load(docling_path), _load(paddle_path)),
            }
        )
    result = {
        "schema_version": 1,
        "status": "DEVELOPMENT_ALIGNMENT_DIAGNOSTIC",
        "docling_manifest_sha256": sha256((docling_dir / "manifest.json").read_bytes()),
        "paddle_manifest_sha256": sha256((paddle_dir / "manifest.json").read_bytes()),
        "pages": pages,
        "artificial_error_category": "not part of parser alignment; AMD A/B are post-parse controlled mutations recorded by the QA runner",
        "probability_use": "PROHIBITED; raw count differences are not candidate error probabilities",
    }
    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docling-dir", type=Path, required=True)
    parser.add_argument("--paddle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.docling_dir, args.paddle_dir, args.output),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
