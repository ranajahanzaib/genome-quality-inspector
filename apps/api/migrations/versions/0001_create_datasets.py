"""Create dataset registry."""

import sqlalchemy as sa
from alembic import op

revision = "0001_create_datasets"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("dataset_type", sa.String(length=40), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("analysis_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("datasets")
