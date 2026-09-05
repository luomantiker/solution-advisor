"""REAL platform task lifecycle fields."""
from alembic import op
import sqlalchemy as sa
revision="0006_x5_real_tasks"; down_revision="0005_worker_instances"; branch_labels=depends_on=None
def upgrade():
    with op.batch_alter_table("evaluation_tasks") as b:
        b.add_column(sa.Column("status", sa.String(), nullable=False, server_default="QUEUED"))
        b.add_column(sa.Column("worker_instance_id", sa.String(), nullable=True))
        b.add_column(sa.Column("attempt_id", sa.String(), nullable=True))
        b.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"))
        b.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("error_code", sa.String(), nullable=True))
    op.create_index("ix_evaluation_tasks_status", "evaluation_tasks", ["status"])
    op.create_index("ix_evaluation_tasks_worker_instance_id", "evaluation_tasks", ["worker_instance_id"])
    op.create_index("ix_evaluation_tasks_attempt_id", "evaluation_tasks", ["attempt_id"])
def downgrade(): raise RuntimeError("restore backup")
