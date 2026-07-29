"""허용 목록 기반 Parser Adapter Registry와 Connector 팩토리."""

from app.adapters.parsers.base import ParserAdapter
from app.adapters.parsers.docling_command import DoclingCommandAdapter
from app.adapters.parsers.generic_command import GenericCommandParserAdapter
from app.adapters.parsers.generic_http import GenericHttpParserAdapter
from app.adapters.parsers.mock import MockParserAdapter
from app.adapters.parsers.paddle_structure import PPStructureV3Adapter
from app.adapters.parsers.synap_http import SynapHttpAdapter
from app.core.exceptions import AppError
from app.db.models.parser import ParserConnector

PARSER_ADAPTERS: dict[str, type[ParserAdapter]] = {
    "mock_parser": MockParserAdapter,
    "pp_structure_v3": PPStructureV3Adapter,
    "synap_http": SynapHttpAdapter,
    "docling_command": DoclingCommandAdapter,
    "generic_http": GenericHttpParserAdapter,
    "generic_command": GenericCommandParserAdapter,
}


def get_parser_adapter(connector: ParserConnector) -> ParserAdapter:
    adapter_class = PARSER_ADAPTERS.get(connector.adapter_key)
    if adapter_class is None:
        raise AppError(
            "UNSUPPORTED_PARSER_ADAPTER",
            f"Unsupported parser adapter: {connector.adapter_key}",
            status_code=422,
        )
    return adapter_class(connector)
