"""사이냅 DocuAnalyzer REST API의 비동기 변환 흐름과 결과 정규화."""

import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.parsers.base import ParserAdapter, ParserExecutionResult
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.normalizers.synap_normalizer import normalize_synap_response
from app.schemas.canonical_document import CanonicalDocument

SYNAP_SUBMIT_PATH = "/da"
SYNAP_STATUS_PATH = "/filestatus/{fid}"
SYNAP_RESULT_PATH = "/result/{fid}"
SYNAP_DELETE_PATH = "/delete/{fid}"
SYNAP_HEALTH_PATH = "/health-check"
SYNAP_TERMINAL_STATUSES = {"SUCCESS", "FAILED"}


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "Synap parser requires an http(s) base_url.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _body_status(payload: dict[str, Any], http_status: int) -> int:
    value = payload.get("status", http_status)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(
            "PARSER_OUTPUT_NOT_FOUND",
            "Synap returned an invalid status value.",
        ) from exc


def _response_result(
    response: httpx.Response,
    operation: str,
    *,
    allowed_statuses: set[int] | None = None,
) -> Any:
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise AppError(
            "PARSER_OUTPUT_NOT_FOUND",
            f"Synap {operation} returned invalid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        return payload

    status = _body_status(payload, response.status_code)
    if status not in (allowed_statuses or {200}):
        raise AppError(
            "PARSER_EXECUTION_FAILED",
            f"Synap {operation} returned status {status}.",
            details={"synap_status": status},
        )
    return payload.get("result", payload)


def _require_dict(value: Any, operation: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError(
            "PARSER_OUTPUT_NOT_FOUND",
            f"Synap {operation} response did not contain an object result.",
        )
    return value


def _coerce_page(value: Any, page_number: int) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {"page_number": page_number, "text": value}
    if isinstance(value, list):
        return {"page_number": page_number, "elements": value}
    if not isinstance(value, dict):
        raise AppError(
            "PARSER_OUTPUT_NOT_FOUND",
            f"Synap page {page_number} did not contain a JSON result.",
        )
    return {"page_number": page_number, **value}


def _collect_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _collect_text(item)]
    if not isinstance(value, dict):
        return []
    for key in ("full_text", "text", "content"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return [text]
    # DocuAnalyzer Chat 응답은 실제 문자열을
    # pages[].contents[].contents 아래에 중첩해서 반환한다.
    for key in ("blocks", "elements", "children", "contents"):
        nested = value.get(key)
        if isinstance(nested, list):
            texts = _collect_text(nested)
            if texts:
                return texts
    return []


def _page_markdown(page: dict[str, Any]) -> str | None:
    value = page.get("markdown")
    return value if isinstance(value, str) and value.strip() else None


def _poll_interval(config: dict[str, Any]) -> float:
    try:
        value = float(config.get("poll_interval_seconds", 0.5))
    except (TypeError, ValueError) as exc:
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "Synap poll_interval_seconds must be a number.",
        ) from exc
    if not 0.1 <= value <= 30:
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "Synap poll_interval_seconds must be between 0.1 and 30.",
        )
    return value


def _use_image_ocr(config: dict[str, Any]) -> bool:
    value = config.get("use_image_ocr", False)
    if not isinstance(value, bool):
        raise AppError(
            "PARSER_CONFIGURATION_INVALID",
            "Synap use_image_ocr must be a boolean.",
        )
    return value


def parse_synap_response(
    execution_result: ParserExecutionResult,
    *,
    document_id: str,
    run_id: str,
    parser_name: str,
    parser_version: str | None,
    parser_config: dict[str, Any],
) -> CanonicalDocument:
    if not isinstance(execution_result.raw_data, dict):
        raise AppError(
            "PARSER_NORMALIZATION_FAILED",
            "Synap parser response must be a JSON object.",
        )
    return normalize_synap_response(
        execution_result.raw_data,
        document_id=document_id,
        run_id=run_id,
        parser_name=parser_name,
        parser_version=parser_version,
        parser_config=parser_config,
        fallback_text=execution_result.text or "",
        fallback_markdown=execution_result.markdown,
    )


