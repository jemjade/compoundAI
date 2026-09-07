"""Build one reproducible, SOURCE-CHECKED synthetic corruption case; no model execution."""

import argparse
import json
from pathlib import Path

from research.pilot import digest, injected_case, read_jsonl, write_json


def build(dataset: Path, out: Path) -> dict:
    if out.exists():
        raise ValueError("Use a new output path")
    blocks = read_jsonl(dataset / "inputs/blocks.jsonl")
    questions = read_jsonl(dataset / "inputs/questions.jsonl")
    manifest = json.loads((dataset / "manifest.json").read_text())
    if digest({"blocks": blocks, "questions": questions}) != manifest["inputs_sha256"]:
        raise ValueError("Dataset inputs changed after preparation")
    document = "BOEING_2022_10K"
    blocks = [block for block in blocks if block["document_id"] == document]
    questions = [question for question in questions if question["document_id"] == document]
    page = next(block for block in blocks if block["block_id"] == f"{document}:p55")
    corruptions = []
    for name, correct, corrupted, label in [
        ("A", "66,608", "6,608", "2022 Total revenues"),
        ("B", "63,106", "6,106", "2022 Total costs and expenses; parentheses preserved"),
    ]:
        if page["text"].count(correct) != 1:
            raise ValueError("Expected one matching source span; inspect this PDF/parser version")
        start = page["text"].index(correct)
        corruptions.append(
            {
                "candidate_id": name,
                "block_id": page["block_id"],
                "start": start,
                "end": start + len(correct),
                "before": correct,
                "after": corrupted,
                "source_note": (
                    f"Controlled digit deletion in {label}. Correct span visually checked against "
                    "FinanceBench's Boeing 2022 10-K PDF, PDF page 55 / printed page 53, "
                    "on 2026-09-07. Not a naturally observed parser error. Other occurrences "
                    "of these facts remain in the full document."
                ),
            }
        )
    case = injected_case(
        {
            "schema_version": 1,
            "case_id": "boeing-digit-deletion-pilot-v1",
            "blocks": blocks,
            "questions": questions,
            "repairs": corruptions,
        }
    )
    case["selection_note"] = (
        "Debugging stress case: source locations chosen with knowledge of annotation evidence. "
        "This is not a blind allocation policy and cannot evaluate candidate-selection quality."
    )
    case["dataset_manifest_sha256"] = digest(manifest)
    write_json(out, case)
    return case


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    case = build(args.dataset, args.out)
    print(
        json.dumps(
            {
                "case_id": case["case_id"],
                "pages": len(case["blocks"]),
                "questions": len(case["questions"]),
                "status": "prepared_not_executed",
            }
        )
    )
