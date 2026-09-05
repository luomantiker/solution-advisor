"""Record the image actually selected for a cross-host Binding."""
from alembic import op
import sqlalchemy as sa

revision = "0022_binding_actual_image"
down_revision = "0021_backfill_platform_types"
branch_labels = depends_on = None


def upgrade():
    op.add_column("platform_bindings", sa.Column("actual_image_ref", sa.String(), nullable=True))
    op.add_column("platform_bindings", sa.Column("actual_image_digest", sa.String(), nullable=True))
    op.add_column("platform_bindings", sa.Column("image_match_status", sa.String(), nullable=False, server_default="MATCH"))
    op.execute("UPDATE platform_bindings SET actual_image_digest = image_lock_version WHERE actual_image_digest IS NULL")


def downgrade():
    op.drop_column("platform_bindings", "image_match_status")
    op.drop_column("platform_bindings", "actual_image_digest")
    op.drop_column("platform_bindings", "actual_image_ref")
