"""local account credentials alongside trusted SSO identities"""
from alembic import op
import sqlalchemy as sa

revision = "0016_local_account_login"
down_revision = "0015_candidate_archive"
branch_labels = depends_on = None

def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("username", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("auth_source", sa.String(length=16), nullable=False, server_default="SSO"))
        batch.add_column(sa.Column("password_updated_at", sa.DateTime(), nullable=True))
    op.create_index("uq_users_username", "users", ["username"], unique=True)

def downgrade(): raise RuntimeError("restore backup")
