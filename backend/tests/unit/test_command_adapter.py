"""Command Template 보안과 Shell 없는 Parser 실행을 검증한다."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.parsers.command_utils import render_command, validate_command_template
from app.adapters.parsers.generic_command import GenericCommandParserAdapter
from app.core.exceptions import AppError


def test_command_template_only_allows_known_variables() -> None:
    validate_command_template(
        ["docling", "{input_path}", "--output", "{output_dir}"],
        ["docling"],
    )

    with pytest.raises(AppError, match="Unsupported command template"):
        validate_command_template(["docling", "{user_input}"], ["docling"])


def test_command_template_enforces_executable_allowlist() -> None:
    with pytest.raises(AppError, match="not in COMMAND_ALLOWED_EXECUTABLES"):
        validate_command_template(["bash", "-c", "anything"], ["docling"])


def test_render_command_replaces_each_allowed_path(tmp_path: Path) -> None:
    command = render_command(
        ["docling", "{input_path}", "{output_dir}", "{config_path}"],
        tmp_path / "input.pdf",
        tmp_path / "output",
        tmp_path / "config.json",
    )

    assert command == [
        "docling",
        str(tmp_path / "input.pdf"),
        str(tmp_path / "output"),
        str(tmp_path / "config.json"),
    ]


async def test_generic_command_adapter_executes_without_shell(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.txt"
    input_path.write_text("input", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    connector = SimpleNamespace(
        name="Test Command",
        model_version="1",
        timeout_seconds=3,
        command_template=[
            sys.executable,
            "-c",
            ("import pathlib,sys;pathlib.Path(sys.argv[1],'output.md').write_text('parsed text')"),
            "{output_dir}",
        ],
    )
    adapter = GenericCommandParserAdapter(connector)

    result = await adapter.parse(input_path, output_dir, {"mode": "test"})
    canonical = await adapter.normalize(result, "document", "run")

    assert result.text == "parsed text"
    assert result.markdown == "parsed text"
    assert result.metrics["exit_code"] == 0
    assert canonical.full_text == "parsed text"
    assert not (output_dir / "config.json").exists()
