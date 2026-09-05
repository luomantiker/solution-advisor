"""Persist ordinary-user ownership for models and evaluation tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0013_user_owned_assets"
down_revision = "0012_three_roles_candidate"
branch_labels = depends_on = None

def upgrade():
    with op.batch_alter_table("model_assets") as batch:
        batch.add_column(sa.Column("owner_subject", sa.String(), nullable=False, server_default="system-admin"))
        batch.create_index("ix_model_assets_owner_subject", ["owner_subject"])
    with op.batch_alter_table("evaluation_tasks") as batch:
        batch.add_column(sa.Column("owner_subject", sa.String(), nullable=False, server_default="system-admin"))
        batch.create_index("ix_evaluation_tasks_owner_subject", ["owner_subject"])

def downgrade(): raise RuntimeError("restore backup")
