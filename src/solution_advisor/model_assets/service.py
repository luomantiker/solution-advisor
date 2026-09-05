from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_advisor.artifacts.service import ArtifactService
from solution_advisor.artifacts.storage import ArtifactStorage
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile
from solution_advisor.model_assets.onnx_analyzer import analyze, load_model

ANALYZER_VERSION = "1.0.0"


class ModelAssetService:
    def __init__(self, session: Session, storage: ArtifactStorage, analyzer_version: str = ANALYZER_VERSION):
        self.session = session
        self.storage = storage
        self.analyzer_version = analyzer_version

    def upload(self, filename: str, payload: bytes) -> tuple[ModelAsset, ModelProfile, bool, bool]:
        model = load_model(payload)
        from hashlib import sha256 as digest
        sha256 = digest(payload).hexdigest()
        asset = self.session.scalar(select(ModelAsset).where(ModelAsset.sha256 == sha256))
        asset_reused = asset is not None
        if asset is None:
            artifact = ArtifactService(self.session, self.storage).put(payload, content_type="application/onnx")
            asset = ModelAsset(
                sha256=sha256,
                original_filename=filename or "upload.onnx",
                size_bytes=len(payload),
                # Kept as a compatibility mirror for pre-Alembic SQLite databases.
                # New business code uses Artifact.uri through artifact_id instead.
                storage_path=artifact.uri,
                artifact_id=artifact.id,
            )
            self.session.add(asset)
            self.session.flush()
        profile = self.session.scalar(
            select(ModelProfile).where(
                ModelProfile.onnx_sha256 == sha256,
                ModelProfile.analyzer_version == self.analyzer_version,
            )
        )
        profile_reused = profile is not None
        if profile is None:
            profile = ModelProfile(
                model_asset_id=asset.id,
                onnx_sha256=sha256,
                analyzer_version=self.analyzer_version,
                analysis=analyze(model, filename=asset.original_filename, size_bytes=asset.size_bytes, sha256=sha256),
            )
            self.session.add(profile)
        self.session.commit()
        return asset, profile, asset_reused, profile_reused

    def register(self, filename: str, payload: bytes, owner_subject: str) -> tuple[ModelAsset, bool]:
        """Register bytes without parsing; common-analyzer owns ONNX parsing."""
        from hashlib import sha256 as digest
        sha256 = digest(payload).hexdigest()
        asset = self.session.scalar(select(ModelAsset).where(ModelAsset.sha256 == sha256))
        reused = asset is not None
        if asset is None:
            artifact = ArtifactService(self.session, self.storage).put(payload, content_type="application/onnx")
            asset = ModelAsset(sha256=sha256, original_filename=filename or "upload.onnx", size_bytes=len(payload), storage_path=artifact.uri, artifact_id=artifact.id, owner_subject=owner_subject)
            self.session.add(asset); self.session.flush()
        access = self.session.scalar(select(ModelAssetAccess).where(
            ModelAssetAccess.model_asset_id == asset.id, ModelAssetAccess.subject == owner_subject))
        if access is None:
            self.session.add(ModelAssetAccess(model_asset_id=asset.id, subject=owner_subject,
                                              access_kind="OWNER", granted_by=owner_subject))
        self.session.commit()
        return asset, reused

    def get_asset(self, asset_id: str) -> ModelAsset | None:
        return self.session.get(ModelAsset, asset_id)

    def list_assets(self, owner_subject: str | None = None) -> list[ModelAsset]:
        query = select(ModelAsset).order_by(ModelAsset.created_at.desc())
        if owner_subject:
            query = query.join(ModelAssetAccess, ModelAssetAccess.model_asset_id == ModelAsset.id).where(
                ModelAssetAccess.subject == owner_subject)
        return list(self.session.scalars(query))

    def access_for(self, asset: ModelAsset, subject: str) -> ModelAssetAccess | None:
        return self.session.scalar(select(ModelAssetAccess).where(
            ModelAssetAccess.model_asset_id == asset.id, ModelAssetAccess.subject == subject))

    def get_profile_for_asset(self, asset: ModelAsset) -> ModelProfile | None:
        return self.session.scalar(
            select(ModelProfile)
            .where(ModelProfile.model_asset_id == asset.id)
            .order_by(ModelProfile.created_at.desc())
        )

    def get_profile(self, profile_id: str) -> ModelProfile | None:
        return self.session.get(ModelProfile, profile_id)
