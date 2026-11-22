"""Store deterministic source sampling details."""

import sqlalchemy as sa
from alembic import op

revision = "0004_dataset_sampling"
down_revision = "0003_dataset_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("sampling_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("datasets", "sampling_json")
