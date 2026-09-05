"""Persist global platform types and Candidate version declarations."""
from alembic import op
import sqlalchemy as sa

revision = "0020_platform_types"
down_revision = "0019_demo_task_status"
branch_labels = depends_on = None

def upgrade():
    op.create_table("platform_types", sa.Column("id", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False, unique=True),
                    sa.Column("display_name", sa.String(), nullable=False), sa.Column("created_by", sa.String(), nullable=False, server_default="admin"),
                    sa.Column("created_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("platform_catalogs") as batch:
        batch.add_column(sa.Column("platform_type_id", sa.String(), nullable=True))
    with op.batch_alter_table("platform_candidates") as batch:
        batch.add_column(sa.Column("platform_type_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("target_version", sa.String(), nullable=True))
    op.create_index("ix_platform_catalogs_platform_type_id", "platform_catalogs", ["platform_type_id"])
    op.create_index("ix_platform_candidates_platform_type_id", "platform_candidates", ["platform_type_id"])

def downgrade():
    raise RuntimeError("restore backup")
