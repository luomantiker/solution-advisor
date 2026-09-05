from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from solution_advisor.persistence.database import Base


class Visibility(StrEnum):
    INTERNAL = "INTERNAL"
    CUSTOMER = "CUSTOMER"


class EvidenceType(StrEnum):
    COMPILATION_LOG = "COMPILATION_LOG"
    BOARD_LOG = "BOARD_LOG"
    BENCHMARK = "BENCHMARK"
    OUTPUT_ARTIFACT = "OUTPUT_ARTIFACT"
    X5_COMPILE_LOG = "x5_compile_log"
    X5_COMPILE_SUMMARY = "x5_compile_summary"
    X5_STATIC_CHECK = "x5_static_check"
    X5_RUNNER_RESULT = "x5_runner_result"
    X5_COMPILED_MODEL = "x5_compiled_model"
    X5_BOARD_PREFLIGHT = "x5_board_preflight"
    X5_BOARD_LOAD_LOG = "x5_board_load_log"
    X5_BOARD_INFERENCE_LOG = "x5_board_inference_log"
    X5_BOARD_RESULT = "x5_board_result"
    S100_COMPILE_LOG = "s100_compile_log"
    S100_STATIC_CHECK = "s100_static_check"
    S100_COMPILE_SUMMARY = "s100_compile_summary"
    S100_RUNNER_RESULT = "s100_runner_result"
    S100_COMPILED_MODEL = "s100_compiled_model"
    S100_BOARD_PREFLIGHT = "s100_board_preflight"
    S100_BOARD_INFERENCE_LOG = "s100_board_inference_log"
    S100_BOARD_LOAD_LOG = "s100_board_load_log"
    S100_BOARD_PROFILE_LOG = "s100_board_profile_log"
    S100_BOARD_PROFILE_CSV = "s100_board_profile_csv"
    S100_BOARD_PROFILE = "s100_board_profile"
    S100_BOARD_RESULT = "s100_board_result"
    PLATFORM_INTEGRATION_PACKAGE = "platform_integration_package"
    PLATFORM_INTEGRATION_RESULT = "platform_integration_result"


class EvidencePhase(StrEnum):
    STATIC_CHECK = "STATIC_CHECK"
    COMPILATION = "COMPILATION"
    BOARD_TEST = "BOARD_TEST"
    INTEGRATION = "INTEGRATION"


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"artifact_{uuid4().hex}")
    uri: Mapped[str] = mapped_column(String, unique=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String)
    storage_backend: Mapped[str] = mapped_column(String)
    visibility: Mapped[str] = mapped_column(String, default=Visibility.INTERNAL.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Evidence(Base):
    __tablename__ = "evidences"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"evidence_{uuid4().hex}")
    evidence_type: Mapped[str] = mapped_column(String)
    phase: Mapped[str] = mapped_column(String)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("evaluation_tasks.id"), nullable=True, index=True)
    platform: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    toolchain_version: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_package_version: Mapped[str | None] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(String, default=Visibility.INTERNAL.value)
    produced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
