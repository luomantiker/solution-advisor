"""Per-user logical model ownership and explicit task sharing."""
from alembic import op
import sqlalchemy as sa

revision = "0017_user_resource_sharing"
down_revision = "0016_local_account_login"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "model_asset_accesses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_asset_id", sa.String(), sa.ForeignKey("model_assets.id"), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("access_kind", sa.String(length=16), nullable=False, server_default="OWNER"),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("model_asset_id", "subject", name="uq_model_asset_access_subject"),
    )
    op.create_index("ix_model_asset_accesses_model_asset_id", "model_asset_accesses", ["model_asset_id"])
    op.create_index("ix_model_asset_accesses_subject", "model_asset_accesses", ["subject"])
    op.create_table(
        "resource_access_audits",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("resource_type", sa.String(length=16), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("actor_subject", sa.String(), nullable=False),
        sa.Column("recipient_subject", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_resource_access_audits_resource_type", "resource_access_audits", ["resource_type"])
    op.create_index("ix_resource_access_audits_resource_id", "resource_access_audits", ["resource_id"])
    op.create_index("ix_resource_access_audits_actor_subject", "resource_access_audits", ["actor_subject"])
    op.create_index("ix_resource_access_audits_recipient_subject", "resource_access_audits", ["recipient_subject"])
    op.execute("INSERT INTO model_asset_accesses (id, model_asset_id, subject, access_kind, granted_by) "
               "SELECT 'model_access_' || id, id, owner_subject, 'OWNER', owner_subject FROM model_assets")
    op.create_table(
        "evaluation_task_shares",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("evaluation_tasks.id"), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("shared_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("task_id", "subject", name="uq_evaluation_task_share_subject"),
    )
    op.create_index("ix_evaluation_task_shares_task_id", "evaluation_task_shares", ["task_id"])
    op.create_index("ix_evaluation_task_shares_subject", "evaluation_task_shares", ["subject"])


def downgrade():
    raise RuntimeError("restore backup")
