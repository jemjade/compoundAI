"""Parser 설정 규약을 위한 JSON Schema 검증."""

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.core.exceptions import AppError


def validate_config_schema(schema: dict[str, Any]) -> None:
    """Connector 등록 시 잘못된 설정 스키마를 거부한다."""
    if not schema:
        return
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AppError(
            "PARSER_CONFIG_SCHEMA_INVALID",
            f"Parser config_schema is invalid: {exc.message}",
            422,
        ) from exc


def validate_parser_config(schema: dict[str, Any], config: dict[str, Any]) -> None:
    """완전히 병합된 Default·Preset·Override 설정 Snapshot을 검증한다."""
    if not schema:
        return
    validate_config_schema(schema)
    try:
        Draft202012Validator(schema).validate(config)
    except ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path)
        prefix = f"{location}: " if location else ""
        raise AppError(
            "PARSER_CONFIG_INVALID",
            f"{prefix}{exc.message}",
            422,
        ) from exc
