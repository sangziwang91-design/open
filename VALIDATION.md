# Validation Record

Generated: 2026-07-30

## Checked object

- Package: `sz-agentbridge`
- Version: `0.2.0`
- Source root: `src/agentbridge`
- Original supplied ZIP SHA-256: `50ff1d9853b06d6d4c2e2a94caa420b1ca8f4f9095337a481941e711dd708aa4`

## Commands and results

1. GitHub upload readback — PASS: 62/62 supplied files matched the ZIP Git blob SHA at commit `4702010cdd9accea17a0603064912dd9cb18aa42`.
2. `python -m pytest -q` — PASS: 45 tests.
3. `ruff check src tests scripts` — PASS.
4. `mypy src` — PASS: 39 source files, no issues.
5. `bandit -q -r src` — PASS: no reported issues.
6. Final `0.2.0` package build — PASS by artifact readback: wheel SHA-256 `6cc9a4edda44c6f7e6026209e78569d26d7c3b2cad7f62955d3239af331d0ab8`; sdist SHA-256 `7121e6b4650975c5bb0aeb698df89102f31a21eab78360c57b182f08c1b4cc99`.
7. Final wheel `--no-deps --target` installation — PASS: import reported `0.2.0`, metadata required Python `>=3.12`, and installed CLI exposed `recover --force-inflight`.
8. Long-run validation — PASS: 2,000 cycles, 2,216 attempts, 11,080 artifacts, 80 service reinitializations, 111 injected executor failures, and 105 acceptance-repair cycles.
9. Concurrent persistence probe — PASS: 250 tasks across 8 workers; 500 events, SQLite integrity `ok`, zero foreign-key errors.
10. Final long-run invariants — PASS: zero unfinished attempts, artifact hash failures, latest-verification failures, and foreign-key errors.

A fresh dependency-resolving installation of final `0.2.0` is UNKNOWN. The host execution-quota gate blocked that isolated rerun; the successful target installation reused the already checked dependency environment.

The bounded long-run result is stored in `validation/long-run-2000.json`.

## Claim boundary

These checks establish behavior only for the checked source tree, Python 3.12 environment, fake executor, declared fault injections, and bounded local SQLite workloads. They do not establish universal correctness, production maturity, external effectiveness, live OpenCode behavior, multi-host coordination, abrupt operating-system kill recovery, or portability across Windows and macOS.
