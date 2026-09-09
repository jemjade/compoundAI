"""PaddleOCR 3.x PP-StructureV3 내장 Parser Adapter."""

import asyncio
import importlib.util
import math
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from importlib import metadata
from pathlib import Path
from time import monotonic
from typing import Any

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.normalizers.paddle_normalizer import normalize_paddle_response
from app.schemas.canonical_document import CanonicalDocument

PADDLE_ADAPTER_KEY = "pp_structure_v3"
PADDLE_SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
PADDLE_OPTION_NAMES = frozenset(
    {
        "use_doc_orientation_classify",
        "use_doc_unwarping",
        "use_textline_orientation",
        "use_table_recognition",
        "use_formula_recognition",
        "use_chart_recognition",
        "use_seal_recognition",
    }
)
PADDLE_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {option: {"type": "boolean"} for option in sorted(PADDLE_OPTION_NAMES)},
    "additionalProperties": False,
}


def paddle_default_options(settings: Settings) -> dict[str, bool]:
    return {
        "use_doc_orientation_classify": settings.paddleocr_use_doc_orientation,
        "use_doc_unwarping": settings.paddleocr_use_doc_unwarping,
        "use_textline_orientation": settings.paddleocr_use_textline_orientation,
        "use_table_recognition": settings.paddleocr_use_table_recognition,
        "use_formula_recognition": settings.paddleocr_use_formula_recognition,
        "use_chart_recognition": settings.paddleocr_use_chart_recognition,
        "use_seal_recognition": settings.paddleocr_use_seal_recognition,
    }


def validate_paddle_options(
    settings: Settings,
    config: dict[str, Any],
) -> dict[str, bool]:
    unknown = set(config) - PADDLE_OPTION_NAMES
    if unknown:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            f"Unsupported PP-StructureV3 options: {', '.join(sorted(unknown))}.",
            422,
        )
    invalid = [key for key, value in config.items() if not isinstance(value, bool)]
    if invalid:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            f"PP-StructureV3 options must be boolean: {', '.join(sorted(invalid))}.",
            422,
        )

    initialized_options = paddle_default_options(settings)
    effective_options = {**initialized_options, **config}
    unavailable = [
        key
        for key, enabled in effective_options.items()
        if enabled and not initialized_options[key]
    ]
    if unavailable:
        raise AppError(
            "PARSER_CONFIG_INVALID",
            (
                "These PP-StructureV3 modules were not initialized: "
                f"{', '.join(sorted(unavailable))}. Enable the matching "
                "PADDLEOCR_USE_* setting and restart the backend."
            ),
            422,
        )
    return effective_options


def validate_paddle_input(input_path: Path) -> None:
    if not input_path.is_file():
        raise AppError("INPUT_FILE_NOT_FOUND", "PaddleOCR input file is not available.")
    suffix = input_path.suffix.lower()
    if suffix not in PADDLE_SUPPORTED_SUFFIXES:
        raise AppError(
            "UNSUPPORTED_FILE_TYPE",
            f"PP-StructureV3 does not support {suffix or 'files without an extension'}.",
            415,
        )
    if input_path.stat().st_size == 0:
        raise AppError("INVALID_INPUT_FILE", "PaddleOCR input file is empty.", 422)

    with input_path.open("rb") as source:
        header = source.read(16)
    valid_signature = (
        suffix == ".pdf"
        and header.startswith(b"%PDF-")
        or suffix == ".png"
        and header.startswith(b"\x89PNG\r\n\x1a\n")
        or suffix in {".jpg", ".jpeg"}
        and header.startswith(b"\xff\xd8\xff")
        or suffix == ".webp"
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    )
    if not valid_signature:
        raise AppError(
            "INVALID_INPUT_FILE",
            "PaddleOCR input content does not match its file extension.",
            422,
        )


