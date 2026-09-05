"""Freeze generic model facts and version customer flow reports."""
from alembic import op
import sqlalchemy as sa

revision = "0029_flow_report_revisions"
down_revision = "0028_local_default_password"
branch_labels = depends_on = None


def upgrade():
    op.add_column("evaluation_flows", sa.Column("model_snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "report_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("flow_id", sa.String(), sa.ForeignKey("evaluation_flows.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("pdf_artifact_id", sa.String(), sa.ForeignKey("artifacts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("flow_id", "version", name="uq_report_revision_flow_version"),
    )
    op.create_index("ix_report_revisions_flow_id", "report_revisions", ["flow_id"])
    op.create_index("ix_report_revisions_pdf_artifact_id", "report_revisions", ["pdf_artifact_id"])


def downgrade():
    raise RuntimeError("Restore backup instead of destructive downgrade")
