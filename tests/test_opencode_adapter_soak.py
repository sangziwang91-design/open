from pathlib import Path

from scripts.opencode_adapter_soak import run_validation


def test_opencode_adapter_soak_smoke(tmp_path: Path) -> None:
    report = run_validation(
        root=tmp_path / "adapter-soak",
        cycles=4,
        fault_every=3,
        timeout_every=4,
        restart_every=2,
    )
    assert report["status"] == "PASS"
    assert report["cycles"] == 4
    assert report["attempts"] == 6
    assert report["fault_cycles"] == 1
    assert report["timeout_cycles"] == 1
    assert report["unfinished_attempts"] == 0
    assert report["active_child_processes"] == 0
