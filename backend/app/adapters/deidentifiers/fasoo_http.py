"""파수 비식별화를 위한 HTTP 전송 및 요청·응답 매핑."""

import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.deidentifiers.base import (
    DeidentificationExecutionResult,
    DeidentifierAdapter,
)
from app.core.config import Settings
from app.core.exceptions import AppError


def build_fasoo_request(
    content: str,
    input_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """ParseLab의 고정 입력 규약을 파수 JSON 요청 규약으로 매핑한다.

    운영 환경별로 파수 요청 스키마가 다를 수 있으므로 이 매핑을 별도로 격리한다.
    """
    return {
        "input_type": input_type,
        "content": content,
        "config": config,
    }


def parse_fasoo_response(payload: Any) -> DeidentificationExecutionResult:
    """알려진 파수 응답 변형을 하나의 내부 결과 모델로 정규화한다."""
    if not isinstance(payload, dict):
        raise AppError("FASOO_EXECUTION_FAILED", "Fasoo returned an invalid response.")
    result = payload.get("result", payload)
    if isinstance(result, str):
        return DeidentificationExecutionResult(
            provider="FASOO",
            deidentified_text=result,
            raw_data=payload,
        )
    if not isinstance(result, dict):
        raise AppError("FASOO_EXECUTION_FAILED", "Fasoo response did not contain a result.")

    text = next(
        (
            result[key]
            for key in (
                "deidentified_text",
                "deidentifiedText",
                "masked_text",
                "maskedText",
                "output",
                "text",
                "content",
            )
            if isinstance(result.get(key), str)
        ),
        None,
    )
    if text is None:
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            "Fasoo response did not contain deidentified text.",
        )
    entities = result.get("entities")
    detected_count = result.get("detected_entity_count", result.get("detectedCount"))
    masked_count = result.get("masked_entity_count", result.get("maskedCount"))
    if detected_count is None and isinstance(entities, list):
        detected_count = len(entities)
    if masked_count is None:
        masked_count = detected_count
    return DeidentificationExecutionResult(
        provider="FASOO",
        deidentified_text=text,
        raw_data=payload,
        detected_entity_count=int(detected_count) if detected_count is not None else None,
        masked_entity_count=int(masked_count) if masked_count is not None else None,
        metrics=result.get("metrics") if isinstance(result.get("metrics"), dict) else {},
    )


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "FASOO_BASE_URL must be an http or https URL when Fasoo is enabled.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


class FasooHttpDeidentifierAdapter(DeidentifierAdapter):
    """전송 세부사항을 Pipeline에서 분리한 채 HTTP로 파수를 호출한다."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        if not self.settings.fasoo_api_key:
            return {}
        return {"Authorization": f"Bearer {self.settings.fasoo_api_key}"}

    async def health_check(self) -> dict[str, Any]:
        url = _endpoint_url(self.settings.fasoo_base_url, "/health")
        try:
            async with httpx.AsyncClient(
                timeout=min(self.settings.fasoo_timeout_seconds, 10),
                follow_redirects=False,
            ) as client:
                response = await client.get(url, headers=self._headers())
            return {
                "healthy": response.is_success,
                "status_code": response.status_code,
                "provider": "FASOO",
            }
        except httpx.HTTPError as exc:
            return {
                "healthy": False,
                "error": type(exc).__name__,
                "provider": "FASOO",
            }

    async def deidentify(
        self,
        input_path: Path,
        input_type: str,
        output_dir: Path,
        config: dict[str, Any],
    ) -> DeidentificationExecutionResult:
        del output_dir
        url = _endpoint_url(
            self.settings.fasoo_base_url,
            str(config.get("http_endpoint", "/deidentify")),
        )
        request_config = {key: value for key, value in config.items() if key != "http_endpoint"}
        started = monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.fasoo_timeout_seconds,
                follow_redirects=False,
            ) as client:
                if input_type == "ORIGINAL_FILE":
                    # 바이너리 원본은 Multipart를, 파생 텍스트 형식은 아래의 JSON을 사용한다.
                    with input_path.open("rb") as source:
                        response = await client.post(
                            url,
                            headers=self._headers(),
                            files={
                                "file": (
                                    input_path.name,
                                    source,
                                    "application/octet-stream",
                                )
                            },
                            data={
                                "input_type": input_type,
                                "config": json.dumps(request_config, ensure_ascii=False),
                            },
                        )
                else:
                    content = await _read_text_input(input_path, input_type)
                    response = await client.post(
                        url,
                        headers=self._headers(),
                        json=build_fasoo_request(content, input_type, request_config),
                    )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(
                "FASOO_TIMEOUT",
                f"Fasoo exceeded {self.settings.fasoo_timeout_seconds} seconds.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            # 응답 본문에 문서 내용이 있을 수 있으므로 오류 메시지에 복사하지 않는다.
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                f"Fasoo returned status {exc.response.status_code}.",
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                f"Fasoo request failed: {type(exc).__name__}.",
            ) from exc

        result = parse_fasoo_response(payload)
        result.metrics = {
            **result.metrics,
            "http_status": response.status_code,
            "latency_ms": int((monotonic() - started) * 1000),
        }
        return result


async def _read_text_input(input_path: Path, input_type: str) -> str:
    content = await asyncio.to_thread(
        input_path.read_text,
        encoding="utf-8",
        errors="ignore",
    )
    if input_type != "CANONICAL_JSON":
        return content
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            "Canonical JSON input is invalid.",
        ) from exc
    return str(payload.get("full_text", "")) if isinstance(payload, dict) else ""
