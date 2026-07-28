"""Parser Connector와 Preset 영속성 처리."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.parser import ParserConnector, ParserPreset
from app.schemas.parser import ParserCreate, ParserPresetCreate, ParserPresetUpdate, ParserUpdate


class ParserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[ParserConnector]:
        result = await self.session.scalars(
            select(ParserConnector)
            .where(ParserConnector.is_active.is_(True))
            .order_by(ParserConnector.name)
        )
        return list(result)

    async def list_all(self) -> list[ParserConnector]:
        result = await self.session.scalars(select(ParserConnector).order_by(ParserConnector.name))
        return list(result)

    async def get(self, parser_id: UUID) -> ParserConnector | None:
        return await self.session.get(ParserConnector, parser_id)

    async def get_by_slug(self, slug: str) -> ParserConnector | None:
        return await self.session.scalar(
            select(ParserConnector).where(ParserConnector.slug == slug)
        )

    async def create(self, data: ParserCreate, user_id: UUID) -> ParserConnector:
        connector = ParserConnector(**data.model_dump(), created_by=user_id)
        self.session.add(connector)
        await self.session.flush()
        return connector

    async def update(
        self,
        connector: ParserConnector,
        data: ParserUpdate,
    ) -> ParserConnector:
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(connector, key, value)
        await self.session.flush()
        return connector

    async def get_preset(self, preset_id: UUID) -> ParserPreset | None:
        return await self.session.get(ParserPreset, preset_id)

    async def list_presets(self, parser_id: UUID) -> list[ParserPreset]:
        result = await self.session.scalars(
            select(ParserPreset)
            .where(ParserPreset.parser_connector_id == parser_id)
            .order_by(ParserPreset.created_at, ParserPreset.name)
        )
        return list(result)

    async def create_preset(
        self,
        parser_id: UUID,
        data: ParserPresetCreate,
        user_id: UUID,
    ) -> ParserPreset:
        preset = ParserPreset(
            parser_connector_id=parser_id,
            created_by=user_id,
            **data.model_dump(),
        )
        self.session.add(preset)
        await self.session.flush()
        return preset

    async def update_preset(
        self,
        preset: ParserPreset,
        data: ParserPresetUpdate,
    ) -> ParserPreset:
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(preset, key, value)
        await self.session.flush()
        return preset

    async def delete_preset(self, preset: ParserPreset) -> None:
        await self.session.delete(preset)