def json_safe(value: Any, _seen: set[int] | None = None) -> Any:
    """Paddle/NumPy/Pydantic 값을 JSON 직렬화 가능한 값으로 보수적으로 변환한다."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return json_safe(value.value, _seen)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    seen = _seen if _seen is not None else set()
    value_id = id(value)
    if value_id in seen:
        return "<recursive>"
    seen.add(value_id)
    try:
        if isinstance(value, dict):
            return {str(key): json_safe(item, seen) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [json_safe(item, seen) for item in value]
        if is_dataclass(value) and not isinstance(value, type):
            return json_safe(asdict(value), seen)
        if hasattr(value, "model_dump"):
            return json_safe(value.model_dump(), seen)
        if hasattr(value, "tolist"):
            return json_safe(value.tolist(), seen)
        if hasattr(value, "item"):
            return json_safe(value.item(), seen)
        return str(value)
    finally:
        seen.discard(value_id)


def _markdown_text(markdown: Any) -> str:
    if isinstance(markdown, str):
        return markdown
    if not isinstance(markdown, dict):
        return ""
    value = markdown.get("markdown_texts", "")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(str(item) for item in value)
    return str(value) if value is not None else ""


def _result_json(result: Any) -> Any:
    if isinstance(result, dict):
        return result
    value = getattr(result, "json", None)
    return value() if callable(value) else value


def _result_markdown(result: Any) -> Any:
    if isinstance(result, dict):
        return result.get("markdown", {})
    value = getattr(result, "markdown", None)
    return value() if callable(value) else value


def _page_text(raw: Any, markdown: str) -> str:
    payload = raw.get("res", raw) if isinstance(raw, dict) else {}
    if isinstance(payload, dict):
        parsing_results = payload.get("parsing_res_list")
        if isinstance(parsing_results, list):
            blocks = [
                str(item.get("block_content", ""))
                for item in parsing_results
                if isinstance(item, dict) and item.get("block_content")
            ]
            if blocks:
                return "\n\n".join(blocks)
        ocr_result = payload.get("overall_ocr_res")
        if isinstance(ocr_result, dict) and isinstance(ocr_result.get("rec_texts"), list):
            return "\n".join(str(item) for item in ocr_result["rec_texts"])
    return markdown


def _is_download_error(exc: Exception) -> bool:
    module = type(exc).__module__
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        module.startswith(
            (
                "aiohttp",
                "aistudio_sdk",
                "huggingface_hub",
                "modelscope",
                "requests",
                "urllib3",
            )
        )
        or name in {"connectionerror", "httperror", "networkerror", "proxyerror"}
        or any(
            marker in message
            for marker in (
                "connection refused",
                "connection reset",
                "failed to download",
                "name resolution",
                "network is unreachable",
                "temporary failure in name resolution",
            )
        )
    )


def _is_out_of_memory(exc: Exception) -> bool:
    return isinstance(exc, MemoryError) or "out of memory" in str(exc).lower()


@dataclass
class PaddleRuntimeResult:
    pages: list[dict[str, Any]]
    markdown: str
    text: str
    warnings: list[str]
    library_version: str
    elapsed_ms: int


class PPStructureRuntime:
    """프로세스 안에서 Pipeline을 한 번 초기화하고 동기 추론을 제한한다."""

    def __init__(
        self,
        settings: Settings,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any = None
        self._initialization_lock = threading.Lock()
        self._inference_semaphore = threading.BoundedSemaphore(settings.paddleocr_max_concurrency)
        self.initialization_count = 0

    @property
    def initialized(self) -> bool:
        return self._pipeline is not None

    def _create_pipeline(self) -> Any:
        cache_dir = self.settings.paddleocr_model_cache_dir
        if cache_dir is not None:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise AppError(
                    "MODEL_INITIALIZATION_FAILED",
                    "PaddleOCR model cache directory is not writable.",
                ) from exc
            # PaddleX 3.7 reads this official variable while importing its cache module.
            os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_dir.resolve())

        factory = self._pipeline_factory
        if factory is None:
            try:
                from paddleocr import PPStructureV3
            except ImportError as exc:
                raise AppError(
                    "MODEL_INITIALIZATION_FAILED",
                    (
                        "PaddleOCR runtime is not installed. "
                        "Install the paddleocr-cpu optional dependency."
                    ),
                ) from exc
            factory = PPStructureV3

        try:
            pipeline = factory(
                **paddle_default_options(self.settings),
                device=self.settings.paddleocr_device,
                engine="paddle",
            )
        except AppError:
            raise
        except Exception as exc:
            code = (
                "MODEL_DOWNLOAD_FAILED"
                if _is_download_error(exc)
                else "MODEL_INITIALIZATION_FAILED"
            )
            message = (
                "PaddleOCR model download failed."
                if code == "MODEL_DOWNLOAD_FAILED"
                else "PaddleOCR model initialization failed."
            )
            raise AppError(code, message) from exc
        self.initialization_count += 1
        return pipeline

    def get_pipeline(self) -> Any:
        if self._pipeline is None:
            with self._initialization_lock:
                if self._pipeline is None:
                    self._pipeline = self._create_pipeline()
        return self._pipeline

    def predict(
        self,
        input_path: Path,
        options: dict[str, bool],
    ) -> PaddleRuntimeResult:
        started = monotonic()
        with self._inference_semaphore:
            pipeline = self.get_pipeline()
            try:
                results = list(pipeline.predict(input=str(input_path), **options))
            except Exception as exc:
                if _is_out_of_memory(exc):
                    raise AppError(
                        "OUT_OF_MEMORY",
                        "PaddleOCR ran out of device memory.",
                    ) from exc
                raise AppError("PARSING_FAILED", "PaddleOCR inference failed.") from exc

            if not results:
                raise AppError("PARSING_FAILED", "PaddleOCR returned no page results.")

            warnings: list[str] = []
            page_results: list[dict[str, Any]] = []
            markdown_infos: list[Any] = []
            try:
                for index, result in enumerate(results):
                    raw_result = _result_json(result)
                    if raw_result is None:
                        warnings.append(f"page {index + 1}: JSON result was unavailable")
                        raw_result = {}
                    if isinstance(raw_result, dict) and raw_result.get("error"):
                        raise AppError(
                            "PARSING_FAILED",
                            "PaddleOCR rejected the requested model options.",
                        )
                    try:
                        markdown_info = _result_markdown(result)
                    except (
                        AttributeError,
                        KeyError,
                        TypeError,
                        ValueError,
                        ModuleNotFoundError,
                    ) as exc:
                        # JSON is the research/source-of-truth artifact. Optional Markdown
                        # construction can require document-export extras (for example python-docx)
                        # and must not discard an otherwise usable parser result.
                        warnings.append(
                            f"page {index + 1}: Markdown result was unavailable "
                            f"({type(exc).__name__})"
                        )
                        markdown_info = {}
                    markdown_infos.append(markdown_info)
                    page_markdown = _markdown_text(markdown_info)
                    safe_raw = json_safe(raw_result)
                    page_results.append(
                        {
                            "page_number": index + 1,
                            "markdown": page_markdown,
                            "raw": safe_raw,
                        }
                    )

                try:
                    merged_markdown = pipeline.concatenate_markdown_pages(markdown_infos)
                    if not isinstance(merged_markdown, str):
                        raise TypeError
                except (
                    AttributeError,
                    KeyError,
                    TypeError,
                    ValueError,
                    ModuleNotFoundError,
                ):
                    warnings.append("PaddleOCR Markdown page merge fallback was used")
                    merged_markdown = "\n\n".join(
                        page["markdown"] for page in page_results if page["markdown"]
                    )
            except AppError:
                raise
            except Exception as exc:
                raise AppError(
                    "RESULT_SERIALIZATION_FAILED",
                    "PaddleOCR result serialization failed.",
                ) from exc

        return PaddleRuntimeResult(
            pages=page_results,
            markdown=merged_markdown,
            text="\n\n".join(_page_text(page["raw"], page["markdown"]) for page in page_results),
            warnings=warnings,
            library_version=_paddleocr_version(),
            elapsed_ms=int((monotonic() - started) * 1000),
        )


def _paddleocr_version() -> str:
    try:
        return metadata.version("paddleocr")
    except metadata.PackageNotFoundError:
        return "not-installed"


_shared_runtime: PPStructureRuntime | None = None
_shared_runtime_signature: tuple[Any, ...] | None = None
_shared_runtime_lock = threading.Lock()


def _runtime_signature(settings: Settings) -> tuple[Any, ...]:
    return (
        settings.paddleocr_device,
        settings.paddleocr_max_concurrency,
        str(settings.paddleocr_model_cache_dir),
        *paddle_default_options(settings).values(),
    )


def get_shared_runtime(settings: Settings) -> PPStructureRuntime:
    global _shared_runtime, _shared_runtime_signature
    signature = _runtime_signature(settings)
    with _shared_runtime_lock:
        if _shared_runtime is None:
            _shared_runtime = PPStructureRuntime(settings)
            _shared_runtime_signature = signature
        elif _shared_runtime_signature != signature:
            raise AppError(
                "MODEL_INITIALIZATION_FAILED",
                "PaddleOCR process settings changed; restart the backend.",
            )
        return _shared_runtime


class PPStructureV3Adapter(ParserAdapter):
    """기존 Task Manager에서 실행되는 로컬 PP-StructureV3 Adapter."""

    def __init__(
        self,
        connector: Any,
        *,
        settings: Settings | None = None,
        runtime: PPStructureRuntime | None = None,
    ) -> None:
        self.connector = connector
        self.settings = settings or get_settings()
        self._injected_runtime = runtime
        self._last_config: dict[str, Any] = {}

    async def health_check(self) -> dict[str, Any]:
        if not self.settings.paddleocr_enabled:
            return {
                "healthy": False,
                "provider": "PADDLEOCR",
                "error_code": "PADDLEOCR_DISABLED",
            }
        dependency_available = (
            importlib.util.find_spec("paddleocr") is not None
            and importlib.util.find_spec("paddle") is not None
        )
        runtime = self._injected_runtime or _shared_runtime
        return {
            "healthy": dependency_available,
            "provider": "PADDLEOCR",
            "device": self.settings.paddleocr_device,
            "library_version": _paddleocr_version(),
            "model_initialized": bool(runtime and runtime.initialized),
            **({} if dependency_available else {"error_code": "MODEL_INITIALIZATION_FAILED"}),
        }

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        del output_dir
        if not self.settings.paddleocr_enabled:
            raise AppError("PADDLEOCR_DISABLED", "PaddleOCR parser is disabled.", 503)
        await asyncio.to_thread(validate_paddle_input, input_path)
        options = validate_paddle_options(self.settings, config)
        self._last_config = options
        runtime = self._injected_runtime or get_shared_runtime(self.settings)
        # Cancelling this coroutine marks the Run interrupted, but an in-flight native
        # Paddle inference call cannot be forcefully stopped inside the worker thread.
        result = await asyncio.to_thread(runtime.predict, input_path, options)
        raw_data = {
            "parser": {
                "name": PADDLE_ADAPTER_KEY,
                "library": "paddleocr",
                "library_version": result.library_version,
                "device": self.settings.paddleocr_device,
                "config": options,
            },
            "document": {
                "input_filename": input_path.name,
                "page_count": len(result.pages),
            },
            "content": {
                "markdown": result.markdown,
                "pages": result.pages,
            },
            "metrics": {"elapsed_ms": result.elapsed_ms},
            "warnings": result.warnings,
        }
        return ParserExecutionResult(
            raw_data=raw_data,
            markdown=result.markdown,
            text=result.text,
            metrics={
                "elapsed_ms": result.elapsed_ms,
                "page_count": len(result.pages),
                "warning_count": len(result.warnings),
                "device": self.settings.paddleocr_device,
                "library_version": result.library_version,
            },
        )

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        return normalize_paddle_response(
            execution_result.raw_data,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
        )
