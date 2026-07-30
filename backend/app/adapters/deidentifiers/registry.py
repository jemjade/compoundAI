"""환경설정에 따라 Mock 또는 HTTP 파수 Adapter를 선택한다."""

from app.adapters.deidentifiers.base import DeidentifierAdapter
from app.adapters.deidentifiers.fasoo_http import FasooHttpDeidentifierAdapter
from app.adapters.deidentifiers.mock import MockDeidentifierAdapter
from app.core.config import Settings, get_settings

_cached_fasoo_settings: Settings | None = None
_cached_fasoo_adapter: FasooHttpDeidentifierAdapter | None = None


def get_deidentifier_adapter(settings: Settings | None = None) -> DeidentifierAdapter:
    global _cached_fasoo_adapter, _cached_fasoo_settings

    resolved_settings = settings or get_settings()
    if resolved_settings.fasoo_enabled:
        if _cached_fasoo_settings is resolved_settings and _cached_fasoo_adapter is not None:
            return _cached_fasoo_adapter
        adapter = FasooHttpDeidentifierAdapter(resolved_settings)
        _cached_fasoo_settings = resolved_settings
        _cached_fasoo_adapter = adapter
        return adapter
    return MockDeidentifierAdapter()
