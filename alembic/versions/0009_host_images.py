"""Separate HostAgent image discovery from platform candidates."""
from alembic import op
import sqlalchemy as sa

revision = "0009_host_images"
down_revision = "0008_platform_catalog_bindings"
branch_labels = depends_on = None

def upgrade():
    op.create_table("host_images", sa.Column("id", sa.String(), primary_key=True), sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False), sa.Column("image_ref", sa.String(), nullable=False), sa.Column("image_id", sa.String(), nullable=False), sa.Column("toolchain_version", sa.String()), sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("last_seen_at", sa.DateTime(), server_default=sa.func.now()), sa.UniqueConstraint("agent_id", "image_id", name="uq_host_image_agent_digest"))
    op.create_index("ix_host_images_agent_id", "host_images", ["agent_id"]); op.create_index("ix_host_images_image_id", "host_images", ["image_id"])

def downgrade(): raise RuntimeError("restore backup")
