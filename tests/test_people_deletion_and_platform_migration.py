from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZipFile

from sqlalchemy import select

from solution_advisor.platforms.domain import PlatformCandidate, PlatformCatalog, PlatformType, UserAccount


SUPER = {"Authorization": "Bearer development-super-admin-token"}
ADMIN = {"Authorization": "Bearer development-admin-token"}
USER = {"Authorization": "Bearer development-user-token"}


def _available_catalog(app, *, created_by: str = "dev-super-admin") -> PlatformCatalog:
    session = app.state.session_factory()
    try:
        platform_type = PlatformType(name="PortableX", display_name="可迁移平台", created_by=created_by)
        session.add(platform_type); session.flush()
        catalog = PlatformCatalog(
            platform_type_id=platform_type.id, platform_id="PortableX", version="1.2.3",
            display_name="PortableX 1.2.3", state="AVAILABLE", created_by=created_by,
            package_manifest={"id": "portablex-package", "version": "1.2.3"},
            image_lock={"digest": "sha256:" + "a" * 64, "reference": "example/portablex:1.2.3"},
            runner={"version": "portablex-runner-1.0", "content_sha256": "b" * 64},
            checks={"compile": "verified", "board": "verified"}, review={"approved": True, "note": "验收通过"},
        )
        session.add(catalog); session.commit(); return catalog
    finally:
        session.close()


def test_super_admin_deletes_person_and_transfers_platform_governance(client, app):
    person = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "deletable-user", "display_name": "可删除人员", "role": "USER", "initial_password": "x",
    }).json()
    catalog = _available_catalog(app, created_by=person["id"])

    denied = client.delete(f"/api/admin/people/{person['id']}", headers=ADMIN | {"If-Match": str(person["revision"])})
    assert denied.status_code == 403
    deleted = client.delete(f"/api/admin/people/{person['id']}", headers=SUPER | {"If-Match": str(person["revision"])})
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True

    session = app.state.session_factory()
    try:
        assert session.get(UserAccount, person["id"]) is None
        assert session.get(PlatformCatalog, catalog.id).created_by == "dev-super-admin"
    finally:
        session.close()


def test_deleting_candidate_owner_clears_manual_claim_instead_of_transferring_it(client, app):
    person = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "candidate-owner", "display_name": "候选项认领人", "role": "ADMIN", "initial_password": "x",
    }).json()
    session = app.state.session_factory()
    try:
        candidate = PlatformCandidate(
            agent_id="agent-person-delete", image_ref="example/candidate:1", image_id="sha256:" + "c" * 64,
            created_by=person["id"], claimed_by=person["id"], claimed_by_name="候选项认领人",
            state="INTEGRATING", evidence={"workspace": {"display_name": "临时接入资料"}},
        )
        session.add(candidate); session.commit(); candidate_id = candidate.id
    finally:
        session.close()

    deleted = client.delete(f"/api/admin/people/{person['id']}", headers=SUPER | {"If-Match": str(person["revision"])})
    assert deleted.status_code == 200
    session = app.state.session_factory()
    try:
        candidate = session.get(PlatformCandidate, candidate_id)
        assert candidate.created_by == "dev-super-admin"
        assert candidate.claimed_by is None
        assert candidate.evidence == {}
        assert candidate.state == "PENDING_INTEGRATION"
    finally:
        session.close()


def test_platform_configuration_backup_then_restore_recovers_catalog_definition(client, app):
    catalog = _available_catalog(app)
    exported = client.post("/api/admin/platform-migrations/export", headers=ADMIN, json={"catalog_ids": [catalog.id]})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")

    session = app.state.session_factory()
    try:
        session.delete(session.get(PlatformCatalog, catalog.id))
        session.delete(session.scalar(select(PlatformType).where(PlatformType.name == "PortableX")))
        session.commit()
    finally:
        session.close()
    imported = client.post("/api/admin/platform-migrations/import", headers=ADMIN,
                           files={"archive": ("portable.zip", exported.content, "application/zip")})
    assert imported.status_code == 200
    assert len(imported.json()["imported_catalog_ids"]) == 1

    session = app.state.session_factory()
    try:
        recovered = session.scalar(select(PlatformCatalog).where(PlatformCatalog.platform_id == "PortableX", PlatformCatalog.version == "1.2.3"))
        assert recovered and recovered.state == "AVAILABLE"
        assert recovered.runner["version"] == "portablex-runner-1.0"
        assert recovered.image_lock["digest"] == "sha256:" + "a" * 64
    finally:
        session.close()


def test_platform_configuration_backup_requires_administrator(client, app):
    catalog = _available_catalog(app)
    denied_export = client.post("/api/admin/platform-migrations/export", headers=USER,
                                json={"catalog_ids": [catalog.id]})
    assert denied_export.status_code == 403
    denied_import = client.post("/api/admin/platform-migrations/import", headers=USER,
                                files={"archive": ("portable.zip", b"not-a-zip", "application/zip")})
    assert denied_import.status_code == 403


def test_platform_configuration_backup_strips_historical_runtime_provenance(client, app):
    catalog = _available_catalog(app)
    session = app.state.session_factory()
    try:
        stored = session.get(PlatformCatalog, catalog.id)
        stored.runner = {
            **stored.runner,
            "package_artifact_id": "artifact_not_portable",
            "integration_rules": {
                "compile_command_template": "portablex_compile --model {model}",
                "board_command_template": "portablex_run --model {model}",
                "host_paths": "NOT_ACCEPTED",
                "credentials": "NOT_ACCEPTED",
            },
        }
        stored.checks = {**stored.checks, "candidate_id": "candidate_history", "integration_evidence_id": "evidence_history"}
        session.commit()
    finally:
        session.close()

    exported = client.post("/api/admin/platform-migrations/export", headers=ADMIN, json={"catalog_ids": [catalog.id]})
    assert exported.status_code == 200
    with ZipFile(BytesIO(exported.content)) as archive:
        payload = json.loads(archive.read("platform-migration.json"))
    portable = payload["catalogs"][0]
    assert portable["runner"]["integration_rules"] == {
        "compile_command_template": "portablex_compile --model {model}",
        "board_command_template": "portablex_run --model {model}",
    }
    assert "package_artifact_id" not in portable["runner"]
    assert "candidate_id" not in portable["checks"]
    assert "integration_evidence_id" not in portable["checks"]


def test_platform_configuration_restore_rejects_handcrafted_runtime_field(client, app):
    catalog = _available_catalog(app)
    exported = client.post("/api/admin/platform-migrations/export", headers=SUPER, json={"catalog_ids": [catalog.id]})
    with ZipFile(BytesIO(exported.content)) as archive:
        payload = json.loads(archive.read("platform-migration.json"))
    payload["catalogs"][0]["runner"]["worker_id"] = "must-not-be-portable"
    bundle = BytesIO()
    with ZipFile(bundle, "w") as archive:
        archive.writestr("platform-migration.json", json.dumps(payload))
    restored = client.post("/api/admin/platform-migrations/import", headers=ADMIN,
                           files={"archive": ("tampered.zip", bundle.getvalue(), "application/zip")})
    assert restored.status_code == 422
    assert restored.json()["detail"]["code"] == "platform_migration_contains_runtime_or_secret"