class SynapHttpAdapter(ParserAdapter):
    """DocuAnalyzer의 제출, Polling, 페이지 수집, 정리를 하나의 Parse로 감싼다."""

    def __init__(self, connector: Any) -> None:
        self.connector = connector
        self._last_config: dict[str, Any] = {}

    async def health_check(self) -> dict[str, Any]:
        url = _endpoint_url(self.connector.base_url, SYNAP_HEALTH_PATH)
        try:
            async with httpx.AsyncClient(
                timeout=min(self.connector.timeout_seconds, 10),
                follow_redirects=False,
            ) as client:
                response = await client.get(url)
            result = _require_dict(_response_result(response, "health check"), "health check")
            engine_status = result.get("da_engine_status")
            healthy = response.is_success and engine_status in {200, "200"}
            return {
                "healthy": healthy,
                "status_code": response.status_code,
                "engine_status": engine_status,
                "message": result.get("msg"),
            }
        except (AppError, httpx.HTTPError) as exc:
            return {
                "healthy": False,
                "error": type(exc).__name__,
            }

    async def parse(
        self,
        input_path: Path,
        output_dir: Path,
        config: dict[str, Any],
    ) -> ParserExecutionResult:
        del output_dir
        self._last_config = config
        api_key = get_settings().synap_api_key
        if not api_key:
            raise AppError(
                "PARSER_CONFIGURATION_INVALID",
                "SYNAP_API_KEY is required for the Synap parser.",
            )

        poll_interval = _poll_interval(config)
        use_image_ocr = _use_image_ocr(config)
        timeout_seconds = self.connector.timeout_seconds
        fid: str | None = None
        cleanup_succeeded: bool | None = None
        poll_count = 0
        response_bytes = 0
        started = monotonic()

        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as client:
                try:
                    async with asyncio.timeout(timeout_seconds):
                        submit_url = _endpoint_url(self.connector.base_url, SYNAP_SUBMIT_PATH)
                        with input_path.open("rb") as document:
                            submit_response = await client.post(
                                submit_url,
                                files={
                                    "file": (
                                        input_path.name,
                                        document,
                                        "application/octet-stream",
                                    )
                                },
                                data={
                                    "api_key": api_key,
                                    "use_image_ocr": str(use_image_ocr).lower(),
                                    "type": "upload",
                                },
                            )
                        response_bytes += len(submit_response.content)
                        submit_result = _require_dict(
                            _response_result(submit_response, "conversion request"),
                            "conversion request",
                        )
                        fid_value = submit_result.get("fid")
                        if not isinstance(fid_value, str) or not fid_value:
                            raise AppError(
                                "PARSER_OUTPUT_NOT_FOUND",
                                "Synap conversion response did not contain fid.",
                            )
                        fid = fid_value

                        status_result: dict[str, Any]
                        while True:
                            status_url = _endpoint_url(
                                self.connector.base_url,
                                SYNAP_STATUS_PATH.format(fid=fid),
                            )
                            status_response = await client.post(
                                status_url,
                                json={"api_key": api_key},
                            )
                            response_bytes += len(status_response.content)
                            poll_count += 1
                            status_result = _require_dict(
                                _response_result(status_response, "conversion status"),
                                "conversion status",
                            )
                            file_status = str(status_result.get("filestatus", "")).upper()
                            if file_status in SYNAP_TERMINAL_STATUSES:
                                break
                            if file_status not in {"LOADING", "RUNNING"}:
                                raise AppError(
                                    "PARSER_EXECUTION_FAILED",
                                    "Synap returned an unknown conversion status.",
                                )
                            await asyncio.sleep(poll_interval)

                        if file_status == "FAILED":
                            return_code = status_result.get("returncode")
                            raise AppError(
                                "PARSER_EXECUTION_FAILED",
                                f"Synap conversion failed with returncode {return_code}.",
                                details={"synap_returncode": return_code},
                            )
                        try:
                            total_pages = int(status_result.get("total_pages", 0))
                        except (TypeError, ValueError) as exc:
                            raise AppError(
                                "PARSER_OUTPUT_NOT_FOUND",
                                "Synap status returned an invalid total_pages value.",
                            ) from exc
                        if total_pages < 1:
                            raise AppError(
                                "PARSER_OUTPUT_NOT_FOUND",
                                "Synap status did not contain a positive total_pages value.",
                            )

                        pages: list[dict[str, Any]] = []
                        for page_number in range(1, total_pages + 1):
                            result_url = _endpoint_url(
                                self.connector.base_url,
                                SYNAP_RESULT_PATH.format(fid=fid),
                            )
                            page_response = await client.post(
                                result_url,
                                json={
                                    "api_key": api_key,
                                    "page_index": page_number,
                                    "type": "json",
                                },
                            )
                            response_bytes += len(page_response.content)
                            page_result = _response_result(page_response, f"page {page_number}")
                            pages.append(_coerce_page(page_result, page_number))
                finally:
                    if fid:
                        cleanup_succeeded = await self._cleanup(client, fid, api_key)
        except TimeoutError as exc:
            raise AppError(
                "PARSER_TIMEOUT",
                f"Synap exceeded {timeout_seconds} seconds.",
            ) from exc
        except AppError:
            raise
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Synap returned HTTP status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "PARSER_EXECUTION_FAILED",
                f"Synap request failed: {type(exc).__name__}.",
            ) from exc

        full_text = "\n\n".join(
            text.strip() for page in pages for text in _collect_text(page) if text.strip()
        )
        markdown_parts = [markdown for page in pages if (markdown := _page_markdown(page))]
        markdown = "\n\n".join(markdown_parts) if markdown_parts else None
        raw_data = {
            "status": 200,
            "result": {
                "fid": fid,
                "filestatus": "SUCCESS",
                "total_pages": len(pages),
                "full_text": full_text,
                "markdown": markdown,
                "pages": pages,
                "metadata": {
                    "provider": "SYNAP_DOCUANALYZER",
                    "result_type": "json",
                },
            },
        }
        return ParserExecutionResult(
            raw_data=raw_data,
            text=full_text,
            markdown=markdown,
            metrics={
                "fid": fid,
                "http_status": 200,
                "poll_count": poll_count,
                "page_requests": len(pages),
                "response_bytes": response_bytes,
                "cleanup_succeeded": cleanup_succeeded,
                "latency_ms": int((monotonic() - started) * 1000),
            },
        )

    async def _cleanup(
        self,
        client: httpx.AsyncClient,
        fid: str,
        api_key: str,
    ) -> bool:
        try:
            response = await client.post(
                _endpoint_url(
                    self.connector.base_url,
                    SYNAP_DELETE_PATH.format(fid=fid),
                ),
                json={"api_key": api_key},
                timeout=min(self.connector.timeout_seconds, 5),
            )
            _response_result(response, "result cleanup")
            return True
        except (AppError, httpx.HTTPError, TimeoutError):
            return False

    async def normalize(
        self,
        execution_result: ParserExecutionResult,
        document_id: str,
        run_id: str,
    ) -> CanonicalDocument:
        return parse_synap_response(
            execution_result,
            document_id=document_id,
            run_id=run_id,
            parser_name=self.connector.name,
            parser_version=self.connector.model_version,
            parser_config=self._last_config,
        )
