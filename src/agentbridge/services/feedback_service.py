from agentbridge.domain.enums import FailureCategory, TaskState, VerificationStatus
from agentbridge.domain.feedback import FeedbackEnvelope
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.verification import ClaimReport, VerificationResult


class FeedbackService:
    @staticmethod
    def build(
        runtime: TaskRuntime,
        results: list[VerificationResult],
        claim_report: ClaimReport | None = None,
        attempt_id: str | None = None,
    ) -> FeedbackEnvelope:
        failed = [r for r in results if r.status != VerificationStatus.PASS]
        failure_category = next((r.failure_category for r in failed if r.failure_category), None)
        if runtime.state == TaskState.COMPLETED:
            status = "COMPLETED"
            next_action = "CLOSE"
        elif runtime.state in {TaskState.BLOCKED, TaskState.RECOVERY_REQUIRED}:
            status = "BLOCKED"
            next_action = "INPUT" if failure_category in {
                FailureCategory.INPUT,
                FailureCategory.ENVIRONMENT,
                FailureCategory.PERMISSION,
            } else "REPAIR"
        else:
            status = "FAILED"
            next_action = "INPUT" if failure_category in {
                FailureCategory.INPUT,
                FailureCategory.ENVIRONMENT,
                FailureCategory.PERMISSION,
            } else "REPAIR"
        evidence = [
            f"{r.check_id}: {r.status.value} — {r.detail}"
            + (f" [artifact {r.artifact_id}]" if r.artifact_id else "")
            for r in results
        ]
        if not evidence:
            evidence = [f"No verification results; current state is {runtime.state.value}"]
        return FeedbackEnvelope(
            task_id=runtime.task_id,
            run_id=runtime.run_id,
            attempt_id=attempt_id,
            status=status,
            evidence_summary=evidence,
            failure_category=failure_category,
            allowed_next_action=next_action,
            forbidden_actions=(claim_report.forbidden_claims if claim_report else []),
            new_constraints=["Retry only the failed acceptance node"] if next_action == "REPAIR" else [],
            requires_human_decision=next_action == "INPUT",
            question_to_human=(
                "Provide the missing input, permission, or environment dependency."
                if next_action == "INPUT"
                else None
            ),
        )
