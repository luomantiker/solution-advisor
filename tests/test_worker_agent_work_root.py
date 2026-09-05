from pathlib import Path

from solution_advisor.workers.worker_agent import WorkerAgent


def test_worker_agent_uses_configured_shared_work_root(tmp_path: Path) -> None:
    root = tmp_path / "agent-work"
    agent = WorkerAgent({"instance_id": "x5-test", "work_root": str(root)})

    with agent._temporary_work_dir("task_x5") as directory:
        work_dir = Path(directory)
        assert work_dir.parent == root
        assert work_dir.is_dir()

    assert root.is_dir()
