"""Command Template의 보안 검증과 안전한 경로 치환."""

import string
from pathlib import Path
from typing import Any

from app.core.exceptions import AppError

ALLOWED_TEMPLATE_VARIABLES = {"input_path", "output_dir", "config_path"}


def validate_command_template(
    template: list[str] | None,
    allowed_executables: list[str],
) -> None:
    """명령이 Subprocess에 전달되기 전에 argv 목록 형태로 검증한다.

    실행 파일 허용 목록과 고정된 Template 변수 집합은 관리자가 Shell을 활성화하지
    않고도 명령을 설정할 수 있게 하는 보안 경계다.
    """
    if not template or not all(isinstance(item, str) and item for item in template):
        raise AppError(
            "INVALID_COMMAND_TEMPLATE",
            "Command template must be a non-empty list of arguments.",
            422,
        )
    executable = Path(template[0]).name
    if executable not in allowed_executables:
        raise AppError(
            "COMMAND_NOT_ALLOWED",
            f"Executable '{executable}' is not in COMMAND_ALLOWED_EXECUTABLES.",
            422,
        )
    formatter = string.Formatter()
    for argument in template:
        try:
            fields = {
                field_name
                for _, field_name, _, _ in formatter.parse(argument)
                if field_name is not None
            }
        except ValueError as exc:
            raise AppError(
                "INVALID_COMMAND_TEMPLATE",
                f"Invalid command template argument: {argument}",
                422,
            ) from exc
        unsupported = fields - ALLOWED_TEMPLATE_VARIABLES
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise AppError(
                "INVALID_COMMAND_TEMPLATE",
                f"Unsupported command template variable(s): {names}",
                422,
            )


def render_command(
    template: list[str],
    input_path: Path,
    output_dir: Path,
    config_path: Path,
) -> list[str]:
    """argv 목록 구조를 유지하면서 검증된 경로만 치환한다."""
    values: dict[str, Any] = {
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "config_path": str(config_path),
    }
    return [argument.format_map(values) for argument in template]
