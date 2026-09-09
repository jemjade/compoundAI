from research.evaluate_development_v1_3 import _aggregate


def test_v1_3_dimensions_are_aggregated_independently():
    rows = [
        {
            "conclusion_correctness": "CORRECT",
            "stated_numeric_accuracy": "NOT_APPLICABLE_NO_NUMBERS",
            "required_explanation_completeness": "MISSING_OR_INCOMPLETE",
            "evidence_sufficiency": "REQUIRED_EVIDENCE_NOT_RETRIEVED",
            "qa_contract_violations": ["quantitative_explanation"],
            "overall_task_correct": False,
        },
        {
            "conclusion_correctness": "INCORRECT",
            "stated_numeric_accuracy": "ALL_STATED_NUMBERS_CORRECT",
            "required_explanation_completeness": "PRESENT_BUT_INVALID",
            "evidence_sufficiency": "AVAILABLE_BUT_OUTPUT_UNSUPPORTED",
            "qa_contract_violations": [],
            "overall_task_correct": False,
        },
    ]
    result = _aggregate(rows)
    assert result["conclusion_correct"] == 1
    assert result["numeric_status"]["ALL_STATED_NUMBERS_CORRECT"] == 1
    assert result["contract_complete"] == 1
    assert result["overall_task_correct"] == 0
