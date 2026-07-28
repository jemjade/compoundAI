"""Parser 설정을 재귀적으로 병합하는 도우미."""

from typing import Any


def merge_config(*configs: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for config in configs:
        for key, value in (config or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = merge_config(merged[key], value)
            else:
                merged[key] = value
    return merged
