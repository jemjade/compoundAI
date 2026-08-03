"""Ground Truth 기반 자동 평가 지표의 계산 규약을 검증한다."""

from copy import deepcopy

import pytest

from app.core.exceptions import AppError
from app.services.benchmark_metrics import evaluate_documents
from app.services.benchmark_service import _aggregate, validate_ground_truth


def sample_document() -> dict:
    return {
        "full_text": "제목 본문 123456-1234567",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {
                        "id": "title",
                        "type": "title",
                        "reading_order": 0,
                        "text": "제목",
                        "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 20},
                    },
                    {
                        "id": "body",
                        "type": "paragraph",
                        "reading_order": 1,
                        "text": "본문",
                        "bbox": {"x1": 0, "y1": 30, "x2": 100, "y2": 60},
                    },
                    {
                        "id": "table",
                        "type": "table",
                        "reading_order": 2,
                        "text": "A B",
                        "bbox": {"x1": 0, "y1": 70, "x2": 100, "y2": 120},
                        "cells": [
                            {
                                "row": 0,
                                "column": 0,
                                "row_span": 1,
                                "column_span": 1,
                                "text": "A",
                            },
                            {
                                "row": 0,
                                "column": 1,
                                "row_span": 1,
                                "column_span": 1,
                                "text": "B",
                            },
                        ],
                    },
                    {
                        "id": "formula",
                        "type": "formula",
                        "reading_order": 3,
                        "text": r"x^2+y^2",
                        "bbox": {"x1": 0, "y1": 130, "x2": 100, "y2": 150},
                    },
                ],
            }
        ],
        "pii_entities": [{"type": "RRN", "start": 6, "end": 20}],
    }


def test_perfect_document_scores_one() -> None:
    document = sample_document()
    metrics, counts, diagnostics = evaluate_documents(
        document,
        deepcopy(document),
        {
            "raw_data": {
                "entities": [{"type": "RRN", "start": 6, "end": 20}],
            }
        },
    )

    assert metrics["text_cer"] == 0
    assert metrics["text_accuracy"] == 1
    assert metrics["layout_f1_iou50"] == 1
    assert metrics["table_structure_f1"] == 1
    assert metrics["table_teds"] == 1
    assert metrics["table_content_accuracy"] == 1
    assert metrics["reading_order_accuracy"] == 1
    assert metrics["formula_accuracy"] == 1
    assert metrics["pii_f1"] == 1
    assert metrics["overall_quality"] == 1
    assert counts["matched_cells"] == 2
    assert diagnostics["text_edit_distance"] == 0


def test_metrics_separate_text_structure_order_and_pii_failures() -> None:
    ground_truth = sample_document()
    prediction = deepcopy(ground_truth)
    prediction["full_text"] = "제목 오인식"
    prediction["pages"][0]["blocks"][0]["reading_order"] = 3
    prediction["pages"][0]["blocks"][3]["reading_order"] = 0
    prediction["pages"][0]["blocks"][2]["cells"].pop()

    metrics, counts, _ = evaluate_documents(
        ground_truth,
        prediction,
        {"raw_data": {"entities": [{"type": "PHONE", "start": 6, "end": 20}]}},
    )

    assert 0 < metrics["text_cer"] <= 1
    assert metrics["text_accuracy"] < 1
    assert metrics["table_structure_recall"] == pytest.approx(0.5)
    assert metrics["table_teds"] < 1
    assert metrics["reading_order_accuracy"] < 1
    assert metrics["pii_precision"] == 0
    assert metrics["pii_recall"] == 0
    assert metrics["pii_leakage_rate"] == 1
    assert counts["prediction_cells"] == 1


def test_cer_uses_ground_truth_character_count_and_may_exceed_one() -> None:
    ground_truth = {"full_text": "가", "pages": []}
    prediction = {"full_text": "가나다", "pages": []}

    metrics, _, _ = evaluate_documents(ground_truth, prediction)

    assert metrics["text_cer"] == 2
    assert metrics["text_accuracy"] == pytest.approx(1 / 3)


def test_metric_aggregate_uses_student_t_interval_for_small_samples() -> None:
    aggregate = _aggregate([0.8, 1.0])
    unbounded = _aggregate([1.0, 2.0], bounded=False)

    assert aggregate.value == pytest.approx(0.9)
    assert aggregate.ci95_low == 0
    assert aggregate.ci95_high == 1
    assert aggregate.sample_count == 2
    assert unbounded.ci95_high is not None and unbounded.ci95_high > 1


@pytest.mark.parametrize(
    "payload",
    [
        {"full_text": "text", "pages": [{"page_number": "first", "blocks": []}]},
        {
            "full_text": "text",
            "pages": [{"page_number": 1, "blocks": [{"type": "table", "cells": "bad"}]}],
        },
        {
            "full_text": "text",
            "pages": [],
            "pii_entities": [{"type": "RRN", "start": 10, "end": 5}],
        },
    ],
)
def test_ground_truth_validation_rejects_invalid_metric_inputs(payload: dict) -> None:
    with pytest.raises(AppError) as caught:
        validate_ground_truth(payload)

    assert caught.value.code == "INVALID_GROUND_TRUTH"
