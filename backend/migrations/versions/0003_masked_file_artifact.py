"""마스킹된 원본 파일 산출물 경로를 추가한다.

리비전 ID: 0003
이전 리비전: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("deidentification_results"):
        return
    columns = {column["name"] for column in inspector.get_columns("deidentification_results")}
    if "masked_file_path" not in columns:
        op.add_column(
            "deidentification_results",
            sa.Column("masked_file_path", sa.String(length=1000), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("deidentification_results"):
        return
    columns = {column["name"] for column in inspector.get_columns("deidentification_results")}
    if "masked_file_path" in columns:
        op.drop_column("deidentification_results", "masked_file_path")
