"""환경에서 활성화한 공식 Parser Connector의 재사용 가능한 Catalog."""

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
from app.core.config import Settings
from app.db.models.parser import ExecutionType
from app.db.models.user import User, UserRole
from app.repositories.parser_repository import ParserRepository
from app.schemas.parser import ParserCreate


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
    return definitions


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
    for definition in enabled_parser_definitions(settings):
        if await parsers.get_by_slug(definition.slug) is not None:
            continue
        await parsers.create(definition, owner.id)
        created.append(definition.slug)
    if created:
        await session.commit()
    return created
