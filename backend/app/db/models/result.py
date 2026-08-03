"""Parser 산출물과 비식별화 결과 메타데이터의 ORM 모델."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class RunResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "run_results"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_runs.id"), unique=True)
    raw_result_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    canonical_result_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    markdown_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    text_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preview_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_length: Mapped[int] = mapped_column(Integer, default=0)
    block_count: Mapped[int] = mapped_column(Integer, default=0)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    parser_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_manifest: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeidentificationInputType(StrEnum):
    ORIGINAL_FILE = "ORIGINAL_FILE"
    TEXT = "TEXT"
    MARKDOWN = "MARKDOWN"
    CANONICAL_JSON = "CANONICAL_JSON"


class DeidentificationResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deidentification_results"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_runs.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(100), default="FASOO")
    input_type: Mapped[str] = mapped_column(String(30))
    result_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    masked_file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    detected_entity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    masked_entity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
