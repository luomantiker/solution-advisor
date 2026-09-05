"""Add the super-admin policy controlling deletion of evaluated models."""
from alembic import op
import sqlalchemy as sa


revision = "0030_model_deletion_policy"
down_revision = "0029_flow_report_revisions"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=96), primary_key=True),
        sa.Column("bool_value", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade():
    raise RuntimeError("Restore backup instead of destructive downgrade")
