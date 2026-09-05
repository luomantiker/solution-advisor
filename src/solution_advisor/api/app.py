from __future__ import annotations

import os
from dataclasses import replace
import redis
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from solution_advisor.api.routers.model_assets import router as model_assets_router
from solution_advisor.api.routers.evaluations import router as evaluations_router
from solution_advisor.api.routers.analysis import router as analysis_router
from solution_advisor.api.routers.workers import router as workers_router
from solution_advisor.api.routers.x5 import router as x5_router
from solution_advisor.api.routers.platforms import router as platforms_router
from solution_advisor.api.routers.auth import router as auth_router
from solution_advisor.api.routers.s100 import router as s100_router
from solution_advisor.api.routers.people import router as people_router
from solution_advisor.api.routers.system_settings import router as system_settings_router
from solution_advisor.model_assets.service import ANALYZER_VERSION
from solution_advisor.persistence.database import make_session_factory
from solution_advisor.config import Settings
from solution_advisor.artifacts import LocalArtifactStorage, S3ArtifactStorage
from solution_advisor.common_analyzer.queue import RedisAnalysisQueue
from solution_advisor.security import IdentityVerifier


def create_app(
    *, database_url: str | None = None, storage_root: Path | None = None, analyzer_version: str = ANALYZER_VERSION,
    storage=None, auto_migrate: bool | None = None, queue=None, test_identities: bool = False,
) -> FastAPI:
    settings = Settings.from_env()
    if test_identities and not settings.local_auth_hmac_key:
        # Explicit TestClient mode may exercise the local provider without
        # enabling it in any deployed Compose environment.
        settings = replace(settings, local_auth_hmac_key="test-local-auth-provider-key")
    database_url = database_url or settings.database_url
    storage_root = storage_root or settings.storage_root
    auto_migrate = settings.auto_migrate if auto_migrate is None else auto_migrate
    if storage is None:
        if settings.storage_backend == "local":
            storage = LocalArtifactStorage(storage_root)
        elif settings.storage_backend == "s3":
            import boto3
            client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url,
                                  aws_access_key_id=settings.s3_access_key_id,
                                  aws_secret_access_key=settings.s3_secret_access_key)
            storage = S3ArtifactStorage(client, bucket=settings.s3_bucket, prefix=settings.s3_prefix)
            storage.ensure_bucket()
        else:
            raise ValueError("SOLUTION_ADVISOR_STORAGE_BACKEND must be local or s3")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if database_url.startswith("sqlite:///") and not database_url.endswith(":memory:"):
            Path(database_url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        if auto_migrate:
            from solution_advisor.persistence.migrations import upgrade_database
            upgrade_database(database_url)
        app.state.session_factory = make_session_factory(database_url)
        app.state.artifact_storage = storage
        app.state.analysis_queue = queue or RedisAnalysisQueue(redis.from_url(settings.redis_url))
        app.state.settings = settings
        app.state.identity_verifier = IdentityVerifier(replace(settings, enable_test_identities=True) if test_identities else settings)
        # Bootstrap is explicit and one-time.  There is deliberately no
        # hard-coded superadmin/default password fallback in code or migration.
        if settings.identity_bootstrap_super_subject and not test_identities:
            from sqlalchemy import select
            from solution_advisor.platforms.domain import UserAccount
            session = app.state.session_factory()
            try:
                if not session.scalar(select(UserAccount).where(UserAccount.role == "SUPER_ADMIN")):
                    session.add(UserAccount(id=settings.identity_bootstrap_super_subject,
                        display_name="初始超级管理员", role="SUPER_ADMIN", person_source="SYSTEM_BUILTIN")); session.commit()
            finally:
                session.close()
        if not test_identities and settings.local_bootstrap_enabled and settings.local_bootstrap_login and settings.local_superadmin_password:
            from sqlalchemy import select
            from solution_advisor.platforms.domain import UserAccount
            from solution_advisor.security import password_hash
            session = app.state.session_factory()
            try:
                if not session.scalar(select(UserAccount).where(UserAccount.role == "SUPER_ADMIN")):
                    login = settings.local_bootstrap_login.strip().lower()
                    session.add(UserAccount(id=f"local:{login}", username=login, display_name="超级管理员",
                        role="SUPER_ADMIN", auth_source="LOCAL",
                        person_source="SYSTEM_BUILTIN", password_hash=password_hash(settings.local_superadmin_password)))
                    session.commit()
            finally:
                session.close()
        app.state.analyzer_version = analyzer_version
        yield

    app = FastAPI(title="Solution Advisor", version="0.1.0", lifespan=lifespan)
    app.include_router(model_assets_router)
    app.include_router(evaluations_router)
    app.include_router(analysis_router)
    app.include_router(workers_router)
    app.include_router(x5_router)
    app.include_router(s100_router)
    app.include_router(platforms_router)
    app.include_router(auth_router)
    app.include_router(people_router)
    app.include_router(system_settings_router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("SOLUTION_ADVISOR_WEB_ORIGIN", "http://localhost:5173")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic custom validators may retain a Python exception in ``ctx``;
        # it must not make an invalid request turn into a server error.
        errors = [{key: value for key, value in error.items() if key != "ctx"} for error in exc.errors()]
        return JSONResponse(status_code=400, content={"detail": errors})

    @app.get("/healthz")
    @app.get("/api/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
