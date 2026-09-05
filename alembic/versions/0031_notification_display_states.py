"""Persist per-account notification read and display state."""
from alembic import op
import sqlalchemy as sa


revision = "0031_notification_display_states"
down_revision = "0030_model_deletion_policy"
branch_labels = depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notification_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("notification_key", sa.String(length=96), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("account_id", "notification_key", name="uq_user_notification_state"),
    )
    op.create_index("ix_user_notification_states_account_id", "user_notification_states", ["account_id"])
    op.create_index("ix_user_notification_states_notification_key", "user_notification_states", ["notification_key"])
    op.create_index("ix_user_notification_states_deleted_at", "user_notification_states", ["deleted_at"])


def downgrade() -> None:
    raise RuntimeError("通知展示状态不可自动回退")
