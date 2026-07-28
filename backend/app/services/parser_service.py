"""Parser Connector 검증·관리·상태 확인·Preset 처리."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.parsers.command_utils import validate_command_template
from app.adapters.parsers.registry import PARSER_ADAPTERS, get_parser_adapter
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.models.parser import ExecutionType, ParserConnector, ParserPreset
from app.db.models.user import User, UserRole
from app.repositories.parser_repository import ParserRepository
from app.schemas.parser import (
    ParserCreate,
    ParserPresetCreate,
    ParserPresetUpdate,
    ParserUpdate,
)
from app.utils.config_validation import validate_config_schema, validate_parser_config

ADAPTER_EXECUTION_TYPES = {
    "mock_parser": ExecutionType.BUILTIN,
    "pp_structure_v3": ExecutionType.BUILTIN,
    "synap_http": ExecutionType.HTTP,
    "generic_http": ExecutionType.HTTP,
    "docling_command": ExecutionType.COMMAND,
    "generic_command": ExecutionType.COMMAND,
}


class ParserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.parsers = ParserRepository(session)

    async def create(self, data: ParserCreate, user: User) -> ParserConnector:
        self._require_admin(user)
        self._validate_connector(data)
        try:
            connector = await self.parsers.create(data, user.id)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("PARSER_SLUG_EXISTS", "Parser slug already exists.", 409) from exc
        return connector

    def _require_admin(self, user: User) -> None:
        if user.role != UserRole.ADMIN:
            raise AppError("ADMIN_REQUIRED", "Only administrators can manage parsers.", 403)

    def _validate_connector(self, data: ParserCreate) -> None:
        expected_type = ADAPTER_EXECUTION_TYPES.get(data.adapter_key)
        if data.adapter_key not in PARSER_ADAPTERS or expected_type is None:
            raise AppError(
                "UNSUPPORTED_PARSER_ADAPTER",
                f"Unsupported parser adapter: {data.adapter_key}",
                422,
            )
        if data.execution_type != expected_type:
            raise AppError(
                "PARSER_CONFIGURATION_INVALID",
                f"{data.adapter_key} requires execution_type {expected_type.value}.",
                422,
            )
        if data.execution_type == ExecutionType.HTTP:
            if not data.base_url or not data.base_url.startswith(("http://", "https://")):
                raise AppError(
                    "PARSER_CONFIGURATION_INVALID",
                    "HTTP parser requires an http(s) base_url.",
                    422,
                )
        if data.execution_type == ExecutionType.COMMAND:
            validate_command_template(
                data.command_template,
                get_settings().command_allowed_executables,
            )
        validate_config_schema(data.config_schema)
        validate_parser_config(data.config_schema, data.default_config)

    async def get(self, parser_id: UUID) -> ParserConnector:
        connector = await self.parsers.get(parser_id)
        if connector is None:
            raise AppError("PARSER_NOT_FOUND", "Parser not found.", 404)
        return connector

    async def update(
        self,
        parser_id: UUID,
        data: ParserUpdate,
        user: User,
    ) -> ParserConnector:
        self._require_admin(user)
        connector = await self.get(parser_id)
        merged = ParserCreate.model_validate(
            {
                **{key: getattr(connector, key) for key in ParserCreate.model_fields},
                **data.model_dump(exclude_unset=True),
            }
        )
        self._validate_connector(merged)
        try:
            connector = await self.parsers.update(connector, data)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("PARSER_SLUG_EXISTS", "Parser slug already exists.", 409) from exc
        return connector

    async def disable(self, parser_id: UUID, user: User) -> None:
        self._require_admin(user)
        connector = await self.get(parser_id)
        connector.is_active = False
        await self.session.commit()

    async def health_check(self, parser_id: UUID) -> dict:
        connector = await self.get(parser_id)
        adapter = get_parser_adapter(connector)
        details = await adapter.health_check()
        return {
            "healthy": bool(details.get("healthy")),
            "adapter_key": connector.adapter_key,
            "details": details,
        }

    async def list_presets(self, parser_id: UUID) -> list[ParserPreset]:
        await self.get(parser_id)
        return await self.parsers.list_presets(parser_id)

    async def create_preset(
        self,
        parser_id: UUID,
        data: ParserPresetCreate,
        user: User,
    ) -> ParserPreset:
        connector = await self.get(parser_id)
        validate_parser_config(connector.config_schema, data.config)
        preset = await self.parsers.create_preset(parser_id, data, user.id)
        await self.session.commit()
        return preset

    async def update_preset(
        self,
        preset_id: UUID,
        data: ParserPresetUpdate,
        user: User,
    ) -> ParserPreset:
        preset = await self.parsers.get_preset(preset_id)
        if preset is None:
            raise AppError("PARSER_PRESET_NOT_FOUND", "Parser preset not found.", 404)
        if preset.created_by != user.id and user.role != UserRole.ADMIN:
            raise AppError("PRESET_ACCESS_DENIED", "You cannot edit this preset.", 403)
        connector = await self.get(preset.parser_connector_id)
        if data.config is not None:
            validate_parser_config(connector.config_schema, data.config)
        preset = await self.parsers.update_preset(preset, data)
        await self.session.commit()
        return preset

    async def delete_preset(
        self,
        preset_id: UUID,
        user: User,
    ) -> None:
        preset = await self.parsers.get_preset(preset_id)
        if preset is None:
            raise AppError("PARSER_PRESET_NOT_FOUND", "Parser preset not found.", 404)
        if preset.created_by != user.id and user.role != UserRole.ADMIN:
            raise AppError("PRESET_ACCESS_DENIED", "You cannot delete this preset.", 403)
        await self.parsers.delete_preset(preset)
        await self.session.commit()
