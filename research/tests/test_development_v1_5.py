import json
from pathlib import Path

import pytest

from research.development_v1_5 import _validate_gate


def test_failed_semantic_audit_cannot_open_repair_gate(tmp_path: Path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "manifest.json").write_text(
        json.dumps({"status": "complete", "cumulative_v1_5_model_calls": 2})
    )
    (clean / "records.jsonl").write_text(
        json.dumps(
            {
                "condition": "amd_clean",
                "status": "completed",
                "question_id": "financebench_id_00222",
            }
        )
        + "\n"
    )
    gate = tmp_path / "gate.json"
    gate.write_text(
        json.dumps(
            {
                "status": "SOURCE_AUDITED_FAIL",
                "question_id": "financebench_id_00222",
                "dimensions": {},
            }
        )
    )
    with pytest.raises(ValueError, match="did not pass"):
        _validate_gate(clean, gate)
