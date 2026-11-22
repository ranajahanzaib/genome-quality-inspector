"""Store immutable analysis run results and configurations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_analysis_runs"
down_revision = "0001_create_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.String(length=36),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_analysis_runs_dataset_id", "analysis_runs", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_dataset_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
