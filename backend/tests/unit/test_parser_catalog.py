"""환경 기반 Parser Catalog 정의를 검증한다."""

from app.core.config import Settings
from app.services.parser_catalog import enabled_parser_definitions


def test_enabled_parser_catalog_contains_three_real_integrations() -> None:
    settings = Settings(
        _env_file=None,
        paddleocr_enabled=True,
        docling_base_url="http://docling:5001",
        mineru_base_url="http://mineru:8000",
    )

    definitions = enabled_parser_definitions(settings)
    by_slug = {definition.slug: definition for definition in definitions}

    assert set(by_slug) == {"pp-structure-v3", "docling", "mineru-3"}
    assert by_slug["pp-structure-v3"].adapter_key == "pp_structure_v3"
    assert by_slug["docling"].adapter_key == "docling_http"
    assert by_slug["docling"].base_url == "http://docling:5001"
    assert by_slug["mineru-3"].adapter_key == "mineru_http"
    assert by_slug["mineru-3"].default_config["lang_list"] == ["korean"]


def test_disabled_external_integrations_keep_builtin_paddle_catalog_entry() -> None:
    settings = Settings(
        _env_file=None,
        paddleocr_enabled=False,
        docling_base_url=None,
        mineru_base_url=None,
    )

    definitions = enabled_parser_definitions(settings)

    assert [definition.slug for definition in definitions] == ["pp-structure-v3"]
