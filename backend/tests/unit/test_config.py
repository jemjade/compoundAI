"""Parser 설정의 재귀 병합을 검증한다."""

from app.utils.config import merge_config


def test_merge_config_preserves_nested_defaults_and_applies_override() -> None:
    merged = merge_config(
        {"ocr": {"enabled": False, "language": "ko"}, "table": "fast"},
        {"ocr": {"enabled": True}},
        {"table": "accurate"},
    )

    assert merged == {
        "ocr": {"enabled": True, "language": "ko"},
        "table": "accurate",
    }
