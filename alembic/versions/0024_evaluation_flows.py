"""User-visible platform-neutral evaluation flows."""
from alembic import op
import sqlalchemy as sa

revision = "0024_evaluation_flows"
down_revision = "0023_s100_candidate_validation"
branch_labels = depends_on = None

def upgrade():
    op.create_table("evaluation_flows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("model_profile_id", sa.String(), sa.ForeignKey("model_profiles.id"), nullable=False),
        sa.Column("owner_subject", sa.String(), nullable=False), sa.Column("preset", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("platform_snapshots", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_evaluation_flows_model_profile_id", "evaluation_flows", ["model_profile_id"])
    op.create_index("ix_evaluation_flows_owner_subject", "evaluation_flows", ["owner_subject"])
    op.create_index("ix_evaluation_flows_status", "evaluation_flows", ["status"])
    # SQLite (used by test/dev) cannot ALTER TABLE to add a foreign key.
    # The immutable flow id is indexed; referential lifecycle is enforced by
    # the application because historical tasks must remain readable.
    op.add_column("evaluation_tasks", sa.Column("flow_id", sa.String(), nullable=True))
    op.create_index("ix_evaluation_tasks_flow_id", "evaluation_tasks", ["flow_id"])

def downgrade():
    raise RuntimeError("Restore backup instead of destructive downgrade")
