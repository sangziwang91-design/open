import yaml

from agentbridge.domain.feedback import FeedbackEnvelope


def to_yaml(envelope: FeedbackEnvelope) -> str:
    return yaml.safe_dump(
        envelope.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    )


def to_markdown(envelope: FeedbackEnvelope) -> str:
    lines = [
        "# AgentBridge Feedback Envelope",
        "",
        f"- Task: `{envelope.task_id}`",
        f"- Run: `{envelope.run_id}`",
        f"- Status: **{envelope.status}**",
        f"- Allowed next action: `{envelope.allowed_next_action}`",
        "",
        "## Evidence",
    ]
    lines.extend(f"- {item}" for item in envelope.evidence_summary)
    if envelope.failure_category:
        lines.extend(["", f"Failure category: `{envelope.failure_category.value}`"])
    if envelope.forbidden_actions:
        lines.extend(["", "## Forbidden claims/actions"])
        lines.extend(f"- {item}" for item in envelope.forbidden_actions)
    if envelope.question_to_human:
        lines.extend(["", f"> Human decision required: {envelope.question_to_human}"])
    return "\n".join(lines) + "\n"
