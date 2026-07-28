"""환경설정에 따라 Mock 또는 HTTP 파수 Adapter를 선택한다."""

from app.adapters.deidentifiers.base import DeidentifierAdapter
from app.adapters.deidentifiers.fasoo_http import FasooHttpDeidentifierAdapter
from app.adapters.deidentifiers.mock import MockDeidentifierAdapter
from app.core.config import Settings, get_settings


def get_deidentifier_adapter(settings: Settings | None = None) -> DeidentifierAdapter:
    resolved_settings = settings or get_settings()
    if resolved_settings.fasoo_enabled:
        return FasooHttpDeidentifierAdapter(resolved_settings)
    return MockDeidentifierAdapter()
