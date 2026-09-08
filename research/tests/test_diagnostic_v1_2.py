"""Validity-focused tests for the frozen v1.2 QA-contract diagnostic."""

from __future__ import annotations

from research.diagnostic_v1_2 import (
    GROSS_QUESTION_ID,
    TAX_QUESTION_ID,
    _gross_evaluation,
    _structured_table,
    _tax_evaluation,
)


def _answer(text, *, cited=True, structured_output=None):
    return {
        "question_id": GROSS_QUESTION_ID,
        "answer": text,
        "evidence_block_ids": ["BOEING_2022_10K:p55"] if cited else [],
        "structured_output": structured_output,
    }


def test_structured_representation_preserves_damage_and_blank_label():
    damaged = """Total revenues 6,608 62,286 58,158
Total costs and expenses (6,106) (59,269) (63,843)
3,502 3,017 (5,685)
Income tax (expense)/benefit (31) 743 2,535"""
    output = _structured_table(damaged)
    assert "| Total revenues | 6,608 | 62,286 | 58,158 |" in output
    assert "| Total costs and expenses | (6,106) | (59,269) | (63,843) |" in output
    assert "| [row label blank in source] | 3,502 | 3,017 | (5,685) |" in output
    assert "gross profit" not in output.lower()
    assert "66,608" not in output and "63,106" not in output


def test_gross_evaluator_separates_correct_conclusion_from_missing_numbers():
    result = _gross_evaluation(
        _answer("Yes, Boeing has an improving gross margin profile as of FY2022."),
        "repaired",
    )
    assert result["conclusion_correctness"] == "CORRECT"
    assert result["stated_numeric_accuracy"] == "NOT_APPLICABLE_NO_NUMBERS"
    assert result["required_quantitative_explanation_completeness"] == (
        "MISSING_OR_INCOMPLETE"
    )
    assert result["evidence_sufficiency"] == "SUFFICIENT"
    assert result["unconditional_overall_correct"] is False


def test_gross_evaluator_accepts_equivalent_margin_explanation_without_all_gold_numbers():
    structured = {
        "conclusion": "Yes, the profile improved.",
        "quantitative_explanation": "Gross margin was 5.3% in 2022 and 4.8% in 2021.",
        "calculations": ["gross margin = subtotal / revenue × 100"],
        "evidence_chunk_ids": ["chunk-1"],
    }
    result = _gross_evaluation(
        _answer(
            "\n".join(
                [
                    structured["conclusion"],
                    structured["quantitative_explanation"],
                    *structured["calculations"],
                ]
            ),
            structured_output=structured,
        ),
        "repaired",
    )
    assert result["conclusion_correctness"] == "CORRECT"
    assert result["stated_numeric_accuracy"] == "ALL_STATED_NUMBERS_CORRECT"
    assert result["required_quantitative_explanation_completeness"] == "COMPLETE"
    assert result["all_reference_numbers_required"] is False
    assert result["unconditional_overall_correct"] is True


def test_gross_evaluator_marks_wrong_numbers_and_damaged_evidence_separately():
    result = _gross_evaluation(
        _answer(
            "Yes, gross margin improved from 4.8% in 2021 to 7.6% in 2022. "
            "gross margin = subtotal / revenue."
        ),
        "damaged",
    )
    assert result["conclusion_correctness"] == "CORRECT"
    assert result["stated_numeric_accuracy"] == "INCORRECT_NUMERIC_CLAIM"
    assert result["evidence_sufficiency"] == "INSUFFICIENT"


def test_tax_evaluator_preserves_reference_sign_conflict():
    financebench = _tax_evaluation(
        {
            **_answer("FY2022 was 0.62%, compared with -14.76% in FY2021."),
            "question_id": TAX_QUESTION_ID,
        }
    )
    filing = _tax_evaluation(
        {
            **_answer("The filing reports (0.6)% in FY2022 versus 14.7% in FY2021."),
            "question_id": TAX_QUESTION_ID,
        }
    )
    wrong_signs = _tax_evaluation(
        {
            **_answer("FY2022 was -0.62%, compared with 14.76% in FY2021."),
            "question_id": TAX_QUESTION_ID,
        }
    )
    assert financebench["financebench_reference_numbers_correct"] is True
    assert financebench["filing_reported_numbers_correct"] is False
    assert filing["filing_reported_numbers_correct"] is True
    assert filing["financebench_reference_numbers_correct"] is False
    assert (
        wrong_signs["stated_numeric_accuracy"] == "DOES_NOT_MATCH_RETAINED_REFERENCES"
    )
    assert financebench["unconditional_overall_correct"] is None
