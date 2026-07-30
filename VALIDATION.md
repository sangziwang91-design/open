# Validation Record

Generated: 2026-07-29

## Checked object

- Package: `sz-agentbridge`
- Version: `0.1.0`
- Source root: `src/agentbridge`

## Commands and results

1. `PYTHONPATH=src python -m compileall -q src tests scripts` — PASS.
2. `PYTHONPATH=src python -m pytest -q` — PASS: 20 tests.
3. `python -m pip install -e . --no-deps --no-build-isolation` — PASS.
4. Installed CLI success path (init → submit → fake run → verify → feedback → status) — PASS; final state `COMPLETED`.
5. Installed CLI acceptance-failure path — PASS; verifier exits 1 and final state is `REPAIR_READY`.
6. Package script and final ZIP extraction are checked after this record is written; authoritative ZIP hash is supplied with delivery.

## Claim boundary

These checks establish that the packaged implementation compiles, its declared automated tests pass, and the tested CLI paths behave as specified in this environment. They do not establish universal correctness, production maturity, or external effectiveness.
