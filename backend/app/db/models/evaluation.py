"""Run 수동 평가를 위한 ORM 모델과 데이터베이스 제약조건."""

from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ManualEvaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "manual_evaluations"
    __table_args__ = (
        UniqueConstraint("run_id", "evaluator_id"),
        CheckConstraint(
            "text_score IS NULL OR text_score BETWEEN 1 AND 5", name="text_score_range"
        ),
        CheckConstraint(
            "table_score IS NULL OR table_score BETWEEN 1 AND 5", name="table_score_range"
        ),
        CheckConstraint(
            "reading_order_score IS NULL OR reading_order_score BETWEEN 1 AND 5",
            name="reading_order_score_range",
        ),
        CheckConstraint(
            "deidentification_score IS NULL OR deidentification_score BETWEEN 1 AND 5",
            name="deidentification_score_range",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("experiment_runs.id"))
    evaluator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    text_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reading_order_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deidentification_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
