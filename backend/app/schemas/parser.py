"""Parser Connector와 Preset 관리 스키마."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.parser import ExecutionType


class ParserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    execution_type: ExecutionType
    adapter_key: str
    base_url: str | None = None
    command_template: list[str] | None = None
    default_config: dict[str, Any] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    supported_formats: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


class ParserResponse(ParserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    created_by: UUID


class ParserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    description: str | None = None
    provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    execution_type: ExecutionType | None = None
    adapter_key: str | None = None
    base_url: str | None = None
    command_template: list[str] | None = None
    default_config: dict[str, Any] | None = None
    config_schema: dict[str, Any] | None = None
    capabilities: list[str] | None = None
    supported_formats: list[str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    is_active: bool | None = None


class ParserPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class ParserPresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    config: dict[str, Any] | None = None


class ParserPresetResponse(ParserPresetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parser_connector_id: UUID
    created_by: UUID
    created_at: datetime


class HealthCheckResponse(BaseModel):
    healthy: bool
    adapter_key: str
    details: dict[str, Any] = Field(default_factory=dict)
