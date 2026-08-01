import hashlib
import json
import os
import re
import shlex
import shutil
import signal

# Subprocess use is the bounded adapter's declared purpose.
import subprocess  # nosec B404
from pathlib import Path
from typing import Any, TextIO

from agentbridge.domain.task import TaskEnvelope
from agentbridge.errors import ExecutorPolicyError, ExecutorUnavailableError
from agentbridge.executors.base import Executor

MINIMUM_OPENCODE_VERSION = (1, 1, 1)
VERSION_PATTERN = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
REQUIRED_RUN_FLAGS = ("--format", "--dir", "--agent", "--title")


def _resolve_executable(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise ExecutorUnavailableError(
            f"{executable!r} executable was not found or is not executable"
        )
    return str(Path(resolved).resolve())


def _run_probe(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["OPENCODE_CONFIG_CONTENT"] = "{}"
    environment["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    environment["OPENCODE_DISABLE_SHARE"] = "1"
    try:
        # argv is explicit and the executable was resolved with shutil.which().
        return subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExecutorUnavailableError(
            f"OpenCode probe timed out after {timeout} seconds"
        ) from exc
    except OSError as exc:
        raise ExecutorUnavailableError(f"OpenCode probe failed: {exc}") from exc


def probe_opencode(executable: str = "opencode", timeout: int = 10) -> dict[str, str]:
    """Resolve OpenCode and verify the CLI contract used by this adapter."""
    resolved = _resolve_executable(executable)
    version_result = _run_probe([resolved, "--pure", "--version"], timeout)
    version_output = (version_result.stdout or version_result.stderr).strip()
    if version_result.returncode != 0:
        detail = version_output[:240] or "no diagnostic output"
        raise ExecutorUnavailableError(
            f"OpenCode version probe exited {version_result.returncode}: {detail}"
        )
    match = VERSION_PATTERN.search(version_output)
    if match is None:
        raise ExecutorUnavailableError(
            f"OpenCode returned an unrecognized version: {version_output[:120]!r}"
        )
    version_tuple = tuple(int(part) for part in match.groups())
    if version_tuple < MINIMUM_OPENCODE_VERSION:
        required = ".".join(str(part) for part in MINIMUM_OPENCODE_VERSION)
        raise ExecutorUnavailableError(
            f"OpenCode {match.group(0)} is too old; version {required}+ is required"
        )

    help_result = _run_probe([resolved, "--pure", "run", "--help"], timeout)
    help_output = f"{help_result.stdout}\n{help_result.stderr}"
    missing = [flag for flag in REQUIRED_RUN_FLAGS if flag not in help_output]
    if help_result.returncode != 0 or missing:
        detail = (
            f"missing flags: {', '.join(missing)}"
            if missing
            else f"exit code {help_result.returncode}"
        )
        raise ExecutorUnavailableError(
            f"OpenCode run command is incompatible with AgentBridge ({detail})"
        )
    return {"executable": resolved, "version": match.group(0)}


def _policy() -> dict[str, Any]:
    protected_files = {
        "*": "allow",
        "*.env": "deny",
        "*.env.*": "deny",
        "*.env.example": "allow",
    }
    return {
        "*": "deny",
        "read": dict(protected_files),
        "edit": dict(protected_files),
        "glob": "allow",
        "grep": "allow",
        "lsp": "allow",
        "bash": "allow",
        "webfetch": "allow",
        "websearch": "allow",
        "external_directory": "deny",
        "task": "deny",
        "skill": "deny",
        "question": "deny",
        "doom_loop": "deny",
    }


def _runtime_environment(policy: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    existing_text = environment.get("OPENCODE_CONFIG_CONTENT", "").strip()
    if existing_text:
        try:
            config = json.loads(existing_text)
        except json.JSONDecodeError as exc:
            raise ExecutorPolicyError(
                "OPENCODE_CONFIG_CONTENT must contain a JSON object"
            ) from exc
        if not isinstance(config, dict):
            raise ExecutorPolicyError(
                "OPENCODE_CONFIG_CONTENT must contain a JSON object"
            )
    else:
        config = {}

    config["permission"] = policy
    agents = config.get("agent")
    if not isinstance(agents, dict):
        agents = {}
    build_agent = agents.get("build")
    if not isinstance(build_agent, dict):
        build_agent = {}
    build_agent["permission"] = policy
    agents["build"] = build_agent
    config["agent"] = agents

    # OpenCode evaluates granular permission rules in insertion order, with the
    # last matching rule winning. Preserve both user config and policy order.
    config_text = json.dumps(config, separators=(",", ":"))
    environment["OPENCODE_CONFIG_CONTENT"] = config_text
    environment["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    environment["OPENCODE_DISABLE_SHARE"] = "1"
    return environment


def _validate_scope(envelope: TaskEnvelope) -> None:
    includes = [value.strip().rstrip("/") for value in envelope.scope.include]
    whole_workspace = not includes or set(includes) <= {"", "."}
    if not whole_workspace or envelope.scope.exclude:
        raise ExecutorPolicyError(
            "OpenCode execution currently requires whole-workspace scope with no "
            "exclusions because shell commands cannot faithfully enforce narrower "
            "path rules"
        )


class OpenCodeExecutor(Executor):
    executor_id = "opencode"
    # OpenCode's edit and shell tools can delete files, and shell commands can use
    # the network. Refuse to launch unless all effects are explicitly authorized.
    required_permissions = ("file_write", "delete", "network", "shell")

    def __init__(self, executable: str = "opencode", probe_timeout: int = 10) -> None:
        self.executable = executable
        self.probe_timeout = probe_timeout
        self.process: subprocess.Popen[str] | None = None
        self.stdout_file: TextIO | None = None
        self.stderr_file: TextIO | None = None
        self.context: dict[str, Any] | None = None

    def prepare(self, envelope: TaskEnvelope, run_dir: Path) -> dict[str, Any]:
        _validate_scope(envelope)
        policy = _policy()
        environment = _runtime_environment(policy)
        probe = probe_opencode(self.executable, self.probe_timeout)
        run_dir.mkdir(parents=True, exist_ok=True)
        workspace_path = Path(envelope.target.workspace).resolve()
        if not workspace_path.is_dir():
            raise ExecutorUnavailableError(
                f"OpenCode workspace is not a directory: {workspace_path}"
            )
        workspace = str(workspace_path)
        command = [
            probe["executable"],
            "--pure",
            "run",
            "--format",
            "json",
            "--agent",
            "build",
            "--title",
            envelope.task_id,
            "--dir",
            workspace,
            envelope.goal,
        ]
        command_text = shlex.join(command)
        command_path = run_dir / "command.txt"
        command_path.write_text(command_text, encoding="utf-8")
        policy_text = json.dumps(
            {
                "schema_version": "1.0",
                "executor": self.executor_id,
                "opencode_version": probe["version"],
                "required_permissions": list(self.required_permissions),
                "scope": {
                    "mode": "whole_workspace",
                    "external_directory": "deny",
                },
                "opencode_permission": policy,
            },
            indent=2,
            sort_keys=True,
        )
        policy_path = run_dir / "policy.json"
        policy_path.write_text(policy_text + "\n", encoding="utf-8")
        self.context = {
            "command": command,
            "command_hash": hashlib.sha256(command_text.encode()).hexdigest(),
            "opencode_version": probe["version"],
            "policy_hash": hashlib.sha256((policy_text + "\n").encode()).hexdigest(),
            "workspace": workspace,
            "run_dir": str(run_dir),
            "policy_path": str(policy_path),
            "_environment": environment,
        }
        return dict(self.context)

    def start(self, prepared_context: dict[str, Any]) -> int:
        self.context = prepared_context
        run_dir = Path(prepared_context["run_dir"])
        self.stdout_file = (run_dir / "stdout.log").open("w", encoding="utf-8")
        self.stderr_file = (run_dir / "stderr.log").open("w", encoding="utf-8")
        environment = prepared_context.pop("_environment")
        popen_options: dict[str, Any] = {}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        # argv is explicit and the executable was resolved with shutil.which().
        self.process = subprocess.Popen(  # nosec B603
            prepared_context["command"],
            cwd=prepared_context["workspace"],
            stdout=self.stdout_file,
            stderr=self.stderr_file,
            text=True,
            env=environment,
            **popen_options,
        )
        return int(self.process.pid)

    def poll(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def wait(self, timeout: int | None = None) -> int:
        if self.process is None:
            raise RuntimeError("executor was not started")
        return int(self.process.wait(timeout=timeout))

    def collect(self) -> dict[str, Any]:
        if self.process is None or self.context is None:
            raise RuntimeError("executor was not started")
        self._close_logs()
        exit_code = int(self.process.returncode)
        signal_name = None
        if exit_code < 0:
            try:
                signal_name = signal.Signals(-exit_code).name
            except ValueError:
                signal_name = "UNKNOWN"
        run_dir = Path(self.context["run_dir"])
        return {
            "exit_code": exit_code,
            "stdout_path": str(run_dir / "stdout.log"),
            "stderr_path": str(run_dir / "stderr.log"),
            "command_path": str(run_dir / "command.txt"),
            "policy_path": self.context["policy_path"],
            "workspace": self.context["workspace"],
            "terminated": exit_code < 0,
            "signal": signal_name,
        }

    def cancel(self) -> None:
        if self.process is not None and self.poll():
            try:
                if os.name == "posix":
                    os.killpg(self.process.pid, signal.SIGKILL)
                else:
                    self.process.kill()
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self._close_logs()

    def _close_logs(self) -> None:
        for handle in (self.stdout_file, self.stderr_file):
            if handle is not None and not handle.closed:
                handle.close()
