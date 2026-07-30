from pathlib import Path
import re

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
        ["run", task_id, "--executor", "fake", "--db", str(db), "--runs-dir", str(runs)],
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
    assert result.output.strip() == "0.1.0"
