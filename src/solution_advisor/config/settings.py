from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_backend: str
    storage_root: Path
    s3_bucket: str
    s3_prefix: str
    s3_endpoint_url: str | None
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    auto_migrate: bool
    redis_url: str
    upload_temp_root: Path
    upload_max_bytes: int
    admin_token: str
    worker_registration_token: str
    enable_test_identities: bool
    identity_issuer: str | None
    identity_audience: str | None
    identity_hmac_key: str | None
    identity_bootstrap_super_subject: str | None
    enterprise_sso_enabled: bool
    local_auth_hmac_key: str | None
    local_auth_issuer: str
    local_auth_audience: str
    local_superadmin_password: str
    local_bootstrap_enabled: bool
    local_bootstrap_login: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("SOLUTION_ADVISOR_DATABASE_URL", "sqlite:///data/solution-advisor.sqlite3"),
            storage_backend=os.getenv("SOLUTION_ADVISOR_STORAGE_BACKEND", "local"),
            storage_root=Path(os.getenv("SOLUTION_ADVISOR_STORAGE_ROOT", "data/uploads")),
            s3_bucket=os.getenv("SOLUTION_ADVISOR_S3_BUCKET", "solution-advisor"),
            s3_prefix=os.getenv("SOLUTION_ADVISOR_S3_PREFIX", "artifacts"),
            s3_endpoint_url=os.getenv("SOLUTION_ADVISOR_S3_ENDPOINT_URL") or None,
            s3_access_key_id=os.getenv("SOLUTION_ADVISOR_S3_ACCESS_KEY_ID") or None,
            s3_secret_access_key=os.getenv("SOLUTION_ADVISOR_S3_SECRET_ACCESS_KEY") or None,
            auto_migrate=os.getenv("SOLUTION_ADVISOR_AUTO_MIGRATE", "true").lower() == "true",
            redis_url=os.getenv("SOLUTION_ADVISOR_REDIS_URL", "redis://localhost:6379/0"),
            upload_temp_root=Path(os.getenv("SOLUTION_ADVISOR_UPLOAD_TEMP_ROOT", "data/receiving")),
            upload_max_bytes=int(os.getenv("SOLUTION_ADVISOR_UPLOAD_MAX_BYTES", str(256 * 1024 * 1024))),
            admin_token=os.getenv("SOLUTION_ADVISOR_ADMIN_TOKEN", "development-admin-token"),
            worker_registration_token=os.getenv("SOLUTION_ADVISOR_WORKER_REGISTRATION_TOKEN", "development-worker-token"),
            enable_test_identities=os.getenv("SOLUTION_ADVISOR_ENABLE_TEST_IDENTITIES", "false").lower() == "true",
            identity_issuer=os.getenv("SOLUTION_ADVISOR_IDENTITY_ISSUER") or None,
            identity_audience=os.getenv("SOLUTION_ADVISOR_IDENTITY_AUDIENCE") or None,
            identity_hmac_key=os.getenv("SOLUTION_ADVISOR_IDENTITY_HMAC_KEY") or None,
            identity_bootstrap_super_subject=os.getenv("SOLUTION_ADVISOR_IDENTITY_BOOTSTRAP_SUPER_SUBJECT") or None,
            enterprise_sso_enabled=os.getenv("SOLUTION_ADVISOR_ENTERPRISE_SSO_ENABLED", "false").lower() == "true",
            local_auth_hmac_key=os.getenv("SOLUTION_ADVISOR_LOCAL_AUTH_HMAC_KEY") or None,
            local_auth_issuer=os.getenv("SOLUTION_ADVISOR_LOCAL_AUTH_ISSUER", "solution-advisor-local"),
            local_auth_audience=os.getenv("SOLUTION_ADVISOR_LOCAL_AUTH_AUDIENCE", "solution-advisor"),
            local_superadmin_password=os.getenv("SOLUTION_ADVISOR_SUPERADMIN_PASSWORD", ""),
            local_bootstrap_enabled=os.getenv("SOLUTION_ADVISOR_LOCAL_BOOTSTRAP_ENABLED", "false").lower() == "true",
            local_bootstrap_login=os.getenv("SOLUTION_ADVISOR_LOCAL_BOOTSTRAP_LOGIN") or None,
        )
