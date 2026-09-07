"""Method-critical checks. Toy outcomes here are not research results."""

import copy
import json
import subprocess
import sys

import pytest

from research.pilot import (
    CONDITIONS,
    digest,
    evidence_doc,
    injected_case,
    judgment_id,
    judgment_template,
    load_complete_run,
    repaired_blocks,
    run_case,
    runner_payload,
    score,
    select_questions,
    validate_case,
    validate_response,
    write_json,
    write_jsonl,
)


@pytest.fixture
def case():
    return {
        "schema_version": 1,
        "case_id": "TEST_ONLY",
        "blocks": [
            {
                "block_id": "d:p1",
                "document_id": "d",
                "page_number": 1,
                "text": "a=1 b=2",
                "reference_answer": "DO_NOT_SEND",
            }
        ],
        "questions": [
            {"question_id": "q1", "document_id": "d", "question": "A?", "answer": "DO_NOT_SEND"},
            {"question_id": "q2", "document_id": "d", "question": "B?"},
        ],
        "repairs": [
            {
                "candidate_id": "A",
                "block_id": "d:p1",
                "start": 2,
                "end": 3,
                "before": "1",
                "after": "100",
                "source_note": "Synthetic unit-test fixture",
            },
            {
                "candidate_id": "B",
                "block_id": "d:p1",
                "start": 6,
                "end": 7,
                "before": "2",
                "after": "200",
                "source_note": "Synthetic unit-test fixture",
            },
        ],
    }


def test_payload_never_includes_answer_keys_or_repair_targets(case):
    payload = runner_payload(case, (), 0)
    serialized = json.dumps(payload)
    assert "DO_NOT_SEND" not in serialized
    assert "repairs" not in serialized and "source_note" not in serialized
    assert "100" not in serialized and "200" not in serialized
    assert set(payload) == {"schema_version", "repeat_id", "blocks", "questions"}


def test_simultaneous_edits_use_original_offsets_and_preserve_base(case):
    before = copy.deepcopy(case)
    assert repaired_blocks(case, ("A", "B"))[0]["text"] == "a=100 b=200"
    assert repaired_blocks(case, ("B", "A"))[0]["text"] == "a=100 b=200"
    assert case == before


def test_injection_inverse_handles_length_changes(case):
    injected = injected_case(case)
    assert injected["blocks"][0]["text"] == "a=100 b=200"
    assert repaired_blocks(injected, ("A", "B"))[0]["text"] == "a=1 b=2"
    assert repaired_blocks(injected, ("B",))[0]["text"] == "a=100 b=2"


@pytest.mark.parametrize("defect", ["overlap", "stale", "duplicate", "cross_document"])
def test_invalid_interventions_fail_closed(case, defect):
    if defect == "overlap":
        case["repairs"][1].update(start=2, end=3, before="1")
    elif defect == "stale":
        case["repairs"][0]["before"] = "wrong"
    elif defect == "duplicate":
        case["questions"][1]["question_id"] = "q1"
    else:
        case["questions"][1]["document_id"] = "other"
    with pytest.raises(ValueError):
        validate_case(case)


def test_evidence_alias_and_single_document_selection():
    assert evidence_doc({"doc_name": "d"}) == "d"
    assert evidence_doc({"evidence_doc_name": "d"}) == "d"
    with pytest.raises(ValueError):
        evidence_doc({"doc_name": "d", "evidence_doc_name": "different"})
    rows = [
        {"financebench_id": "1", "doc_name": "d", "evidence": [{"doc_name": "d"}]},
        {"financebench_id": "2", "doc_name": "d", "evidence": [{"doc_name": "other"}]},
    ]
    selected, excluded = select_questions(rows, ["d"])
    assert [r["financebench_id"] for r in selected] == ["1"]
    assert excluded == [{"question_id": "2", "reason": "not_single_document"}]


def make_scored_run(tmp_path, case, outcomes):
    folder = tmp_path / "run"
    folder.mkdir()
    write_json(folder / "frozen_case.json", case)
    write_json(
        folder / "manifest.json",
        {
            "status": "complete",
            "repeats": 1,
            "case_sha256": digest(case),
        },
    )
    records, judgments = [], []
    for condition, (first, second) in outcomes.items():
        response = {
            "answers": [
                {"question_id": "q1", "answer": str(first)},
                {"question_id": "q2", "answer": str(second)},
            ]
        }
        record = {
            "execution_id": condition,
            "repeat_id": 0,
            "condition": condition,
            "response": response,
            "output_sha256": digest(response),
            "input_sha256": digest(runner_payload(case, CONDITIONS[condition], 0)),
        }
        records.append(record)
        for question_id, correct in [("q1", first), ("q2", second)]:
            judgments.append(
                {
                    "judgment_id": judgment_id(record, question_id),
                    "correct": correct,
                    "judge_id": "TEST_ONLY",
                }
            )
    write_jsonl(folder / "records.jsonl", records)
    return folder, records, judgments


