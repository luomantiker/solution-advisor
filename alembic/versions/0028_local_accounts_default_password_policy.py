"""Make legacy local accounts active without forced first-login password change."""

from alembic import op


revision = "0028_local_default_password"
down_revision = "0027_candidate_manual_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This is a deliberate product-policy migration. Existing local accounts
    # retain their already stored password hash; only the forced-change gate is
    # removed, so users can log in with the password already assigned to them.
    op.execute("UPDATE users SET status = 'ACTIVE', active = true, must_change_password = false "
               "WHERE auth_source = 'LOCAL' AND status = 'PENDING_ACTIVATION'")


def downgrade() -> None:
    raise RuntimeError("本地账号密码策略迁移不可自动回退")
