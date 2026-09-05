"""Add the governance-facing person source classification.

Revision ID: 0032_people_source
Revises: 0031_notification_display_states
"""
from alembic import op
import sqlalchemy as sa

revision = "0032_people_source"
down_revision = "0031_notification_display_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("person_source", sa.String(length=24), nullable=True))
    op.execute("UPDATE users SET person_source = 'SYSTEM_BUILTIN' WHERE role = 'SUPER_ADMIN'")
    # 历史上由自动化、浏览器验收和人工验收创建的临时账号，统一标注为
    # TEST_ONLY。按稳定的命名约定迁移，不影响真实业务账号；新账号则由
    # 人员管理 API 的 test_only 显式声明。
    op.execute(
        """
        UPDATE users
           SET person_source = 'TEST_ONLY'
         WHERE person_source IS NULL
           AND role <> 'SUPER_ADMIN'
           AND (
             lower(username) LIKE 'test%'
             OR lower(username) LIKE 'm4r%'
             OR lower(username) LIKE 'm5r%'
             OR lower(username) LIKE '%accept%'
             OR lower(username) LIKE '%browser%'
           )
        """
    )
    op.execute("UPDATE users SET person_source = 'INTERNAL_GENERATED' WHERE person_source IS NULL")
    # SQLite 不支持 ALTER COLUMN；batch 模式会在 SQLite 安全地重建表，
    # 在 PostgreSQL 上则仍保持正常的受控列变更。
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "person_source",
            existing_type=sa.String(length=24),
            nullable=False,
            server_default="INTERNAL_GENERATED",
        )
    op.create_index("ix_users_person_source", "users", ["person_source"])


def downgrade() -> None:
    op.drop_index("ix_users_person_source", table_name="users")
    op.drop_column("users", "person_source")
