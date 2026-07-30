# SZ-AgentBridge

A model-agnostic, Chat-native control plane that turns a task envelope into a bounded executor run, an append-only event timeline, independently checked acceptance results, and a feedback envelope.

## Implemented scope — Phase 1-B hardening

- Pydantic task-envelope contract with strict unknown-field rejection and legacy compact-key aliases.
- SQLite persistence with verification batch IDs, optimistic runtime revisions, WAL, migrations, and foreign-key enforcement.
- Explicit state-transition graph. Normal writes cannot skip states; forced recovery is separately recorded.
- Deterministic `fake` executor for testing and an `opencode` subprocess adapter for physical execution.
- Per-attempt baseline, command, stdout, stderr, and git-diff evidence artifacts with SHA-256 integrity checks.
- Permission-gated command verification, workspace-confined file verification, and bounded command timeouts.
- Bounded repair retries, explicit in-flight recovery, and terminal attempt recording after errors or timeouts.
- Claim ceiling and YAML/Markdown feedback-envelope rendering.
- Typer CLI: `init`, `doctor`, `submit`, `status`, `run`, `verify`, `feedback`, and `recover`.

## Boundary

This package proves only that the declared checks passed in the current workspace and environment. It does not establish universal correctness, product maturity, autonomous usefulness, or external effectiveness.

## Install

```bash
python -m pip install -e .
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

If the controller itself was interrupted while a run remained in an in-flight state, an operator can explicitly reconcile it:

```bash
agentbridge recover TASK-ID --db demo.db --force-inflight
```

This flag does not guess whether an external process is still alive or kill an unknown PID. Use it only after confirming that the prior worker is no longer authoritative.

## Development checks

```bash
python -m pip install -e '.[dev]'
python -m pytest
ruff check src tests scripts
mypy src
bandit -q -r src
python -m build
python scripts/package.py
python scripts/long_run.py --cycles 500
```
