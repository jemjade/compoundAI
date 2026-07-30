"""파수 NAS 경로 비식별화 API 전송과 산출물 정규화."""

import asyncio
import json
import re
import shutil
from pathlib import Path, PurePosixPath
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

_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
_TEXT_SUFFIXES = {".json", ".md", ".txt"}


def _endpoint_url(base_url: str | None, path: str) -> str:
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "FASOO_BASE_URL must be an http or https URL when Fasoo is enabled.",
        )
    if not path.startswith("/") or path.startswith("//"):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Fasoo API paths must be absolute URL paths.",
        )
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def build_fasoo_rule(
    settings: Settings,
    config: dict[str, Any],
) -> dict[str, Any]:
    """환경 기본 정책 또는 실행별 ``rule``을 실제 파수 요청 규약으로 만든다."""
    configured_rule = config.get("rule")
    if configured_rule is not None:
        if not isinstance(configured_rule, dict):
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "Fasoo rule must be a JSON object.",
            )
        rule = dict(configured_rule)
    elif settings.fasoo_rule_json:
        try:
            loaded_rule = json.loads(settings.fasoo_rule_json)
        except json.JSONDecodeError as exc:
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "FASOO_RULE_JSON must contain valid JSON.",
            ) from exc
        if not isinstance(loaded_rule, dict):
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "FASOO_RULE_JSON must contain a JSON object.",
            )
        rule = loaded_rule
    else:
        rule = {
            "masking": True,
            "maskingChar": settings.fasoo_masking_char,
            "patterns": settings.fasoo_patterns,
            "patternOptions": [],
            "labels": settings.fasoo_labels,
            "labelOptions": [],
            "version": settings.fasoo_rule_version,
            "systemCode": settings.fasoo_system_code,
            "systemName": settings.fasoo_system_name,
        }

    if rule.get("masking") is not True:
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Fasoo path integration requires rule.masking=true.",
        )
    patterns = rule.get("patterns", [])
    labels = rule.get("labels", [])
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Fasoo rule.patterns must be a string array.",
        )
    if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Fasoo rule.labels must be a string array.",
        )
    if not patterns and not labels:
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "At least one Fasoo pattern or label must be configured.",
        )
    return rule


def build_fasoo_request(
    input_path: str,
    output_path: str,
    masked_path: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    """동기 경로 검출 요청을 생성한다. 동기 호출에는 callbackUrl을 보내지 않는다."""
    return {
        "sync": "true",
        "inputPath": input_path,
        "outputPath": output_path,
        "maskedPath": masked_path,
        "rule": rule,
    }


def local_to_fasoo_path(
    local_path: Path,
    local_root: Path,
    fasoo_root: str,
) -> str:
    """공유 NAS의 로컬 Mount 경로를 파수 서버가 보는 POSIX 경로로 변환한다."""
    resolved_root = local_root.resolve()
    resolved_path = local_path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Fasoo staging path is outside NAS_MOUNT_PATH.",
        ) from exc

    remote_root = PurePosixPath(fasoo_root)
    if not remote_root.is_absolute() or ".." in remote_root.parts:
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "FASOO_NAS_PATH must be an absolute POSIX path.",
        )
    return str(remote_root.joinpath(*relative.parts))


def _safe_staging_directory(settings: Settings, output_dir: Path) -> Path:
    scope = output_dir.name
    if not scope or not _SAFE_PATH_SEGMENT.fullmatch(scope):
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "Run directory name cannot be used as a Fasoo staging scope.",
        )
    local_root = settings.nas_mount_path.resolve()
    staging_dir = (local_root / settings.fasoo_work_subdir / scope).resolve()
    if local_root not in staging_dir.parents:
        raise AppError(
            "FASOO_CONFIGURATION_INVALID",
            "FASOO_WORK_SUBDIR escaped NAS_MOUNT_PATH.",
        )
    return staging_dir


