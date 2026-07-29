# SZ-AgentBridge

A model-agnostic, Chat-native control plane that turns a task envelope into a bounded executor run, an append-only event timeline, independently checked acceptance results, and a feedback envelope.

## Implemented scope — Phase 1-B

- Pydantic task-envelope contract with strict unknown-field rejection and legacy compact-key aliases.
- SQLite persistence for tasks, runs, events, artifacts, attempts, verification results, and capability snapshots.
- Explicit state-transition graph. Normal writes cannot skip states; forced recovery is separately recorded.
- Deterministic `fake` executor and `opencode` subprocess adapter.
- Evidence artifacts with SHA-256 hashes.
- Typer CLI and verification workflow.

## Validation

```bash
python -m compileall -q src tests scripts
python -m pytest
```
