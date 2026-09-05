"""Static contract for the customer-facing Candidate stage guidance component."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_stage_guide_covers_all_governed_states_and_cleanup_boundary():
    component = (ROOT / "frontend/src/components/CandidateStageGuide.vue").read_text(encoding="utf-8")
    for stage in ("DISCOVERED", "INTEGRATING", "MANAGED"):
        assert stage in component
    for label in ("当前上下文", "需要填写/确认", "系统将执行", "资料与证据"):
        assert label in component
    assert "释放或超级管理员强制释放会先清理本次接入资料" in component
    assert "其他管理员只读" in component
