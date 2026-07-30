from pathlib import Path

from scripts.long_run import run_validation


def test_long_run_validator_smoke(tmp_path: Path) -> None:
    report = run_validation(
        root=tmp_path / "soak",
        cycles=6,
        restart_every=3,
        fault_every=4,
        repair_every=5,
        concurrent_tasks=8,
        workers=4,
    )
    assert report["status"] == "PASS"
    assert report["cycles"] == 6
    assert report["unfinished_attempts"] == 0
    assert report["artifact_integrity_failures"] == 0
    assert report["foreign_key_errors"] == 0
