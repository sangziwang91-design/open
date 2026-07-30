# SZ-AgentBridge

A model-agnostic, Chat-native control plane that turns a task envelope into a bounded executor run, an append-only event timeline, independently checked acceptance results, and a feedback envelope.

## Implemented scope — Phase 1-B

- Pydantic task-envelope contract with strict unknown-field rejection and legacy compact-key aliases.
- SQLite persistence for tasks, runs, events, artifacts, attempts, verification results, and capability snapshots.
- Explicit state-transition graph. Normal writes cannot skip states; forced recovery is separately recorded.
- Deterministic `fake` executor for testing and an `opencode` subprocess adapter for physical execution.
- Baseline, command, stdout, stderr, and git-diff evidence artifacts with SHA-256 hashes.
- Command, git-diff, and file-existence verifiers.
- Claim ceiling and YAML/Markdown feedback-envelope rendering.
- Typer CLI: `init`, `doctor`, `submit`, `status`, `run`, `verify`, `feedback`, and `recover`.

## Boundary

This package proves only that the declared checks passed in the current workspace and environment. It does not establish universal correctness, product maturity, autonomous usefulness, or external effectiveness.

## Install

```bash
python -m pip install -e . --no-deps
```

Python 3.12+ is required. Runtime dependencies are Pydantic, Typer, and PyYAML.

## Verified local flow

```bash
agentbridge init --db demo.db
agentbridge doctor --db demo.db
agentbridge submit examples/task-success.yaml --db demo.db
agentbridge run TASK-DEMO-SUCCESS --executor fake --db demo.db --runs-dir data/runs
agentbridge verify TASK-DEMO-SUCCESS --db demo.db --runs-dir data/runs
agentbridge feedback TASK-DEMO-SUCCESS --db demo.db --format markdown
```

The `opencode` executor requires the `opencode` executable on `PATH`. When it is absent, the run is recorded as `RECOVERY_REQUIRED` rather than presented as successful.

## Development checks

```bash
python -m compileall -q src tests scripts
python -m pytest
python scripts/package.py
```
