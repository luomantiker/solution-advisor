"""production persistence and evidence foundation

Revision ID: 0001_persistence_foundation
Revises:
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_persistence_foundation"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "artifacts" not in tables:
        op.create_table("artifacts",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("uri", sa.String(), nullable=False, unique=True),
            sa.Column("sha256", sa.String(64), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("content_type", sa.String(), nullable=False), sa.Column("storage_backend", sa.String(), nullable=False),
            sa.Column("visibility", sa.String(), nullable=False, server_default="INTERNAL"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
        op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])
    if "model_assets" not in tables:
        op.create_table("model_assets",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("original_filename", sa.String(), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("storage_path", sa.String(), nullable=True), sa.Column("artifact_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
        op.create_index("ix_model_assets_sha256", "model_assets", ["sha256"])
        op.create_index("ix_model_assets_artifact_id", "model_assets", ["artifact_id"])
    elif "artifact_id" not in _columns("model_assets"):
        op.add_column("model_assets", sa.Column("artifact_id", sa.String(), nullable=True))
        op.create_index("ix_model_assets_artifact_id", "model_assets", ["artifact_id"])
    if "model_profiles" not in tables:
        op.create_table("model_profiles",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("model_asset_id", sa.String(), nullable=False),
            sa.Column("onnx_sha256", sa.String(64), nullable=False), sa.Column("analyzer_version", sa.String(), nullable=False),
            sa.Column("analysis", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("onnx_sha256", "analyzer_version", name="uq_profile_cache"))
        op.create_index("ix_model_profiles_model_asset_id", "model_profiles", ["model_asset_id"])
        op.create_index("ix_model_profiles_onnx_sha256", "model_profiles", ["onnx_sha256"])
    if "task_snapshots" not in tables:
        op.create_table("task_snapshots",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("model_asset_id", sa.String(), nullable=False), sa.Column("model_profile_id", sa.String(), nullable=False),
            sa.Column("evaluation_template_version", sa.String(), nullable=False), sa.Column("report_template_version", sa.String(), nullable=False),
            sa.Column("platform_package_versions", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
        op.create_index("ix_task_snapshots_task_id", "task_snapshots", ["task_id"])
        op.create_index("ix_task_snapshots_model_asset_id", "task_snapshots", ["model_asset_id"])
        op.create_index("ix_task_snapshots_model_profile_id", "task_snapshots", ["model_profile_id"])
    if "evaluation_tasks" not in tables:
        op.create_table("evaluation_tasks",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("model_profile_id", sa.String(), nullable=False),
            sa.Column("mode", sa.String(), nullable=False), sa.Column("platforms", sa.JSON(), nullable=False), sa.Column("snapshot_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
        op.create_index("ix_evaluation_tasks_model_profile_id", "evaluation_tasks", ["model_profile_id"])
        op.create_index("ix_evaluation_tasks_snapshot_id", "evaluation_tasks", ["snapshot_id"])
    elif "snapshot_id" not in _columns("evaluation_tasks"):
        op.add_column("evaluation_tasks", sa.Column("snapshot_id", sa.String(), nullable=True))
        op.create_index("ix_evaluation_tasks_snapshot_id", "evaluation_tasks", ["snapshot_id"])
    if "evaluation_results" not in tables:
        op.create_table("evaluation_results",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("platform", sa.String(), nullable=False), sa.Column("source", sa.String(), nullable=False),
            sa.Column("fixture_version", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("schema_version", sa.String(), nullable=False, server_default="1.0.0"),
            sa.Column("common_result", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("platform_result", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default="[]"))
        op.create_index("ix_evaluation_results_task_id", "evaluation_results", ["task_id"])
    else:
        columns = _columns("evaluation_results")
        for name, column, default in (("schema_version", sa.String(), "1.0.0"), ("common_result", sa.JSON(), "{}"),
                                      ("platform_result", sa.JSON(), "{}"), ("evidence_ids", sa.JSON(), "[]")):
            if name not in columns:
                op.add_column("evaluation_results", sa.Column(name, column, nullable=False, server_default=default))
    if "evidences" not in tables:
        op.create_table("evidences",
            sa.Column("id", sa.String(), primary_key=True), sa.Column("evidence_type", sa.String(), nullable=False),
            sa.Column("phase", sa.String(), nullable=False), sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("platform", sa.String(), nullable=True), sa.Column("artifact_id", sa.String(), nullable=False),
            sa.Column("toolchain_version", sa.String(), nullable=True), sa.Column("rule_package_version", sa.String(), nullable=True),
            sa.Column("visibility", sa.String(), nullable=False, server_default="INTERNAL"),
            sa.Column("produced_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")))
        op.create_index("ix_evidences_task_id", "evidences", ["task_id"])
        op.create_index("ix_evidences_artifact_id", "evidences", ["artifact_id"])


def downgrade() -> None:
    # Existing MVP databases may predate Alembic; destructive downgrade is intentionally unsupported.
    raise RuntimeError("Downgrade is not supported; restore a verified database backup instead.")
