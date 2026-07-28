"""Parser JSON Schema와 병합 설정 검증을 확인한다."""

import pytest

from app.core.exceptions import AppError
from app.utils.config_validation import validate_parser_config


def test_parser_config_validates_merged_values() -> None:
    schema = {
        "type": "object",
        "properties": {
            "ocr": {"type": "boolean"},
            "table_mode": {"enum": ["fast", "accurate"]},
        },
        "required": ["ocr"],
        "additionalProperties": False,
    }

    validate_parser_config(schema, {"ocr": True, "table_mode": "accurate"})
    with pytest.raises(AppError, match="is not of type"):
        validate_parser_config(schema, {"ocr": "yes"})
