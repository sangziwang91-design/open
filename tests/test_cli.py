import re
from pathlib import Path

from typer.testing import CliRunner

from agentbridge.cli import app

runner = CliRunner()


def test_cli_end_to_end(tmp_path: Path) -> None:
    db = tmp_path / "cli.db"
    runs = tmp_path / "runs"
    task_file = tmp_path / "task.yaml"
    task_file.write_text(
        """title: cli test
type: engineering
goal: test the cli
source: {adapter: test}
target: {executor_id: fake, workspace: .}
acceptance:
  - {id: A1, type: command, command: 'python -V', expected_exit_code: 0}
stop: {success: pass, blocked: blocked}
""",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "--db", str(db)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["submit", str(task_file), "--db", str(db)])
    assert result.exit_code == 0, result.output
    task_id = re.search(r"Task ID: (\S+)", result.output).group(1)
    result = runner.invoke(
        app,
        [
            "run",
            task_id,
            "--executor",
            "fake",
            "--db",
            str(db),
            "--runs-dir",
            str(runs),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app, ["verify", task_id, "--db", str(db), "--runs-dir", str(runs)]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["feedback", task_id, "--db", str(db)])
    assert result.exit_code == 0
    assert "COMPLETED" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.4.0"


def test_doctor_reports_structured_opencode_probe(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "agentbridge.cli.probe_opencode",
        lambda executable: {"executable": executable, "version": "1.18.10"},
    )
    result = runner.invoke(
        app,
        [
            "doctor",
            "--db",
            str(tmp_path / "doctor.db"),
            "--opencode-executable",
            "/opt/opencode",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "status: READY" in result.output
    assert "version: 1.18.10" in result.output
    assert "executable: /opt/opencode" in result.output


def test_doctor_can_require_opencode(monkeypatch, tmp_path: Path) -> None:
    def unavailable(executable: str):
        raise RuntimeError(f"unavailable: {executable}")

    monkeypatch.setattr("agentbridge.cli.probe_opencode", unavailable)
    result = runner.invoke(
        app,
        [
            "doctor",
            "--db",
            str(tmp_path / "required.db"),
            "--require-opencode",
        ],
    )
    assert result.exit_code == 1
    assert "status: UNAVAILABLE" in result.output
    assert "RuntimeError: unavailable: opencode" in result.output


def test_bridge_requires_explicit_no_sandbox_acknowledgement(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = runner.invoke(app, ["bridge", "--workspace", str(workspace)])
    assert result.exit_code == 2
    assert "--acknowledge-no-os-sandbox" in result.output
    result = runner.invoke(
        app,
        [
            "bridge",
            "--workspace",
            str(workspace),
            "--executor",
            "fake",
        ],
    )
    assert result.exit_code == 2
    assert "verification commands" in result.output
