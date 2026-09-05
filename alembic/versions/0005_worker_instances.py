"""Persist registered Worker Host instances."""
from alembic import op
import sqlalchemy as sa

revision = "0005_worker_instances"
down_revision = "0004_drafts_capacity_r2"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("worker_instances", sa.Column("id", sa.String(), primary_key=True), sa.Column("worker_type", sa.String(), nullable=False), sa.Column("image_ref", sa.String(), nullable=False), sa.Column("image_id", sa.String()), sa.Column("toolchain_version", sa.String()), sa.Column("platform_package_version", sa.String()), sa.Column("capabilities", sa.JSON(), nullable=False), sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("health", sa.String(), nullable=False), sa.Column("last_heartbeat_at", sa.DateTime()), sa.Column("last_error", sa.String()), sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))

def downgrade(): raise RuntimeError("restore backup")
