"""X5 board smoke task lineage."""

from alembic import op
import sqlalchemy as sa


revision = "0007_x5_board_smoke"
down_revision = "0006_x5_real_tasks"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_tasks") as batch:
        batch.add_column(sa.Column("task_kind", sa.String(), nullable=False, server_default="X5_COMPILE"))
        batch.add_column(sa.Column("source_task_id", sa.String(), nullable=True))
    op.create_index("ix_evaluation_tasks_task_kind", "evaluation_tasks", ["task_kind"])
    op.create_index("ix_evaluation_tasks_source_task_id", "evaluation_tasks", ["source_task_id"])


def downgrade():
    raise RuntimeError("restore backup")
