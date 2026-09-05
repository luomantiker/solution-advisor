"""Candidate claims are manual and have no natural expiry.

Revision ID: 0027_candidate_manual_claims
Revises: 0026_local_identity_sessions
"""
from alembic import op


revision = "0027_candidate_manual_claims"
down_revision = "0026_local_identity_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the legacy column so old audit snapshots remain readable, but make
    # it explicitly non-authoritative and remove every remaining deadline.
    op.execute("UPDATE platform_candidates SET lease_expires_at = NULL")


def downgrade() -> None:
    raise RuntimeError("Candidate claim semantics require restore from backup")
