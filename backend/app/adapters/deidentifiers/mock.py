"""개발 및 CI용 결정론적 로컬 개인정보 마스킹 Adapter."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.adapters.deidentifiers.base import (
    DeidentificationExecutionResult,
    DeidentifierAdapter,
)

PATTERNS = (
    (
        "RRN",
        re.compile(r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)"),
    ),
    (
        "EMAIL",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),
    ),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:01[016789]|0(?:2|[3-6][1-5]))[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
    ),
)


def _read_mock_input(input_path: Path, input_type: str) -> str:
    if input_type == "CANONICAL_JSON":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return str(payload.get("full_text", ""))
        return ""
    return input_path.read_text(encoding="utf-8", errors="ignore")


class MockDeidentifierAdapter(DeidentifierAdapter):
    """외부 파수 API가 비활성화된 경우 사용하는 결정론적 로컬 대체 구현."""

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "provider": "MOCK_FASOO", "mode": "in-process"}

    async def deidentify(
        self,
        input_path: Path,
        input_type: str,
        output_dir: Path,
        config: dict[str, Any],
    ) -> DeidentificationExecutionResult:
        del output_dir
        await asyncio.sleep(float(config.get("delay_seconds", 0)))
        text = await asyncio.to_thread(_read_mock_input, input_path, input_type)
        entities: list[dict[str, Any]] = []
        masked_text = text
        for entity_type, pattern in PATTERNS:
            matches = list(pattern.finditer(masked_text))
            entities.extend(
                # 테스트에는 위치와 유형만 저장하고 감지된 개인정보 원문은 저장하지 않는다.
                {
                    "type": entity_type,
                    "start": match.start(),
                    "end": match.end(),
                }
                for match in matches
            )
            masked_text = pattern.sub(f"[{entity_type}]", masked_text)
        entity_count = len(entities)
        return DeidentificationExecutionResult(
            provider="MOCK_FASOO",
            deidentified_text=masked_text,
            raw_data={
                "provider": "MOCK_FASOO",
                "entities": entities,
            },
            detected_entity_count=entity_count,
            masked_entity_count=entity_count,
            metrics={"input_characters": len(text), "output_characters": len(masked_text)},
        )
