from enum import Enum


class TaskState(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    INVALID = "INVALID"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY = "READY"
    BASELINING = "BASELINING"
    BLOCKED = "BLOCKED"
    DISPATCHING = "DISPATCHING"
    EXECUTING = "EXECUTING"
    INTERRUPTED = "INTERRUPTED"
    TIMED_OUT = "TIMED_OUT"
    EXECUTOR_ERROR = "EXECUTOR_ERROR"
    COLLECTING = "COLLECTING"
    WAITING_VERIFICATION = "WAITING_VERIFICATION"
    VERIFYING = "VERIFYING"
    ACCEPTANCE_FAILED = "ACCEPTANCE_FAILED"
    REPAIR_READY = "REPAIR_READY"
    WAITING_HUMAN = "WAITING_HUMAN"
    REJECTED = "REJECTED"
    REQUIRE_CHANGE = "REQUIRE_CHANGE"
    COMPLETED = "COMPLETED"
    LEARNING = "LEARNING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PAUSED = "PAUSED"
    SUPERSEDED = "SUPERSEDED"
    ABORTED = "ABORTED"
    CLOSED = "CLOSED"


class PermissionMode(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ExecutorCapability(str, Enum):
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    GIT = "git"
    TEST = "test"
    BROWSER = "browser"
    GUI = "gui"


class ArtifactType(str, Enum):
    BASELINE = "baseline"
    COMMAND = "command"
    STDOUT = "stdout"
    STDERR = "stderr"
    DIFF = "diff"
    LOG = "log"
    FILE = "file"


class AttemptStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    TIMED_OUT = "TIMED_OUT"
    KILLED = "KILLED"
    FAILED = "FAILED"


class VerificationStatus(str, Enum):
    # This is a verification status, not a credential.
    PASS = "PASS"  # nosec B105
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class FailureCategory(str, Enum):
    INPUT = "INPUT"
    PERMISSION = "PERMISSION"
    ENVIRONMENT = "ENVIRONMENT"
    TOOL = "TOOL"
    IMPLEMENTATION = "IMPLEMENTATION"
    ACCEPTANCE = "ACCEPTANCE"


class ClaimLevel(str, Enum):
    GENERATED = "GENERATED"
    CHECKED = "CHECKED"
    EXECUTED = "EXECUTED"
