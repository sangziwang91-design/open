from agentbridge.domain.enums import ClaimLevel, TaskState, VerificationStatus
from agentbridge.domain.runtime import TaskRuntime
from agentbridge.domain.verification import ClaimReport, VerificationResult
from agentbridge.feedback.renderer import to_markdown, to_yaml
from agentbridge.services.feedback_service import FeedbackService


def test_feedback_for_completed_run() -> None:
    runtime = TaskRuntime(task_id="T", state=TaskState.COMPLETED)
    results = [
        VerificationResult(
            check_id="A1", status=VerificationStatus.PASS, verifier_id="command", detail="ok"
        )
    ]
    report = ClaimReport(max_claim_level=ClaimLevel.EXECUTED, forbidden_claims=["no overclaim"])
    envelope = FeedbackService.build(runtime, results, report)
    assert envelope.allowed_next_action == "CLOSE"
    assert "no overclaim" in to_markdown(envelope)
    assert "task_id: T" in to_yaml(envelope)
