"""자동 벤치마크와 Parser 원본 산출물 Manifest를 추가한다.

리비전 ID: 0004
이전 리비전: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("run_results"):
        columns = {column["name"] for column in inspector.get_columns("run_results")}
        if "artifact_manifest" not in columns:
            op.add_column(
                "run_results",
                sa.Column(
                    "artifact_manifest",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
            )

    if not inspector.has_table("ground_truths"):
        op.create_table(
            "ground_truths",
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("dataset_name", sa.String(length=200), nullable=False),
            sa.Column("dataset_version", sa.String(length=100), nullable=False),
            sa.Column("schema_version", sa.String(length=30), nullable=False),
            sa.Column("content_path", sa.String(length=1000), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("document_id"),
        )
        op.create_index("ix_ground_truths_document_id", "ground_truths", ["document_id"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("automated_evaluations"):
        op.create_table(
            "automated_evaluations",
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("ground_truth_id", sa.Uuid(), nullable=False),
            sa.Column("evaluator_version", sa.String(length=50), nullable=False),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("sample_counts", sa.JSON(), nullable=False),
            sa.Column("diagnostics", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(["ground_truth_id"], ["ground_truths.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["experiment_runs.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id"),
        )
        op.create_index(
            "ix_automated_evaluations_run_id",
            "automated_evaluations",
            ["run_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("automated_evaluations"):
        op.drop_index("ix_automated_evaluations_run_id", table_name="automated_evaluations")
        op.drop_table("automated_evaluations")
    if inspector.has_table("ground_truths"):
        op.drop_index("ix_ground_truths_document_id", table_name="ground_truths")
        op.drop_table("ground_truths")
    if inspector.has_table("run_results"):
        columns = {column["name"] for column in inspector.get_columns("run_results")}
        if "artifact_manifest" in columns:
            op.drop_column("run_results", "artifact_manifest")
