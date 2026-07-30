from pathlib import Path
from uuid import uuid4

from agentbridge.domain.enums import (
    ArtifactType,
    ClaimLevel,
    TaskState,
    VerificationStatus,
)
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.task import TaskEnvelope
from agentbridge.domain.verification import ClaimReport, VerificationResult
from agentbridge.interpreters.artifact_collector import artifact_for
from agentbridge.persistence.database import Database
from agentbridge.persistence.repository import AgentRepository
from agentbridge.persistence.unit_of_work import UnitOfWork
from agentbridge.services.state_manager import StateManager
from agentbridge.verification.base import Verifier
from agentbridge.verification.command_verifier import CommandVerifier
from agentbridge.verification.file_verifier import FileExistsVerifier
from agentbridge.verification.git_verifier import GitDiffVerifier


class VerificationService:
    def __init__(self, database: Database, runs_dir: Path) -> None:
        self.database = database
        self.runs_dir = Path(runs_dir)
        self.verifiers: dict[str, Verifier] = {
            "command": CommandVerifier(),
            "gitdiff": GitDiffVerifier(),
            "fileexists": FileExistsVerifier(),
        }

    def verify(
        self, runtime: TaskRuntime, envelope: TaskEnvelope
    ) -> tuple[bool, list[VerificationResult], ClaimReport]:
        verification_dir = (
            self.runs_dir
            / runtime.run_id
            / "verifications"
            / f"verification-{uuid4().hex.upper()}"
        )
        command_verifier = CommandVerifier(
            timeout_seconds=envelope.budget.timeout_seconds,
            evidence_dir=verification_dir,
        )
        self.verifiers["command"] = command_verifier
        run_dir = self.runs_dir / runtime.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        workspace = Path(envelope.target.workspace).resolve()
        with UnitOfWork(self.database) as uow:
            repo = AgentRepository(uow.connection)
            manager = StateManager(repo)
            manager.transition(
                runtime, TaskState.VERIFYING, "VerificationStarted", "checks_dispatched"
            )
            artifacts = repo.list_artifacts(runtime.run_id)
            results: list[VerificationResult] = []
            for item in envelope.acceptance:
                verifier = self.verifiers.get(item.type)
                if verifier is None:
                    results.append(
                        VerificationResult(
                            check_id=item.id,
                            status=VerificationStatus.UNKNOWN,
                            verifier_id="unsupported",
                            detail=f"No verifier for acceptance type {item.type}",
                        )
                    )
                    continue
                result = verifier.check(
                    item, artifacts, run_dir, workspace, envelope.permissions
                )
                if item.type == "command":
                    log_path = command_verifier.log_path(run_dir, item.id)
                    if log_path.exists():
                        evidence = artifact_for(
                            runtime.task_id,
                            runtime.run_id,
                            log_path,
                            ArtifactType.LOG,
                            result.verifier_id,
                            run_dir,
                        )
                        repo.save_artifacts([evidence])
                        result = result.model_copy(
                            update={"artifact_id": evidence.artifact_id}
                        )
                results.append(result)
            repo.save_verification_results(runtime.run_id, results)
            passed = bool(results) and all(
                r.status == VerificationStatus.PASS for r in results
            )
            report = ClaimReport(
                allowed_claims=["All declared acceptance checks passed"]
                if passed
                else [],
                forbidden_claims=[
                    "The implementation is universally correct",
                    "No undiscovered defects exist",
                    "External effectiveness has been established",
                ],
                max_claim_level=ClaimLevel.EXECUTED if passed else ClaimLevel.GENERATED,
            )
            if passed:
                manager.transition(
                    runtime,
                    TaskState.COMPLETED,
                    "VerificationPassed",
                    "all_acceptance_checks_passed",
                    extra={"claim_level": report.max_claim_level.value},
                )
            else:
                manager.transition(
                    runtime,
                    TaskState.ACCEPTANCE_FAILED,
                    "VerificationFailed",
                    "one_or_more_checks_failed",
                    extra={
                        "failed_checks": [
                            r.check_id
                            for r in results
                            if r.status != VerificationStatus.PASS
                        ]
                    },
                )
                manager.transition(
                    runtime, TaskState.REPAIR_READY, "RepairReady", "acceptance_failure"
                )
            return passed, results, report