def test_real_joint_outcomes_not_union_of_singles_and_regressions_count(tmp_path, case):
    folder, _, judgments = make_scored_run(
        tmp_path,
        case,
        {
            "baseline": (True, False),
            "no_op": (False, False),
            "A": (True, True),
            "B": (True, True),
            "AB": (False, True),
        },
    )
    row = score(folder, judgments)["repeats"][0]
    assert row["conditions"]["AB"]["net_recovery"] == 0
    assert row["conditions"]["AB"]["regressed_question_ids"] == ["q1"]
    assert row["interaction_count"] == -2
    assert row["no_op_net_change"] == -1


def test_synergy_is_not_assumed_away_and_judgments_are_required(tmp_path, case):
    folder, _, judgments = make_scored_run(
        tmp_path,
        case,
        {
            "baseline": (False, False),
            "no_op": (False, False),
            "A": (False, False),
            "B": (False, False),
            "AB": (True, True),
        },
    )
    assert score(folder, judgments)["repeats"][0]["interaction_count"] == 2
    with pytest.raises(ValueError):
        score(folder, judgments[:-1])
    judgments[0]["correct"] = "false"
    with pytest.raises(ValueError):
        score(folder, judgments)


def test_judging_hides_condition_and_detects_modified_predictions(tmp_path, case):
    folder, records, _ = make_scored_run(
        tmp_path, case, {key: (False, False) for key in CONDITIONS}
    )
    gold = [
        {"question_id": "q1", "reference_answer": "100"},
        {"question_id": "q2", "reference_answer": "200"},
    ]
    rows = judgment_template(folder, gold)
    assert len(rows) == 10 and all(row["correct"] is None for row in rows)
    assert all("condition" not in row and "repeat_id" not in row for row in rows)
    records[0]["response"]["answers"][0]["answer"] = "modified"
    write_jsonl(folder / "records.jsonl", records)
    with pytest.raises(ValueError, match="output changed"):
        load_complete_run(folder)


def test_runner_executes_both_no_change_conditions_without_reuse(tmp_path, case):
    script = tmp_path / "runner.py"
    calls = tmp_path / "calls.jsonl"
    script.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "data=json.load(sys.stdin)\n"
        f"with Path({str(calls)!r}).open('a') as f: f.write(json.dumps(data)+'\\n')\n"
        "print(json.dumps({'answers':[{'question_id':q['question_id'],'answer':'TEST_ONLY'} "
        "for q in data['questions']]}))\n"
    )
    output = tmp_path / "run"
    result = run_case(case, [sys.executable, str(script)], output, repeats=2)
    assert result["completed_calls"] == 10
    payloads = [json.loads(line) for line in calls.read_text().splitlines()]
    assert sum(row["blocks"][0]["text"] == "a=1 b=2" for row in payloads) == 4
    assert "DO_NOT_SEND" not in calls.read_text()
    with pytest.raises(FileExistsError):
        run_case(case, [sys.executable, str(script)], output)


def test_missing_answers_and_failed_runner_are_not_scored(tmp_path, case):
    with pytest.raises(ValueError):
        validate_response(
            {"answers": [{"question_id": "q1", "answer": "x"}]}, runner_payload(case, (), 0)
        )
    with pytest.raises(ValueError, match="nonempty"):
        validate_response(
            {
                "answers": [
                    {"question_id": "q1", "answer": ""},
                    {"question_id": "q2", "answer": "x"},
                ]
            },
            runner_payload(case, (), 0),
        )
    with pytest.raises(ValueError, match="completed"):
        validate_response(
            {
                "answers": [
                    {"question_id": "q1", "answer": "x"},
                    {"question_id": "q2", "answer": "x"},
                ],
                "metadata": {"status": "incomplete"},
            },
            runner_payload(case, (), 0),
        )
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError):
        run_case(case, [sys.executable, "-c", "raise SystemExit(3)"], output)
    assert json.loads((output / "manifest.json").read_text())["status"] == "failed"
    with pytest.raises(ValueError):
        load_complete_run(output)


def test_timeout_marks_run_failed(monkeypatch, tmp_path, case):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", "runner"), timeout=0.1)

    monkeypatch.setattr(subprocess, "run", timeout)
    output = tmp_path / "timeout"
    with pytest.raises(subprocess.TimeoutExpired):
        run_case(case, ["runner"], output, timeout=0.1)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["error_type"] == "TimeoutExpired"
