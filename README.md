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


## WLS ↔ AgentBridge: reuse the existing mailbox instead of a second agent

The `wls-prepare` and `wls-reply` commands connect **one already-leased
WLS AgenticHarness node** to this project's existing SQLite-backed executor.
They do not implement ChatGPT browser/UI automation, a provider quota bypass,
or unattended reasoning from a free ChatGPT conversation.

The WLS runtime first exports a task via its existing
`AgenticHarness.export_node_task_envelope(graph_id, node_id,
lease_id=..., mailbox_root=..., recipient="agentbridge")` method.
The runtime must already hold an ACTIVE node lease. Both packages must
see the **same local mailbox directory** (or an explicitly synchronized
copy that preserves the JSON files); a GitHub repository by itself is not
a shared running process or a live messaging service.

Given WLS's `message_id` from the export receipt and a disposable or
owner-approved workspace, the **single-command** local path uses the existing
submission, executor, verification, and WLS reply functions:

```sh
agentbridge wls-cycle MESSAGE_ID \
  --mailbox-root ./shared-mailbox \
  --workspace ./candidate-worktree \
  --check-file expected-result.txt \
  --db ./agentbridge.db --runs-dir ./runs \
  --executor fake
```

To use the actual OpenCode worker, explicitly select `--executor opencode
--allow-model-usage` after provider authentication. It may consume paid or
metered model usage and has workspace side-effect permissions; neither the
ChatGPT chat interface nor GitHub source-control access substitutes for
OpenCode authentication.

The same steps remain available **individually** for diagnosis or recovery:

```sh
agentbridge wls-prepare MESSAGE_ID \
  --mailbox-root ./shared-mailbox \
  --workspace ./candidate-worktree \
  --check-file expected-result.txt \
  --output ./wls-task.json \
  --executor fake

agentbridge submit ./wls-task.json --db ./agentbridge.db
agentbridge run WLS-TASK-ID --executor fake --db ./agentbridge.db --runs-dir ./runs
agentbridge verify WLS-TASK-ID --db ./agentbridge.db --runs-dir ./runs
agentbridge wls-reply MESSAGE_ID --mailbox-root ./shared-mailbox --db ./agentbridge.db
```

The `WLS-TASK-ID` is printed by `wls-prepare` and `submit`. Replace the
`fake` executor with **`opencode` only in an authorized workspace with a
configured provider and appropriate permissions**. OpenCode may incur
provider charges. Acceptance for the first bridge version is a single
**file-exists** check; do not treat that as proof of broad code quality.
WLS must still independently apply its own acceptance tests when importing
the result.

The response is written as a native WLS `ResultEnvelope` to
`shared-mailbox/results/`, including `in_reply_to`, graph/node/lease IDs,
the lease fencing token, strict SHA-256 payload digest, and only persisted
AgentBridge verifier outcomes. WLS can import it using its existing
`AgenticHarness.import_node_result_envelope(...)` method. A submitted,
running or unverified task cannot generate a success reply; retries with
the same identifiers are idempotent. WLS remains the only authority for
completing its graph node.

**Current operational limit:** local file transport has been connected and
tested; GitHub Actions cannot automatically invoke a private ChatGPT
conversation as an inference engine. A completely unattended loop requires
a separately authenticated, explicitly authorized model/worker process.
Use ChatGPT for interactive task decisions and GitHub for source changes,
PR reviews and CI receipts without pretending the chat is an API.
