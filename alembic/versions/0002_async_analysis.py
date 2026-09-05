"""async common analyzer tasks

Revision ID: 0002_async_analysis
Revises: 0001_persistence_foundation
"""
from alembic import op
import sqlalchemy as sa
revision = "0002_async_analysis"; down_revision = "0001_persistence_foundation"; branch_labels = depends_on = None
def upgrade():
    op.create_table("analyzer_configurations", sa.Column("id", sa.String(), primary_key=True), sa.Column("revision", sa.Integer(), nullable=False), sa.Column("modules", sa.JSON(), nullable=False), sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("analysis_tasks", sa.Column("id", sa.String(), primary_key=True), sa.Column("model_asset_id", sa.String(), nullable=False), sa.Column("artifact_id", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("attempt_id", sa.String()), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("lease_expires_at", sa.DateTime()), sa.Column("config_snapshot", sa.JSON(), nullable=False), sa.Column("profile_id", sa.String()), sa.Column("error_code", sa.String()), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("started_at", sa.DateTime()), sa.Column("finished_at", sa.DateTime()))
    op.create_index("ix_analysis_tasks_status", "analysis_tasks", ["status"]); op.create_index("ix_analysis_tasks_model_asset_id", "analysis_tasks", ["model_asset_id"])
    op.create_table("analysis_events", sa.Column("id", sa.String(), primary_key=True), sa.Column("task_id", sa.String(), nullable=False), sa.Column("attempt_id", sa.String()), sa.Column("stage_id", sa.String(), nullable=False), sa.Column("module_id", sa.String()), sa.Column("status", sa.String(), nullable=False), sa.Column("progress_percent", sa.Integer(), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("occurred_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("analyzer_version", sa.String(), nullable=False), sa.Column("result_ref", sa.String()), sa.Column("error_code", sa.String()))
    op.create_index("ix_analysis_events_task_id", "analysis_events", ["task_id"])
def downgrade(): raise RuntimeError("Restore backup instead of destructive downgrade")
