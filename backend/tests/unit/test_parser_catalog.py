"""환경 기반 Parser Catalog 정의를 검증한다."""

from app.core.config import Settings
from app.services.parser_catalog import enabled_parser_definitions, parser_catalog_entries


def test_enabled_parser_catalog_contains_configured_real_integrations() -> None:
    settings = Settings(
        _env_file=None,
        paddleocr_enabled=True,
        docling_base_url="http://docling:5001",
        mineru_base_url="http://mineru:8000",
        synap_box_base_url="http://synap-box/docuanalyzer-box",
        synap_chat_base_url="http://synap-chat/docuanalyzer-chat",
        synap_api_key="test-key",
    )

    definitions = enabled_parser_definitions(settings)
    by_slug = {definition.slug: definition for definition in definitions}

    assert set(by_slug) == {
        "pp-structure-v3",
        "docling",
        "mineru-3",
        "synap-docuanalyzer-box",
        "synap-docuanalyzer-chat",
    }
    assert by_slug["pp-structure-v3"].adapter_key == "pp_structure_v3"
    assert by_slug["docling"].adapter_key == "docling_http"
    assert by_slug["docling"].base_url == "http://docling:5001"
    assert by_slug["mineru-3"].adapter_key == "mineru_http"
    assert by_slug["mineru-3"].default_config["lang_list"] == ["korean"]
    assert by_slug["synap-docuanalyzer-box"].adapter_key == "synap_http"
    assert by_slug["synap-docuanalyzer-box"].base_url == (
        "http://synap-box/docuanalyzer-box"
    )
    assert by_slug["synap-docuanalyzer-chat"].base_url == (
        "http://synap-chat/docuanalyzer-chat"
    )
    assert by_slug["synap-docuanalyzer-chat"].default_config["result_delivery"] == (
        "pages"
    )


def test_disabled_external_integrations_keep_builtin_paddle_catalog_entry() -> None:
    settings = Settings(
        _env_file=None,
        paddleocr_enabled=False,
        docling_base_url=None,
        mineru_base_url=None,
        synap_box_base_url=None,
        synap_chat_base_url=None,
    )

    definitions = enabled_parser_definitions(settings)

    assert [definition.slug for definition in definitions] == ["pp-structure-v3"]


def test_unconfigured_synap_integrations_are_visible_as_inactive_catalog_entries() -> None:
    settings = Settings(
        _env_file=None,
        docling_base_url=None,
        mineru_base_url=None,
        synap_box_base_url=None,
        synap_chat_base_url=None,
        synap_api_key=None,
    )

    entries = parser_catalog_entries(settings)
    by_slug = {entry.definition.slug: entry for entry in entries}

    assert by_slug["synap-docuanalyzer-box"].is_active is False
    assert by_slug["synap-docuanalyzer-box"].definition.base_url is None
    assert by_slug["synap-docuanalyzer-chat"].is_active is False
    assert by_slug["synap-docuanalyzer-chat"].definition.base_url is None
