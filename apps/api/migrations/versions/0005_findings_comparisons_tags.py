"""Persist findings, comparisons, and dataset tags."""

import sqlalchemy as sa
from alembic import op

revision = "0005_findings_comparisons_tags"
down_revision = "0004_dataset_sampling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"))
    op.create_table(
        "comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("dataset_ids_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_findings_dataset_id", "findings", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_dataset_id", table_name="findings")
    op.drop_table("findings")
    op.drop_table("comparisons")
    op.drop_column("datasets", "tags_json")
