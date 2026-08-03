"""환경에서 활성화한 공식 Parser Connector의 재사용 가능한 Catalog."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.parsers.docling_http import (
    DOCLING_HTTP_CONFIG_SCHEMA,
    DOCLING_HTTP_DEFAULT_CONFIG,
    DOCLING_SUPPORTED_FORMATS,
)
from app.adapters.parsers.mineru_http import (
    MINERU_CONFIG_SCHEMA,
    MINERU_DEFAULT_CONFIG,
)
from app.adapters.parsers.paddle_structure import (
    PADDLE_CONFIG_SCHEMA,
    paddle_default_options,
)
from app.adapters.parsers.synap_http import (
    SYNAP_CONFIG_SCHEMA,
    SYNAP_DEFAULT_CONFIG,
    SYNAP_SUPPORTED_FORMATS,
)
from app.core.config import Settings
from app.db.models.parser import ExecutionType
from app.db.models.user import User, UserRole
from app.repositories.parser_repository import ParserRepository
from app.schemas.parser import ParserCreate


@dataclass(frozen=True, slots=True)
class ParserCatalogEntry:
    definition: ParserCreate
    is_active: bool = True


def _synap_parser_entries(settings: Settings) -> list[ParserCatalogEntry]:
    entries: list[ParserCatalogEntry] = []
    for name, slug, description, base_url in (
        (
            "Synap DocuAnalyzer Box",
            "synap-docuanalyzer-box",
            "Synap DocuAnalyzer Box 기반 문서 구조 분석 Parser",
            settings.synap_box_base_url,
        ),
        (
            "Synap DocuAnalyzer Chat",
            "synap-docuanalyzer-chat",
            "Synap DocuAnalyzer Chat 기반 문서 구조 분석 Parser",
            settings.synap_chat_base_url,
        ),
    ):
        entries.append(
            ParserCatalogEntry(
                definition=ParserCreate(
                    name=name,
                    slug=slug,
                    description=description,
                    provider="Synapsoft",
                    model_name="DocuAnalyzer",
                    model_version=None,
                    execution_type=ExecutionType.HTTP,
                    adapter_key="synap_http",
                    base_url=base_url,
                    default_config=SYNAP_DEFAULT_CONFIG,
                    config_schema=SYNAP_CONFIG_SCHEMA,
                    capabilities=[
                        "TEXT",
                        "MARKDOWN",
                        "TABLE",
                        "LAYOUT",
                        "OCR",
                        "FORMULA",
                    ],
                    supported_formats=SYNAP_SUPPORTED_FORMATS,
                    timeout_seconds=300,
                ),
                is_active=bool(base_url and settings.synap_api_key),
            )
        )
    return entries


def enabled_parser_definitions(settings: Settings) -> list[ParserCreate]:
    """기본 Parser와 설정된 외부 Endpoint를 Catalog에 노출한다."""
    definitions: list[ParserCreate] = [
        ParserCreate(
            name="PaddleOCR PP-StructureV3",
            slug="pp-structure-v3",
            description="PaddleOCR 3.x 기반 로컬 문서 구조 분석 Parser",
            provider="PaddlePaddle",
            model_name="PP-StructureV3",
            model_version="3.7.x",
            execution_type=ExecutionType.BUILTIN,
            adapter_key="pp_structure_v3",
            default_config=paddle_default_options(settings),
            config_schema=PADDLE_CONFIG_SCHEMA,
            capabilities=["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR"],
            supported_formats=["pdf", "png", "jpg", "jpeg", "webp"],
            timeout_seconds=1800,
        )
    ]
    if settings.docling_base_url:
        definitions.append(
            ParserCreate(
                name="Docling",
                slug="docling",
                description="Docling Serve v1 기반 문서 변환 및 구조 분석 Parser",
                provider="LF AI & Data",
                model_name="Docling",
                model_version="2.x",
                execution_type=ExecutionType.HTTP,
                adapter_key="docling_http",
                base_url=settings.docling_base_url,
                default_config=DOCLING_HTTP_DEFAULT_CONFIG,
                config_schema=DOCLING_HTTP_CONFIG_SCHEMA,
                capabilities=["TEXT", "MARKDOWN", "TABLE", "LAYOUT", "OCR"],
                supported_formats=DOCLING_SUPPORTED_FORMATS,
                timeout_seconds=900,
            )
        )
    if settings.mineru_base_url:
        definitions.append(
            ParserCreate(
                name="MinerU 3.x",
                slug="mineru-3",
                description="MinerU 3.x 공식 mineru-api 기반 문서 구조 분석 Parser",
                provider="OpenDataLab",
                model_name="MinerU",
                model_version="3.x",
                execution_type=ExecutionType.HTTP,
                adapter_key="mineru_http",
                base_url=settings.mineru_base_url,
                default_config=MINERU_DEFAULT_CONFIG,
                config_schema=MINERU_CONFIG_SCHEMA,
                capabilities=[
                    "TEXT",
                    "MARKDOWN",
                    "TABLE",
                    "LAYOUT",
                    "OCR",
                    "FORMULA",
                ],
                supported_formats=[
                    "pdf",
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "docx",
                    "pptx",
                    "xlsx",
                ],
                timeout_seconds=1800,
            )
        )
    definitions.extend(
        entry.definition for entry in _synap_parser_entries(settings) if entry.is_active
    )
    return definitions


def parser_catalog_entries(settings: Settings) -> list[ParserCatalogEntry]:
    """미설정 외부 Parser를 포함해 관리 화면에 표시할 Catalog를 반환한다."""
    entries = [
        ParserCatalogEntry(definition=definition)
        for definition in enabled_parser_definitions(settings)
        if definition.adapter_key != "synap_http"
    ]
    entries.extend(_synap_parser_entries(settings))
    return entries


async def seed_enabled_parser_connectors(
    session: AsyncSession,
    settings: Settings,
    *,
    owner: User | None = None,
) -> list[str]:
    """기존 관리자 환경에도 활성화한 Connector를 idempotent하게 추가한다."""
    if owner is None:
        owner = await session.scalar(
            select(User).where(User.role == UserRole.ADMIN).order_by(User.created_at)
        )
    if owner is None:
        return []

    parsers = ParserRepository(session)
    created: list[str] = []
    changed = False
    for entry in parser_catalog_entries(settings):
        definition = entry.definition
        connector = await parsers.get_by_slug(definition.slug)
        if connector is not None:
            if definition.adapter_key == "synap_http":
                desired_base_url = definition.base_url or connector.base_url
                desired_active = bool(desired_base_url and settings.synap_api_key)
                if connector.base_url != desired_base_url:
                    connector.base_url = desired_base_url
                    changed = True
                if connector.is_active != desired_active:
                    connector.is_active = desired_active
                    changed = True
            continue
        connector = await parsers.create(definition, owner.id)
        connector.is_active = entry.is_active
        created.append(definition.slug)
        changed = True
    if changed:
        await session.commit()
    return created
