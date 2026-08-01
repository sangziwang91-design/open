# SZ-AgentBridge

A model-agnostic, Chat-native control plane that turns a task envelope into a bounded executor run, an append-only event timeline, independently checked acceptance results, and a feedback envelope.

## Implemented scope — usable local baseline

- Pydantic task-envelope contract with strict unknown-field rejection and legacy compact-key aliases.
- SQLite persistence with verification batch IDs, optimistic runtime revisions, WAL, migrations, and foreign-key enforcement.
- Explicit state-transition graph. Normal writes cannot skip states; forced recovery is separately recorded.
- Deterministic `fake` executor plus a version-probed OpenCode subprocess adapter using the current non-interactive `run` contract.
- Fail-closed OpenCode permission preflight: file writes, deletion, network, and shell effects must all be explicitly allowed because OpenCode's edit/shell tools cannot isolate those effects from one another.
- Runtime-inline OpenCode permission policy with external-directory/subagent denials, `.env` protection, plugin isolation, immutable policy evidence, bounded timeouts, and process-group cleanup.
- Per-attempt baseline, command, stdout, stderr, and git-diff evidence artifacts with SHA-256 integrity checks.
- Permission-gated command verification, workspace-confined file verification, and bounded command timeouts.
- Bounded repair retries, explicit in-flight recovery, and terminal attempt recording after errors or timeouts.
- Claim ceiling and YAML/Markdown feedback-envelope rendering.
- Typer CLI: `init`, `doctor`, `submit`, `status`, `run`, `verify`, `feedback`, and `recover`.
- GitHub Actions quality gates on Python 3.12 and 3.13.

## Boundary

This package proves only that the declared checks passed in the current workspace and environment. It does not establish universal correctness, product maturity, autonomous usefulness, or external effectiveness.

## Install

```bash
python -m pip install -e .
```

Python 3.12+ is required. Runtime dependencies are bounded to compatible major versions of Pydantic, Typer, and PyYAML.

## Verified local flow

```bash
agentbridge init --db demo.db
agentbridge doctor --db demo.db
agentbridge submit examples/task-success.yaml --db demo.db
agentbridge run TASK-DEMO-SUCCESS --executor fake --db demo.db --runs-dir data/runs
agentbridge verify TASK-DEMO-SUCCESS --db demo.db --runs-dir data/runs
agentbridge feedback TASK-DEMO-SUCCESS --db demo.db --format markdown
```

## OpenCode flow

Install and authenticate OpenCode using its official instructions, then require a healthy adapter contract before submitting work:

```bash
npm install -g opencode-ai
opencode auth login
agentbridge doctor --require-opencode --db demo.db
agentbridge submit examples/task-opencode.yaml --db demo.db
agentbridge run TASK-DEMO-OPENCODE --db demo.db --runs-dir data/runs
agentbridge verify TASK-DEMO-OPENCODE --db demo.db --runs-dir data/runs
```

Use `--opencode-executable /absolute/path/to/opencode` on `doctor` and `run` when OpenCode is not on `PATH`.

The adapter requires OpenCode 1.1.1 or newer and probes the exact `run` flags it needs. It currently accepts only whole-workspace scope with no exclusions, and requires explicit `allow` for `file_write`, `delete`, `network`, and `shell`. This is intentionally fail-closed: OpenCode shell/edit operations cannot faithfully enforce a narrower combination without an external operating-system sandbox. The launched process receives a runtime-inline policy that denies external-directory and subagent tools, runs with external plugins disabled, and records a secret-free `policy.json` artifact and hash for each attempt. OpenCode administrator-managed configuration can still take precedence, so deployments must verify their managed policy separately.

When OpenCode is missing or incompatible, the run is recorded as `RECOVERY_REQUIRED` rather than presented as successful. When permissions are insufficient, it is blocked before any attempt starts.

If the controller itself was interrupted while a run remained in an in-flight state, an operator can explicitly reconcile it:

```bash
agentbridge recover TASK-ID --db demo.db --force-inflight
```

This flag does not guess whether an external process is still alive or kill an unknown PID. Use it only after confirming that the prior worker is no longer authoritative.

SZ-AgentBridge is independent software and is not built by or affiliated with the OpenCode team.

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
python scripts/opencode_adapter_soak.py --cycles 100
```

The latest bounded evidence and exact claim boundary are recorded in `VALIDATION.md` and `validation/`.
