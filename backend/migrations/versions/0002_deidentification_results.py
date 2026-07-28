"""비식별화 결과 저장소를 추가한다.

리비전 ID: 0002
이전 리비전: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("deidentification_results"):
        return
    op.create_table(
        "deidentification_results",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("input_type", sa.String(length=30), nullable=False),
        sa.Column("result_path", sa.String(length=1000), nullable=True),
        sa.Column("detected_entity_count", sa.Integer(), nullable=True),
        sa.Column("masked_entity_count", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["experiment_runs.id"],
            name=op.f("fk_deidentification_results_run_id_experiment_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deidentification_results")),
        sa.UniqueConstraint("run_id", name=op.f("uq_deidentification_results_run_id")),
    )


def downgrade() -> None:
    op.drop_table("deidentification_results")