def _find_integer(payload: Any, keys: set[str]) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        for value in payload.values():
            found = _find_integer(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_integer(value, keys)
            if found is not None:
                return found
    return None


def _find_list_length(payload: Any, keys: set[str]) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, list):
                return len(value)
        for value in payload.values():
            found = _find_list_length(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_list_length(value, keys)
            if found is not None:
                return found
    return None


def _find_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in (
            "deidentified_text",
            "deidentifiedText",
            "masked_text",
            "maskedText",
            "output",
            "text",
            "content",
        ):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        values = payload.values()
    elif isinstance(payload, list):
        values = payload
    else:
        return None
    for value in values:
        found = _find_text(value)
        if found is not None:
            return found
    return None


def parse_fasoo_result(
    payload: Any,
    masked_file_path: Path,
    *,
    http_payload: Any = None,
) -> DeidentificationExecutionResult:
    """NAS 결과 JSON을 내부 결과로 정규화한다.

    파수 결과 JSON 상세 Schema는 제공되지 않았으므로 알려진 Count/Text 키만
    보수적으로 읽고 원본 JSON은 그대로 보존한다.
    """
    if not isinstance(payload, (dict, list)):
        raise AppError(
            "FASOO_EXECUTION_FAILED",
            "Fasoo result artifact must contain a JSON object or array.",
        )
    detected_count = _find_integer(
        payload,
        {
            "detected_entity_count",
            "detectedEntityCount",
            "detectedCount",
            "detectCount",
            "totalCount",
        },
    )
    if detected_count is None:
        detected_count = _find_list_length(
            payload,
            {"detections", "entities", "items"},
        )
    masked_count = _find_integer(
        payload,
        {
            "masked_entity_count",
            "maskedEntityCount",
            "maskedCount",
            "maskingCount",
        },
    )
    if masked_count is None:
        masked_count = detected_count

    text = _find_text(payload)
    if text is None and masked_file_path.suffix.lower() in _TEXT_SUFFIXES:
        text = masked_file_path.read_text(encoding="utf-8", errors="ignore")

    raw_data: dict[str, Any] = {"result": payload}
    if isinstance(http_payload, (dict, list, str, int, float, bool)):
        raw_data["http_response"] = http_payload
    return DeidentificationExecutionResult(
        provider="FASOO",
        deidentified_text=text or "",
        raw_data=raw_data,
        detected_entity_count=detected_count,
        masked_entity_count=masked_count,
        masked_file_path=masked_file_path,
    )


async def _wait_for_artifacts(
    paths: tuple[Path, ...],
    wait_seconds: float,
) -> None:
    deadline = monotonic() + wait_seconds
    while True:
        if all(path.is_file() for path in paths):
            return
        if monotonic() >= deadline:
            missing = ", ".join(path.name for path in paths if not path.is_file())
            raise AppError(
                "FASOO_ARTIFACT_NOT_FOUND",
                f"Fasoo completed without required NAS artifacts: {missing}.",
            )
        await asyncio.sleep(0.1)


def _optional_response_payload(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return None


class FasooHttpDeidentifierAdapter(DeidentifierAdapter):
    """공유 NAS에 파일을 배치하고 파수 동기 경로 검출 API를 호출한다."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._access_token: str | None = None
        self._token_lock = asyncio.Lock()

    def _login_configured(self) -> bool:
        values = (
            self.settings.fasoo_auth_url,
            self.settings.fasoo_username,
            self.settings.fasoo_password,
        )
        if not any(values):
            return False
        if not all(values):
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "FASOO_AUTH_URL, FASOO_USERNAME, and FASOO_PASSWORD must be configured together.",
            )
        if not self.settings.fasoo_auth_url.startswith(("http://", "https://")):
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "FASOO_AUTH_URL must be an http or https URL.",
            )
        return True

    async def _login(self, client: httpx.AsyncClient) -> str:
        if not self._login_configured():
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "Fasoo login credentials are not configured.",
            )
        try:
            response = await client.post(
                self.settings.fasoo_auth_url,
                data={
                    "username": self.settings.fasoo_username,
                    "password": self.settings.fasoo_password,
                    "redirectUrl": self.settings.fasoo_auth_redirect_url,
                    "lang": self.settings.fasoo_auth_lang,
                },
                timeout=min(self.settings.fasoo_timeout_seconds, 10),
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppError(
                "FASOO_AUTHENTICATION_FAILED",
                "Fasoo login request timed out.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "FASOO_AUTHENTICATION_FAILED",
                f"Fasoo login returned status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "FASOO_AUTHENTICATION_FAILED",
                f"Fasoo login request failed: {type(exc).__name__}.",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "FASOO_AUTHENTICATION_FAILED",
                "Fasoo login response is not valid JSON.",
            ) from exc
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise AppError(
                "FASOO_AUTHENTICATION_FAILED",
                "Fasoo login response did not contain access_token.",
            )
        return token.strip()

    async def _token(
        self,
        client: httpx.AsyncClient,
        *,
        rejected_token: str | None = None,
    ) -> str | None:
        if not self.settings.fasoo_api_key:
            if not self._login_configured():
                return None
            async with self._token_lock:
                if self._access_token and (
                    rejected_token is None or self._access_token != rejected_token
                ):
                    return self._access_token
                self._access_token = await self._login(client)
                return self._access_token
        return self.settings.fasoo_api_key

    async def _headers(
        self,
        client: httpx.AsyncClient,
        *,
        rejected_token: str | None = None,
    ) -> tuple[dict[str, str], str | None]:
        token = await self._token(client, rejected_token=rejected_token)
        if token is None:
            return {}, None
        return {"Authorization": f"Bearer {token}"}, token

    def _can_refresh_token(self, token: str | None) -> bool:
        return token is not None and not self.settings.fasoo_api_key and self._login_configured()

    def _client_kwargs(self, timeout: float) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": False,
        }
        if self.settings.fasoo_ca_bundle is not None:
            kwargs["verify"] = str(self.settings.fasoo_ca_bundle)
        return kwargs

    async def health_check(self) -> dict[str, Any]:
        url = _endpoint_url(
            self.settings.fasoo_base_url,
            self.settings.fasoo_configuration_path,
        )
        try:
            async with httpx.AsyncClient(
                **self._client_kwargs(min(self.settings.fasoo_timeout_seconds, 10))
            ) as client:
                headers, token = await self._headers(client)
                response = await client.get(url, headers=headers)
                if response.status_code == 401 and self._can_refresh_token(token):
                    headers, _ = await self._headers(client, rejected_token=token)
                    response = await client.get(url, headers=headers)
            return {
                "healthy": response.is_success,
                "status_code": response.status_code,
                "provider": "FASOO",
            }
        except AppError as exc:
            return {
                "healthy": False,
                "error": exc.code,
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
        del input_type
        if not await asyncio.to_thread(input_path.is_file):
            raise AppError("FASOO_EXECUTION_FAILED", "Fasoo input file is not available.")
        if not await asyncio.to_thread(self.settings.nas_mount_path.is_dir):
            raise AppError(
                "FASOO_CONFIGURATION_INVALID",
                "NAS_MOUNT_PATH is not an available directory.",
            )

        rule = build_fasoo_rule(self.settings, config)
        staging_dir = _safe_staging_directory(self.settings, output_dir)
        suffix = input_path.suffix.lower()
        input_dir = staging_dir / "input"
        masked_dir = staging_dir / "masked"
        staged_input = input_dir / f"input{suffix}"
        result_artifact = masked_dir / "result.json"
        masked_artifact = masked_dir / f"masked{suffix}"

        def prepare_staging() -> None:
            input_dir.mkdir(parents=True, exist_ok=True)
            masked_dir.mkdir(parents=True, exist_ok=True)
            for stale_path in (staged_input, result_artifact, masked_artifact):
                if stale_path.is_file() or stale_path.is_symlink():
                    stale_path.unlink()
            shutil.copy2(input_path, staged_input)

        try:
            await asyncio.to_thread(prepare_staging)
        except OSError as exc:
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                f"Unable to prepare Fasoo NAS staging: {type(exc).__name__}.",
            ) from exc
        request_payload = build_fasoo_request(
            local_to_fasoo_path(
                staged_input,
                self.settings.nas_mount_path,
                self.settings.fasoo_nas_path,
            ),
            local_to_fasoo_path(
                result_artifact,
                self.settings.nas_mount_path,
                self.settings.fasoo_nas_path,
            ),
            local_to_fasoo_path(
                masked_artifact,
                self.settings.nas_mount_path,
                self.settings.fasoo_nas_path,
            ),
            rule,
        )
        url = _endpoint_url(
            self.settings.fasoo_base_url,
            self.settings.fasoo_detect_path,
        )
        started = monotonic()
        try:
            async with httpx.AsyncClient(
                **self._client_kwargs(self.settings.fasoo_timeout_seconds)
            ) as client:
                headers, token = await self._headers(client)
                response = await client.post(
                    url,
                    headers=headers,
                    json=request_payload,
                )
                if response.status_code == 401 and self._can_refresh_token(token):
                    headers, _ = await self._headers(client, rejected_token=token)
                    response = await client.post(
                        url,
                        headers=headers,
                        json=request_payload,
                    )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AppError(
                "FASOO_TIMEOUT",
                f"Fasoo exceeded {self.settings.fasoo_timeout_seconds} seconds.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                f"Fasoo returned status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                f"Fasoo request failed: {type(exc).__name__}.",
            ) from exc

        await _wait_for_artifacts(
            (result_artifact, masked_artifact),
            self.settings.fasoo_artifact_wait_seconds,
        )
        try:
            result_text = await asyncio.to_thread(
                result_artifact.read_text,
                encoding="utf-8",
            )
            result_payload = await asyncio.to_thread(json.loads, result_text)
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError(
                "FASOO_EXECUTION_FAILED",
                "Fasoo result artifact is not valid JSON.",
            ) from exc

        result = await asyncio.to_thread(
            parse_fasoo_result,
            result_payload,
            masked_artifact,
            http_payload=_optional_response_payload(response),
        )
        result.metrics = {
            **result.metrics,
            "http_status": response.status_code,
            "latency_ms": int((monotonic() - started) * 1000),
        }
        return result
