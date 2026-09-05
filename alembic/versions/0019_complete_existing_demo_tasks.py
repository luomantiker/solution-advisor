"""Mark synchronous DEMO fixture tasks as completed."""
from alembic import op

revision = "0019_demo_task_status"
down_revision = "0018_task_share_model_payload"
branch_labels = depends_on = None


def upgrade():
    op.execute("UPDATE evaluation_tasks SET status = 'SUCCEEDED' WHERE mode = 'DEMO' AND status = 'QUEUED'")


def downgrade():
    raise RuntimeError("restore backup")
