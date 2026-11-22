"""Record dataset source and immutable upstream revision."""

import sqlalchemy as sa
from alembic import op

revision = "0003_dataset_provenance"
down_revision = "0002_analysis_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "data_source", sa.String(length=80), server_default="user_upload", nullable=False
        ),
    )
    op.add_column(
        "datasets", sa.Column("source_revision", sa.String(length=80), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("datasets", "source_revision")
    op.drop_column("datasets", "data_source")
