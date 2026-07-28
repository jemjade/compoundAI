"""Parser Connector·상태 확인·Preset 관리 Endpoint."""

from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, SessionDep
from app.db.models.user import UserRole
from app.repositories.parser_repository import ParserRepository
from app.schemas.parser import (
    HealthCheckResponse,
    ParserCreate,
    ParserPresetCreate,
    ParserPresetResponse,
    ParserPresetUpdate,
    ParserResponse,
    ParserUpdate,
)
from app.services.parser_service import ParserService

router = APIRouter(prefix="/parsers", tags=["parsers"])


@router.get("", response_model=list[ParserResponse])
async def list_parsers(
    user: CurrentUser,
    session: SessionDep,
    include_inactive: bool = Query(default=False),
) -> list[ParserResponse]:
    if include_inactive and user.role == UserRole.ADMIN:
        parsers = await ParserRepository(session).list_all()
    else:
        parsers = await ParserRepository(session).list_active()
    return [ParserResponse.model_validate(parser) for parser in parsers]


@router.post("", response_model=ParserResponse, status_code=status.HTTP_201_CREATED)
async def create_parser(
    data: ParserCreate,
    user: CurrentUser,
    session: SessionDep,
) -> ParserResponse:
    parser = await ParserService(session).create(data, user)
    return ParserResponse.model_validate(parser)


@router.get("/{parser_id}", response_model=ParserResponse)
async def get_parser(
    parser_id: UUID,
    _: CurrentUser,
    session: SessionDep,
) -> ParserResponse:
    return ParserResponse.model_validate(await ParserService(session).get(parser_id))


@router.patch("/{parser_id}", response_model=ParserResponse)
async def update_parser(
    parser_id: UUID,
    data: ParserUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> ParserResponse:
    connector = await ParserService(session).update(parser_id, data, user)
    return ParserResponse.model_validate(connector)


@router.delete("/{parser_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parser(
    parser_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    await ParserService(session).disable(parser_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{parser_id}/health-check", response_model=HealthCheckResponse)
async def health_check(
    parser_id: UUID,
    _: CurrentUser,
    session: SessionDep,
) -> HealthCheckResponse:
    return HealthCheckResponse.model_validate(await ParserService(session).health_check(parser_id))


@router.post(
    "/{parser_id}/presets",
    response_model=ParserPresetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_preset(
    parser_id: UUID,
    data: ParserPresetCreate,
    user: CurrentUser,
    session: SessionDep,
) -> ParserPresetResponse:
    preset = await ParserService(session).create_preset(parser_id, data, user)
    return ParserPresetResponse.model_validate(preset)


@router.get("/{parser_id}/presets", response_model=list[ParserPresetResponse])
async def list_presets(
    parser_id: UUID,
    _: CurrentUser,
    session: SessionDep,
) -> list[ParserPresetResponse]:
    presets = await ParserService(session).list_presets(parser_id)
    return [ParserPresetResponse.model_validate(preset) for preset in presets]


preset_router = APIRouter(prefix="/parser-presets", tags=["parser-presets"])


@preset_router.patch("/{preset_id}", response_model=ParserPresetResponse)
async def update_preset(
    preset_id: UUID,
    data: ParserPresetUpdate,
    user: CurrentUser,
    session: SessionDep,
) -> ParserPresetResponse:
    preset = await ParserService(session).update_preset(preset_id, data, user)
    return ParserPresetResponse.model_validate(preset)


@preset_router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: UUID,
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    await ParserService(session).delete_preset(preset_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
