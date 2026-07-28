"""공개 비식별화 인터페이스와 Adapter 선택 도우미."""

from app.adapters.deidentifiers.base import (
    DeidentificationExecutionResult,
    DeidentifierAdapter,
)
from app.adapters.deidentifiers.registry import get_deidentifier_adapter

__all__ = [
    "DeidentificationExecutionResult",
    "DeidentifierAdapter",
    "get_deidentifier_adapter",
]
