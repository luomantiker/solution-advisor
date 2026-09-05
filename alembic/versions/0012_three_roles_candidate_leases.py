"""Three persisted roles and Candidate collaboration leases."""
from alembic import op
import sqlalchemy as sa

revision = "0012_three_roles_candidate"
down_revision = "0011_host_image_visibility"
branch_labels = depends_on = None

def upgrade():
    op.create_table("users", sa.Column("id", sa.String(), primary_key=True), sa.Column("display_name", sa.String(), nullable=False), sa.Column("role", sa.String(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("uq_users_super_admin", "users", ["role"], unique=True, postgresql_where=sa.text("role = 'SUPER_ADMIN'"), sqlite_where=sa.text("role = 'SUPER_ADMIN'"))
    # Historical records had a fixed `admin` actor.  Preserve their provenance without
    # granting an implicit production identity or leaving a fourth role behind.
    op.execute(sa.text("INSERT INTO users (id, display_name, role, active) VALUES ('system-admin', '历史系统管理员', 'ADMIN', true)"))
    op.execute(sa.text("UPDATE platform_candidates SET created_by = 'system-admin' WHERE created_by = 'admin'"))
    with op.batch_alter_table("platform_candidates") as batch:
        batch.add_column(sa.Column("claimed_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("claimed_by_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_handled_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("last_handled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_platform_candidates_claimed_by", "platform_candidates", ["claimed_by"])
    op.create_table("candidate_history", sa.Column("id", sa.String(), primary_key=True), sa.Column("candidate_id", sa.String(), sa.ForeignKey("platform_candidates.id"), nullable=False), sa.Column("actor", sa.String(), nullable=False), sa.Column("action", sa.String(), nullable=False), sa.Column("old_revision", sa.Integer(), nullable=False), sa.Column("new_revision", sa.Integer(), nullable=False), sa.Column("reason", sa.String(), nullable=True), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_index("ix_candidate_history_candidate_id", "candidate_history", ["candidate_id"])
def downgrade(): raise RuntimeError("restore backup")
