"""S100 HostAgent candidate validation lifecycle.

Revision ID: 0023_s100_candidate_validation
Revises: 0022_binding_actual_image
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_s100_candidate_validation"
down_revision = "0022_binding_actual_image"
branch_labels = depends_on = None


def upgrade():
    op.create_table("candidate_validation_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("candidate_id", sa.String(), sa.ForeignKey("platform_candidates.id"), nullable=False),
        sa.Column("candidate_revision", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("runner_release", sa.String(), nullable=False),
        sa.Column("worker_instance_id", sa.String()), sa.Column("error_code", sa.String()),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at", sa.DateTime()), sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint("candidate_id", "candidate_revision", "attempt", name="uq_candidate_validation_revision_attempt"))
    for column in ("candidate_id", "candidate_revision", "agent_id", "status", "worker_instance_id"):
        op.create_index(f"ix_candidate_validation_tasks_{column}", "candidate_validation_tasks", [column])


def downgrade():
    raise RuntimeError("Restore backup instead of destructive downgrade")
