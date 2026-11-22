"""Store sequence-to-taxonomy metadata mappings."""

import sqlalchemy as sa
from alembic import op

revision = "0006_taxonomy_mappings"
down_revision = "0005_findings_comparisons_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "taxonomy_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_id", sa.String(500), nullable=False),
        sa.Column("taxon_name", sa.String(500), nullable=False),
        sa.Column("taxon_id", sa.String(80), nullable=True),
        sa.Column("rank", sa.String(80), nullable=True),
        sa.Column("source", sa.String(120), nullable=False),
        sa.Column("release", sa.String(120), nullable=True),
    )
    op.create_index("ix_taxonomy_mappings_dataset_id", "taxonomy_mappings", ["dataset_id"])
    op.create_index("ix_taxonomy_mappings_sequence_id", "taxonomy_mappings", ["sequence_id"])


def downgrade() -> None:
    op.drop_index("ix_taxonomy_mappings_sequence_id", table_name="taxonomy_mappings")
    op.drop_index("ix_taxonomy_mappings_dataset_id", table_name="taxonomy_mappings")
    op.drop_table("taxonomy_mappings")
