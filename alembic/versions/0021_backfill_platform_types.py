"""Backfill global platform types from existing versioned Catalog assets."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = "0021_backfill_platform_types"
down_revision = "0020_platform_types"
branch_labels = depends_on = None

def upgrade():
    bind = op.get_bind()
    names = bind.execute(sa.text("SELECT DISTINCT platform_id FROM platform_catalogs")).scalars().all()
    for name in names:
        row = bind.execute(sa.text("SELECT id FROM platform_types WHERE name = :name"), {"name": name}).scalar()
        type_id = row or f"platform_type_{uuid4().hex}"
        if not row:
            bind.execute(sa.text("INSERT INTO platform_types (id, name, display_name, created_by) VALUES (:id, :name, :display_name, 'migration')"),
                         {"id": type_id, "name": name, "display_name": name})
        bind.execute(sa.text("UPDATE platform_catalogs SET platform_type_id = :type_id WHERE platform_id = :name AND platform_type_id IS NULL"),
                     {"type_id": type_id, "name": name})

def downgrade():
    raise RuntimeError("restore backup")
