from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import os
from solution_advisor.persistence.database import Base
import solution_advisor.artifacts.domain  # noqa: F401
import solution_advisor.common_analyzer.domain  # noqa: F401
import solution_advisor.evaluations.domain  # noqa: F401
import solution_advisor.model_assets.domain  # noqa: F401
import solution_advisor.system_settings.domain  # noqa: F401

config = context.config
if os.getenv("SOLUTION_ADVISOR_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["SOLUTION_ADVISOR_DATABASE_URL"])
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
