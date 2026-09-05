"""Persist analyzer drafts and make reusable lease slots safe.

Revision ID: 0004_drafts_capacity_r2
Revises: 0003_config_leases
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_drafts_capacity_r2"
down_revision = "0003_config_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analyzer_config_drafts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("modules", sa.JSON(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.Column("change_note", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_analyzer_config_drafts_base_version", "analyzer_config_drafts", ["base_version"])
    op.create_index("ix_analyzer_config_drafts_status", "analyzer_config_drafts", ["status"])
    with op.batch_alter_table("analyzer_config_audits") as batch:
        batch.add_column(sa.Column("result", sa.String(), nullable=False, server_default="SUCCEEDED"))
        batch.add_column(sa.Column("error_code", sa.String(), nullable=True))
        batch.add_column(sa.Column("draft_id", sa.String(), nullable=True))
    with op.batch_alter_table("worker_capacity_leases") as batch:
        batch.add_column(sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("released_at", sa.DateTime(), nullable=True))
        batch.drop_constraint("uq_active_slot", type_="unique")
    # Both PostgreSQL and SQLite support partial unique indexes. Released/expired
    # leases remain auditable while a slot can be reused by a later attempt.
    op.create_index("uq_worker_active_slot", "worker_capacity_leases", ["worker_instance_id", "slot_index"], unique=True,
                    postgresql_where=sa.text("status = 'ACTIVE'"), sqlite_where=sa.text("status = 'ACTIVE'"))


def downgrade():
    raise RuntimeError("restore backup")
