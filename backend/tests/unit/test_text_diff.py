"""상대 텍스트 유사도와 선택적 공백 정규화를 검증한다."""

from app.utils.text_diff import compare_text


def test_compare_text_reports_relative_similarity_and_changes() -> None:
    result = compare_text("계약 당사자는 A", "계약 당사자는 에이")

    assert 0 < result["similarity_ratio"] < 1
    assert result["added_count"] == 2
    assert result["removed_count"] == 1
    assert {part["type"] for part in result["diff"]} == {"equal", "removed", "added"}


def test_compare_text_can_normalize_whitespace() -> None:
    result = compare_text("hello\n\nworld", "hello world", normalize_whitespace=True)

    assert result["similarity_ratio"] == 1
    assert result["added_count"] == 0
    assert result["removed_count"] == 0
