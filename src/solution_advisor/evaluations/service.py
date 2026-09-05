from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_advisor.evaluations.domain import EvaluationResult, EvaluationTask, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile

ALLOWED_PLATFORMS = {"X5", "S100", "Intel"}
FIXTURE_PATH = Path(__file__).with_name("fixtures") / "demo_results_v1.json"


class DemoTaskError(ValueError):
    def __init__(self, message: str, code: str = "invalid_demo_task"):
        super().__init__(message)
        self.code = code


class DemoEvaluationService:
    def __init__(self, session: Session):
        self.session = session

    def create(self, profile_id: str, mode: str, platforms: list[str], owner_subject: str) -> EvaluationTask:
        if mode != "DEMO":
            code = "real_mode_not_enabled" if mode == "REAL" else "invalid_mode"
            raise DemoTaskError("Only DEMO evaluation tasks can be created in this release", code)
        if not platforms or not set(platforms).issubset(ALLOWED_PLATFORMS):
            raise DemoTaskError("platforms must contain one or more of: X5, S100, Intel")
        if self.session.get(ModelProfile, profile_id) is None:
            raise LookupError("Model profile not found")
        examples = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        profile = self.session.get(ModelProfile, profile_id)
        asset = self.session.get(ModelAsset, profile.model_asset_id)
        snapshot = TaskSnapshot(model_asset_id=asset.id, model_profile_id=profile.id,
                                platform_package_versions={platform: "demo-fixture-1.0.0" for platform in platforms})
        self.session.add(snapshot)
        self.session.flush()
        # DEMO fixtures are produced in this transaction, so the task is already
        # complete when it becomes visible to the portal.
        task = EvaluationTask(model_profile_id=profile_id, mode="DEMO", platforms=platforms, snapshot_id=snapshot.id,
                              owner_subject=owner_subject, status="SUCCEEDED", task_kind="DEMO")
        self.session.add(task)
        self.session.flush()
        snapshot.task_id = task.id
        for platform in platforms:
            self.session.add(EvaluationResult(
                task_id=task.id, platform=platform, source="DEMO",
                fixture_version=examples["version"], payload=examples["platforms"][platform],
                common_result={"mode": "DEMO"}, platform_result=examples["platforms"][platform], evidence_ids=[],
            ))
        self.session.commit()
        return task

    def get(self, task_id: str) -> EvaluationTask | None:
        return self.session.get(EvaluationTask, task_id)

    def results(self, task_id: str) -> list[EvaluationResult]:
        return list(self.session.scalars(select(EvaluationResult).where(EvaluationResult.task_id == task_id)))
