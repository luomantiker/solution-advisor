from __future__ import annotations


SUPER = {"Authorization": "Bearer development-super-admin-token"}
ADMIN = {"Authorization": "Bearer development-admin-token"}


def test_super_admin_controls_versioned_onnx_extension_policy(client, model_bytes):
    denied = client.get("/api/admin/system-settings/onnx-analysis-policy", headers=ADMIN)
    assert denied.status_code == 403

    initial = client.get("/api/admin/system-settings/onnx-analysis-policy", headers=SUPER)
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["base_checks"] == [{
        "id": "core_profile", "name": "基础 ONNX 结构检查",
        "description": "校验 ONNX 合法性，并提取 IR、Opset、输入输出、节点和算子统计。",
        "enabled": True, "required": True,
    }]
    extensions = {item["id"]: item["enabled"] for item in payload["extensions"]}
    assert set(extensions) == {"model_size", "dynamic_shape"}

    upload = client.post("/api/v1/model-assets", files={"file": ("policy.onnx", model_bytes, "application/onnx")})
    assert upload.status_code == 201
    old_task_id = upload.json()["analysis_task"]["id"]

    extensions["dynamic_shape"] = False
    updated = client.put("/api/admin/system-settings/onnx-analysis-policy", headers=SUPER, json={
        "revision": payload["revision"], "extensions": extensions,
    })
    assert updated.status_code == 200
    assert updated.json()["revision"] == payload["revision"] + 1
    assert {item["id"]: item["enabled"] for item in updated.json()["extensions"]}["dynamic_shape"] is False

    # The queued task freezes the policy present at creation and does not follow
    # the new global value.
    old_task = client.get(f"/api/v1/analysis-tasks/{old_task_id}")
    assert old_task.status_code == 200
    assert old_task.json()["snapshot"]["revision"] == payload["revision"]
    assert old_task.json()["snapshot"]["modules"]["dynamic_shape"]["enabled"] is True

    stale = client.put("/api/admin/system-settings/onnx-analysis-policy", headers=SUPER, json={
        "revision": payload["revision"], "extensions": extensions,
    })
    assert stale.status_code == 409
    malformed = client.put("/api/admin/system-settings/onnx-analysis-policy", headers=SUPER, json={
        "revision": updated.json()["revision"], "extensions": {"model_size": True},
    })
    assert malformed.status_code == 422
