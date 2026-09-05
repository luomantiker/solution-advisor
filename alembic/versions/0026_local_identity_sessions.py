"""local personnel lifecycle, identity links and opaque sessions

Revision ID: 0026_local_identity_sessions
Revises: 0025_candidate_history_slot
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_local_identity_sessions"
down_revision = "0025_candidate_history_slot"
branch_labels = depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"))
        batch.add_column(sa.Column("quota", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("capability_scope", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("auth_provider_type", sa.String(length=24), nullable=False, server_default="SSO"))
        batch.add_column(sa.Column("issuer", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("identity_subject", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_status", "users", ["status"])
    op.create_table("identity_links", sa.Column("id", sa.String(), primary_key=True),
                    sa.Column("account_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("provider_type", sa.String(length=24), nullable=False),
                    sa.Column("issuer", sa.String(length=255), nullable=True),
                    sa.Column("subject", sa.String(length=255), nullable=False),
                    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_index("ix_identity_links_account_id", "identity_links", ["account_id"])
    op.create_index("uq_identity_link", "identity_links", ["provider_type", "issuer", "subject"], unique=True)
    op.create_table("authentication_sessions", sa.Column("id", sa.String(length=96), primary_key=True),
                    sa.Column("account_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
                    sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("revoked_at", sa.DateTime(), nullable=True),
                    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.create_index("ix_authentication_sessions_account_id", "authentication_sessions", ["account_id"])
    op.create_index("ix_authentication_sessions_expires_at", "authentication_sessions", ["expires_at"])
    op.create_index("ix_authentication_sessions_revoked_at", "authentication_sessions", ["revoked_at"])
    op.create_table("account_audits", sa.Column("id", sa.String(), primary_key=True), sa.Column("actor", sa.String(), nullable=False),
                    sa.Column("account_id", sa.String(), nullable=False), sa.Column("action", sa.String(), nullable=False),
                    sa.Column("old_revision", sa.Integer(), nullable=True), sa.Column("new_revision", sa.Integer(), nullable=True),
                    sa.Column("reason", sa.String(length=500), nullable=True), sa.Column("summary", sa.String(length=500), nullable=False),
                    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_index("ix_account_audits_actor", "account_audits", ["actor"])
    op.create_index("ix_account_audits_account_id", "account_audits", ["account_id"])
    op.create_index("ix_account_audits_action", "account_audits", ["action"])


def downgrade() -> None:
    raise RuntimeError("restore backup")
