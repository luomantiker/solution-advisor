"""Catalog-linked Candidate becomes historical provenance, not an active slot.

Revision ID: 0025_candidate_history_slot
Revises: 0024_evaluation_flows
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_candidate_history_slot"
down_revision = "0024_evaluation_flows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_platform_candidate_active_agent_digest", table_name="platform_candidates")
    predicate = sa.text("archived_at IS NULL AND catalog_id IS NULL")
    op.create_index("uq_platform_candidate_active_agent_digest", "platform_candidates", ["agent_id", "image_id"], unique=True,
                    postgresql_where=predicate, sqlite_where=predicate)


def downgrade() -> None:
    op.drop_index("uq_platform_candidate_active_agent_digest", table_name="platform_candidates")
    predicate = sa.text("archived_at IS NULL")
    op.create_index("uq_platform_candidate_active_agent_digest", "platform_candidates", ["agent_id", "image_id"], unique=True,
                    postgresql_where=predicate, sqlite_where=predicate)
