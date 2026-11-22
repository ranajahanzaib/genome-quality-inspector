"""Persist optional scientific tool runs."""

import sqlalchemy as sa
from alembic import op

revision = "0007_tool_runs"
down_revision = "0006_taxonomy_mappings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tool_runs_dataset_id", "tool_runs", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_runs_dataset_id", table_name="tool_runs")
    op.drop_table("tool_runs")
