"""Make a shared evaluation optionally include its source model."""
from alembic import op
import sqlalchemy as sa

revision = "0018_task_share_model_payload"
down_revision = "0017_user_resource_sharing"
branch_labels = depends_on = None


def upgrade():
    op.add_column("evaluation_task_shares", sa.Column("include_model", sa.Boolean(), nullable=False, server_default=sa.false()))
    # 0017 briefly exposed direct model shares. The supported business operation is
    # now a task/report share with an explicit include_model choice, so do not carry
    # implicit model-file grants forward.
    op.execute("DELETE FROM model_asset_accesses WHERE access_kind = 'SHARED'")


def downgrade():
    raise RuntimeError("restore backup")
