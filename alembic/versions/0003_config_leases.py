from alembic import op
import sqlalchemy as sa
revision='0003_config_leases'; down_revision='0002_async_analysis'; branch_labels=depends_on=None
def upgrade():
 op.create_table('analyzer_config_versions',sa.Column('id',sa.String(),primary_key=True),sa.Column('version',sa.Integer(),unique=True),sa.Column('modules',sa.JSON()),sa.Column('max_concurrency',sa.Integer()),sa.Column('config_hash',sa.String(64)),sa.Column('created_by',sa.String()),sa.Column('change_note',sa.String()),sa.Column('state',sa.String()),sa.Column('created_at',sa.DateTime(),server_default=sa.text('CURRENT_TIMESTAMP')))
 op.create_table('analyzer_config_audits',sa.Column('id',sa.String(),primary_key=True),sa.Column('action',sa.String()),sa.Column('actor',sa.String()),sa.Column('old_version',sa.Integer()),sa.Column('new_version',sa.Integer()),sa.Column('summary',sa.String()),sa.Column('created_at',sa.DateTime(),server_default=sa.text('CURRENT_TIMESTAMP')))
 op.create_table('worker_capacity_leases',sa.Column('id',sa.String(),primary_key=True),sa.Column('worker_instance_id',sa.String()),sa.Column('slot_index',sa.Integer()),sa.Column('task_id',sa.String()),sa.Column('attempt_id',sa.String()),sa.Column('lease_token',sa.String(),unique=True),sa.Column('status',sa.String()),sa.Column('expires_at',sa.DateTime()),sa.Column('created_at',sa.DateTime(),server_default=sa.text('CURRENT_TIMESTAMP')),sa.UniqueConstraint('worker_instance_id','slot_index','status',name='uq_active_slot'))
def downgrade(): raise RuntimeError('restore backup')
