"""Shell을 사용하지 않는 Command Parser 실행과 산출물 탐색."""

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.adapters.parsers.command_utils import render_command
from app.core.exceptions import AppError
from app.normalizers.text_normalizer import text_to_canonical
from app.schemas.canonical_document import CanonicalDocument

STDIO_LIMIT = 20_000


def _read_first(paths: list[Path]) -> str | None:
    for path in paths:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _discover_outputs(
    output_dir: Path,
) -> tuple[
    dict[str, Any] | list[Any] | str | None,
    str | None,
    str | None,
    int,
    list[str],
]:
    """Command Parser가 생성한 지원 형식의 첫 산출물을 찾는다."""
    json_paths = sorted(path for path in output_dir.rglob("*.json") if path.name != "config.json")
    markdown_paths = sorted(output_dir.rglob("*.md"))
    text_paths = sorted(output_dir.rglob("*.txt"))
    raw_data: dict[str, Any] | list[Any] | str | None = None
    for json_path in json_paths:
        try:
            raw_data = json.loads(json_path.read_text(encoding="utf-8"))
            break
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    output_files = [
        str(path.relative_to(output_dir))
        for path in sorted(output_dir.rglob("*"))
        if path.is_file()
    ]
    return (
        raw_data,
        _read_first(markdown_paths),
        _read_first(text_paths),
        len(json_paths) + len(markdown_paths) + len(text_paths),
        output_files,
    )


class GenericCommandParserAdapter(ParserAdapter):
    """Shell을 호출하지 않고 허용 목록에 등록된 Parser 명령을 실행한다."""

    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    async def health_check(self) -> dict[str, Any]:
        template = self.connector.command_template or []
        executable = template[0] if template else ""
        resolved = shutil.which(executable)
        return {
            "healthy": resolved is not None,
            "executable": executable,
            "resolved_path": resolved,
        }

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        template = self.connector.command_template
        if not template:
            raise AppError(
                "PARSER_CONFIGURATION_INVALID",
                "Command parser requires command_template.",
            )
        self._last_config = config
        config_path = output_dir / "config.json"
        await asyncio.to_thread(
            config_path.write_text,
            json.dumps(config, ensure_ascii=False, indent=2),
            "utf-8",
        )
        command = render_command(template, input_path, output_dir, config_path)
        started = asyncio.get_running_loop().time()
        process: asyncio.subprocess.Process | None = None
        try:
            # argv를 직접 전달하므로 경로나 설정의 Shell 특수문자는 실행되지 않는다.
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=output_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.connector.timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise AppError(
                    "PARSER_TIMEOUT",
                    f"Command parser exceeded {self.connector.timeout_seconds} seconds.",
                ) from exc
        except FileNotFoundError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Parser executable was not found: {command[0]}.",
            ) from exc
        except asyncio.CancelledError:
            # 작업 취소 후에도 Parser 프로세스가 백그라운드에 남지 않게 종료한다.
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            raise
        finally:
            # 설정 파일은 실행 범위에 한정되며 민감한 옵션을 포함할 수 있어 즉시 삭제한다.
            if config_path.exists():
                await asyncio.to_thread(config_path.unlink)

        latency_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Command parser exited with code {process.returncode}.",
            )

        raw_data, markdown, text, output_file_count, output_files = await asyncio.to_thread(
            _discover_outputs,
            output_dir,
        )
        has_parser_output = bool(output_file_count or stdout.strip())
        if not has_parser_output:
            raise AppError(
                "PARSER_OUTPUT_NOT_FOUND",
                "Command parser produced no supported output.",
            )
        if text is None and markdown is not None:
            text = markdown
        if text is None and stdout.strip():
            text = stdout.strip()
        if raw_data is None:
            # 출력이 많은 CLI가 과도한 크기의 산출물을 만들지 않도록 진단 정보를 제한한다.
            raw_data = {
                "exit_code": process.returncode,
                "stdout": stdout[:STDIO_LIMIT],
                "stderr": stderr[:STDIO_LIMIT],
                "output_files": output_files,
            }
        return ParserExecutionResult(
            raw_data=raw_data,
            markdown=markdown,
            text=text or "",
            metrics={
                "command_latency_ms": latency_ms,
                "exit_code": process.returncode,
                "output_file_count": output_file_count,
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        return text_to_canonical(
            text=execution_result.text or "",
            markdown=execution_result.markdown,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
            metadata={"transport": "command"},
        )
