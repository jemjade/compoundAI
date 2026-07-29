"""Parser 설정의 재귀 병합을 검증한다."""

import pytest

from app.core.config import Settings
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


def test_paddle_boolean_environment_value_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PADDLEOCR_ENABLED", "false")
    monkeypatch.setenv("PADDLEOCR_USE_TABLE_RECOGNITION", "true")

    settings = Settings(_env_file=None)

    assert settings.paddleocr_enabled is False
    assert settings.paddleocr_use_table_recognition is True
