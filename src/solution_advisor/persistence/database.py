from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url: str):
    # Import ORM modules so Alembic metadata and service sessions share the same schema.
    import solution_advisor.artifacts.domain  # noqa: F401
    import solution_advisor.common_analyzer.domain  # noqa: F401
    import solution_advisor.evaluations.domain  # noqa: F401
    import solution_advisor.model_assets.domain  # noqa: F401
    import solution_advisor.platforms.domain  # noqa: F401
    import solution_advisor.system_settings.domain  # noqa: F401

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    return sessionmaker(bind=engine, expire_on_commit=False)
