"""실험과 Parser Run의 ORM 모델 및 상태 열거형."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ParseStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class DeidentificationStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class Experiment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "experiments"

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    run_deidentification: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "experiment_runs"

    experiment_id: Mapped[UUID] = mapped_column(ForeignKey("experiments.id"), index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"))
    parser_connector_id: Mapped[UUID] = mapped_column(ForeignKey("parser_connectors.id"))
    parser_preset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("parser_presets.id"), nullable=True
    )
    parser_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    parse_status: Mapped[ParseStatus] = mapped_column(
        Enum(ParseStatus), default=ParseStatus.PENDING, index=True
    )
    deidentification_status: Mapped[DeidentificationStatus] = mapped_column(
        Enum(DeidentificationStatus), default=DeidentificationStatus.NOT_REQUESTED
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
