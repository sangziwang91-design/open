import argparse
import json
import tempfile
import time
from pathlib import Path

from agentbridge.bridge.controller import BridgeConfig, BridgeController
from agentbridge.bridge.protocol import BrainTaskMessage
from agentbridge.persistence.database import Database


def controller_for(root: Path) -> BridgeController:
    return BridgeController(
        BridgeConfig(
            workspace=root / "workspace",
            database=Database(root / "bridge.db"),
            runs_dir=root / "runs",
            executor_name="fake",
            max_pending_jobs=8,
        )
    )


def wait_for_result(controller: BridgeController, job_id: str, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = controller.store.get(job_id)
        if job is not None and job.status in {"FINISHED", "ERROR"}:
            return job
        time.sleep(0.01)
    raise RuntimeError(f"job did not finish: {job_id}")


def run(cycles: int, restart_every: int) -> dict[str, int | float | str]:
    started = time.monotonic()
    completed = 0
    duplicate_checks = 0
    restarts = 0
    with tempfile.TemporaryDirectory(prefix="agentbridge-bridge-soak-") as directory:
        root = Path(directory)
        (root / "workspace").mkdir()
        controller = controller_for(root)
        controller.start()
        previous: str | None = None
        try:
            for index in range(cycles):
                request_id = f"REQ-SOAK-{index:06d}"
                task = BrainTaskMessage(
                    session_id="AB-SOAK",
                    request_id=request_id,
                    parent_request_id=previous,
                    title=f"Soak cycle {index}",
                    goal="Exercise the persistent bridge execution and verification loop.",
                    acceptance=[
                        {
                            "id": "PYTHON",
                            "type": "command",
                            "command": "python --version",
                            "expected_exit_code": 0,
                        }
                    ],
                    timeout_seconds=30,
                )
                job, created = controller.submit(task)
                if not created:
                    raise RuntimeError("new soak request was unexpectedly deduplicated")
                final = wait_for_result(controller, job.job_id)
                if (
                    final.status != "FINISHED"
                    or final.result is None
                    or final.result.status != "COMPLETED"
                    or not final.result.checks
                    or final.result.checks[0].status != "PASS"
                ):
                    raise RuntimeError(f"soak cycle failed: {final}")
                completed += 1
                previous = request_id
                if index % 10 == 0:
                    duplicate, duplicate_created = controller.submit(task)
                    if duplicate_created or duplicate.job_id != job.job_id:
                        raise RuntimeError("idempotency check failed")
                    duplicate_checks += 1
                if (
                    restart_every > 0
                    and index + 1 < cycles
                    and (index + 1) % restart_every == 0
                ):
                    controller.stop()
                    controller = controller_for(root)
                    controller.start()
                    restarts += 1
        finally:
            controller.stop()
    return {
        "protocol": "agentbridge/1",
        "cycles": cycles,
        "completed": completed,
        "duplicate_checks": duplicate_checks,
        "controller_restarts": restarts,
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "PASS" if completed == cycles else "FAIL",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--restart-every", type=int, default=25)
    args = parser.parse_args()
    if args.cycles < 1 or args.restart_every < 0:
        raise SystemExit("cycles must be positive and restart-every non-negative")
    print(json.dumps(run(args.cycles, args.restart_every), indent=2))


if __name__ == "__main__":
    main()
