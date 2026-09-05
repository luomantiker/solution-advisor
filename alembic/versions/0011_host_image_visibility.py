"""Persist global workbench visibility for discovered Host images."""
from alembic import op
import sqlalchemy as sa

revision = "0011_host_image_visibility"
down_revision = "0010_candidate_creator"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("host_images") as batch:
        batch.add_column(sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("hidden_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("hidden_at", sa.DateTime(), nullable=True))


def downgrade():
    raise RuntimeError("restore backup")
