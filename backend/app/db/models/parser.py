"""Parser Connector와 재사용 가능한 Preset의 ORM 모델."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionType(StrEnum):
    BUILTIN = "BUILTIN"
    HTTP = "HTTP"
    COMMAND = "COMMAND"


class ParserConnector(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "parser_connectors"

    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(150), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    execution_type: Mapped[ExecutionType] = mapped_column(Enum(ExecutionType))
    adapter_key: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    command_template: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    default_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    supported_formats: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class ParserPreset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "parser_presets"

    parser_connector_id: Mapped[UUID] = mapped_column(ForeignKey("parser_connectors.id"))
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
