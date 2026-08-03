"""Ground Truth와 자동 정량 평가 결과를 영속화하는 모델."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GroundTruth(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ground_truths"
    __table_args__ = (UniqueConstraint("document_id"),)

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    dataset_name: Mapped[str] = mapped_column(String(200))
    dataset_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(30), default="1.0")
    content_path: Mapped[str] = mapped_column(String(1000))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class AutomatedEvaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "automated_evaluations"
    __table_args__ = (UniqueConstraint("run_id"),)

    run_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_runs.id"), index=True)
    ground_truth_id: Mapped[UUID] = mapped_column(ForeignKey("ground_truths.id"))
    evaluator_version: Mapped[str] = mapped_column(String(50))
    metrics: Mapped[dict[str, float | None]] = mapped_column(JSON, default=dict)
    sample_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
