from __future__ import annotations

from sqlalchemy import select

from solution_advisor.artifacts.domain import Artifact
from solution_advisor.artifacts.service import ArtifactService
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationTask, EvaluationTaskShare, ReportRevision
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile


SUPER = {"Authorization": "Bearer development-super-admin-token"}
USER_2 = {"Authorization": "Bearer development-user-2-token"}


def _seed(client):
    session = client.app.state.session_factory()
    try:
        model_artifact = ArtifactService(session, client.app.state.artifact_storage).put(b"onnx-bytes", content_type="application/onnx")
        asset = ModelAsset(sha256="a" * 64, original_filename="shared.onnx", size_bytes=10, artifact_id=model_artifact.id,
                           storage_path=model_artifact.uri, owner_subject="dev-user")
        session.add(asset); session.flush()
        session.add_all([
            ModelAssetAccess(model_asset_id=asset.id, subject="dev-user", access_kind="OWNER", granted_by="dev-user"),
            ModelAssetAccess(model_asset_id=asset.id, subject="dev-user-2", access_kind="SHARED", granted_by="dev-user"),
        ])
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test",
                               analysis={"summary": {"node_count": 1}})
        session.add(profile); session.flush()
        flow = EvaluationFlow(model_profile_id=profile.id, owner_subject="dev-user", status="SUCCEEDED",
                              preset="standard-performance-1.0", platform_snapshots={}, model_snapshot={}, error_summary={})
        session.add(flow); session.flush()
        task = EvaluationTask(model_profile_id=profile.id, mode="REAL", platforms=["X5"], status="SUCCEEDED",
                              task_kind="X5_COMPILE", flow_id=flow.id, owner_subject="dev-user")
        session.add(task); session.flush()
        session.add(EvaluationTaskShare(task_id=task.id, subject="dev-user-2", shared_by="dev-user", include_model=True))
        pdf = ArtifactService(session, client.app.state.artifact_storage).put(b"pdf", content_type="application/pdf")
        session.add(ReportRevision(flow_id=flow.id, version=1, template_version="test", snapshot={}, pdf_artifact_id=pdf.id))
        session.commit()
        return asset.id, flow.id, model_artifact.uri, pdf.uri
    finally:
        session.close()


def test_only_super_admin_changes_model_deletion_policy(client):
    assert client.get("/api/admin/system-settings", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/admin/system-settings").status_code == 403
    assert client.get("/api/admin/system-settings", headers=SUPER).json()["allow_evaluated_model_deletion"] is False
    changed = client.put("/api/admin/system-settings", headers=SUPER, json={"allow_evaluated_model_deletion": True})
    assert changed.status_code == 200
    assert changed.json()["allow_evaluated_model_deletion"] is True


def test_model_deletion_cleans_own_evaluations_but_keeps_shared_onnx_until_last_reference(client):
    asset_id, flow_id, model_uri, pdf_uri = _seed(client)
    assert next(item for item in client.get("/api/v1/model-assets").json() if item["id"] == asset_id)["can_delete_model"] is False
    assert client.delete(f"/api/v1/model-assets/{asset_id}").status_code == 403
    assert client.put("/api/admin/system-settings", headers=SUPER, json={"allow_evaluated_model_deletion": True}).status_code == 200
    assert next(item for item in client.get("/api/v1/model-assets").json() if item["id"] == asset_id)["can_delete_model"] is True

    deleted = client.delete(f"/api/v1/model-assets/{asset_id}")
    assert deleted.status_code == 200
    assert deleted.json()["physical_model_deleted"] is False
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}").status_code == 404
    assert client.app.state.artifact_storage.exists(model_uri)
    assert not client.app.state.artifact_storage.exists(pdf_uri)
    assert client.get(f"/api/v1/model-assets/{asset_id}", headers=USER_2).status_code == 200

    final = client.delete(f"/api/v1/model-assets/{asset_id}", headers=USER_2)
    assert final.status_code == 200
    assert final.json()["physical_model_deleted"] is True
    assert not client.app.state.artifact_storage.exists(model_uri)
    session = client.app.state.session_factory()
    try:
        assert session.get(ModelAsset, asset_id) is None
        assert session.scalar(select(Artifact.id).where(Artifact.uri == model_uri)) is None
    finally:
        session.close()


def test_super_admin_can_delete_legacy_model_without_its_own_access_grant(client):
    asset_id, flow_id, model_uri, _ = _seed(client)
    assert client.put("/api/admin/system-settings", headers=SUPER, json={"allow_evaluated_model_deletion": True}).status_code == 200

    # A super administrator can see historical global model assets even when
    # they were created before per-user ModelAssetAccess rows existed.
    item = next(item for item in client.get("/api/v1/model-assets", headers=SUPER).json() if item["id"] == asset_id)
    assert item["can_delete_model"] is True
    deleted = client.delete(f"/api/v1/model-assets/{asset_id}", headers=SUPER)
    assert deleted.status_code == 200
    assert deleted.json()["physical_model_deleted"] is True
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}", headers=SUPER).status_code == 404
    assert not client.app.state.artifact_storage.exists(model_uri)
