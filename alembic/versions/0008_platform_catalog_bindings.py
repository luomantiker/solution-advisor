"""Platform catalog, Agent Binding and dynamic Worker hierarchy."""
from alembic import op
import sqlalchemy as sa

revision = "0008_platform_catalog_bindings"
down_revision = "0007_x5_board_smoke"
branch_labels = depends_on = None


def upgrade():
    op.create_table("platform_catalogs",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("platform_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False), sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False), sa.Column("package_manifest", sa.JSON(), nullable=False),
        sa.Column("image_lock", sa.JSON(), nullable=False), sa.Column("runner", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False), sa.Column("review", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True), sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("platform_id", "version", name="uq_platform_catalog_version"))
    op.create_index("ix_platform_catalogs_platform_id", "platform_catalogs", ["platform_id"])
    op.create_index("ix_platform_catalogs_state", "platform_catalogs", ["state"])
    op.create_table("platform_candidates",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("image_ref", sa.String(), nullable=False), sa.Column("image_id", sa.String(), nullable=False),
        sa.Column("toolchain_version", sa.String(), nullable=True), sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(), nullable=False), sa.Column("catalog_id", sa.String(), sa.ForeignKey("platform_catalogs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_index("ix_platform_candidates_agent_id", "platform_candidates", ["agent_id"])
    op.create_table("agents",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("host_state", sa.String(), nullable=False),
        sa.Column("agent_version", sa.String(), nullable=True), sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True), sa.Column("discovery_policy", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()))
    op.create_table("platform_bindings",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("catalog_id", sa.String(), sa.ForeignKey("platform_catalogs.id"), nullable=False), sa.Column("platform_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False), sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("image_lock_version", sa.String(), nullable=False),
        sa.Column("runner_version", sa.String(), nullable=False), sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "catalog_id", name="uq_platform_binding_agent_catalog"))
    op.create_index("ix_platform_bindings_agent_id", "platform_bindings", ["agent_id"]); op.create_index("ix_platform_bindings_catalog_id", "platform_bindings", ["catalog_id"]); op.create_index("ix_platform_bindings_platform_id", "platform_bindings", ["platform_id"]); op.create_index("ix_platform_bindings_state", "platform_bindings", ["state"])
    op.create_table("platform_workers",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("binding_id", sa.String(), sa.ForeignKey("platform_bindings.id"), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False), sa.Column("platform_id", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False), sa.Column("runner", sa.JSON(), nullable=False),
        sa.Column("current_task_id", sa.String(), nullable=True), sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()))
    for field in ("binding_id", "agent_id", "platform_id", "state", "current_task_id"): op.create_index(f"ix_platform_workers_{field}", "platform_workers", [field])
    op.create_table("platform_audits",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("action", sa.String(), nullable=False), sa.Column("actor", sa.String(), nullable=False),
        sa.Column("catalog_id", sa.String(), nullable=True), sa.Column("binding_id", sa.String(), nullable=True), sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("result", sa.String(), nullable=False), sa.Column("summary", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()))
    for field in ("catalog_id", "binding_id", "worker_id"): op.create_index(f"ix_platform_audits_{field}", "platform_audits", [field])
    with op.batch_alter_table("task_snapshots") as batch:
        batch.add_column(sa.Column("platform_governance", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))

    bind = op.get_bind(); meta = sa.MetaData()
    wi = sa.Table("worker_instances", meta, autoload_with=bind); tasks = sa.Table("evaluation_tasks", meta, autoload_with=bind)
    snapshots = sa.Table("task_snapshots", meta, autoload_with=bind)
    catalog_id, binding_id, worker_id = "catalog_x5_1_0_0", "binding_x5_a_x5_1_0_0", "worker_x5_a_x5_0"
    bind.execute(sa.insert(sa.Table("platform_catalogs", meta, autoload_with=bind)).values(
        id=catalog_id, platform_id="X5", version="1.0.0", display_name="X5", state="AVAILABLE", created_by="migration",
        package_manifest={"id":"x5","version":"1.0.0","capabilities":["static_check","compile","board_smoke"]},
        image_lock={"image":"openexplorer/ai_toolchain_ubuntu_20_x5_gpu:v1.2.8-py310","digest":"sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593"},
        runner={"module":"platform_runner","version":"1.0.0"}, checks={"self_check":True,"offline_test":True}, review={"approved":True,"source":"M4-A/M4-B-R0 验收迁移"}))
    legacy = bind.execute(sa.select(wi).where(wi.c.id == "x5-a")).mappings().first()
    if legacy:
        bind.execute(sa.insert(sa.Table("agents", meta, autoload_with=bind)).values(id="x5-a", host_state="ONLINE", agent_version="legacy-agent", last_heartbeat_at=legacy["last_heartbeat_at"], discovery_policy={}))
        bind.execute(sa.insert(sa.Table("platform_bindings", meta, autoload_with=bind)).values(id=binding_id, agent_id="x5-a", catalog_id=catalog_id, platform_id="X5", state="HEALTHY", capabilities=legacy["capabilities"], max_concurrency=legacy["max_concurrency"], image_lock_version="sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593", runner_version="1.0.0", last_heartbeat_at=legacy["last_heartbeat_at"]))
        bind.execute(sa.insert(sa.Table("platform_workers", meta, autoload_with=bind)).values(id=worker_id, binding_id=binding_id, agent_id="x5-a", platform_id="X5", state="READY", max_concurrency=legacy["max_concurrency"], runner={"version":"1.0.0","image_lock_version":"sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593"}, last_heartbeat_at=legacy["last_heartbeat_at"]))
        bind.execute(tasks.update().where(tasks.c.worker_instance_id == "x5-a").values(worker_instance_id=worker_id))
        leases = sa.Table("worker_capacity_leases", meta, autoload_with=bind)
        bind.execute(leases.update().where(leases.c.worker_instance_id == "x5-a").values(worker_instance_id=worker_id))
    governance = {"platform_id":"X5","catalog_id":catalog_id,"catalog_version":"1.0.0","binding_id":binding_id,"worker_id":worker_id,"runner_version":"1.0.0","image_lock_version":"sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593","profile_parser_version":"x5-hrt-profile-1.0"}
    bind.execute(snapshots.update().where(snapshots.c.platform_package_versions.is_not(None)).values(platform_governance=governance))


def downgrade():
    raise RuntimeError("restore backup")
