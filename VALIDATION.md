# Validation Record

Generated: 2026-08-01

## Checked object

- Package: `sz-agentbridge`
- Version: `0.3.0`
- Source root: `src/agentbridge`
- Original supplied ZIP SHA-256: `50ff1d9853b06d6d4c2e2a94caa420b1ca8f4f9095337a481941e711dd708aa4`
- Remote baseline before this iteration: `sangziwang91-design/open@11e6483ae3a0ad9f35018ae7b3fd0c3956d39b94`

## Commands and results

1. Original GitHub upload readback — PASS: 62/62 supplied files matched the ZIP Git blob SHA at commit `4702010cdd9accea17a0603064912dd9cb18aa42`.
2. `python -m pytest -q` — PASS: 58 tests.
3. `ruff check src tests scripts` — PASS.
4. `mypy src` — PASS: 39 source files, no issues.
5. `bandit -q -r src` and `python -m compileall -q src tests scripts` — PASS.
6. Isolated PEP 517 build — PASS: wheel SHA-256 `c16358246c2084d07f06fa855a664a8b76b85221097ee0f75de67db990d98570`; sdist SHA-256 `09022939117adab77f540f1b32cca79531695155fc0be1d9506ce60e60065b7e`.
7. Fresh Python 3.12 virtual environment dependency-resolving wheel install — PASS: dependencies downloaded and resolved from scratch, `pip check` reported no broken requirements, and installed CLI reported `0.3.0`.
8. Installed-wheel fake-executor CLI path — PASS: submit → run → verify → status reached `COMPLETED`.
9. Installed-wheel controlled OpenCode subprocess path — PASS: `doctor --require-opencode` recognized contract version `1.18.10`; submit → real OS subprocess → six artifact classes → verify → feedback reached `COMPLETED`; SQLite integrity was `ok` with zero foreign-key errors.
10. OpenCode adapter soak — PASS: 200 cycles, 217 real subprocess attempts, 11 injected nonzero exits, 6 injected timeouts with child processes, 10 service restarts, and 1,302 integrity-checked artifacts. Zero active child processes, unfinished attempts, artifact failures, policy-event failures, and foreign-key errors remained.
11. Core long run — PASS: 3,000 cycles, 3,324 attempts, 16,620 artifacts, 120 service restarts, 167 injected executor failures, and 157 acceptance-repair cycles.
12. Concurrent persistence probe — PASS: 500 tasks across 12 workers; 1,000 events, SQLite integrity `ok`, zero foreign-key errors.
13. Core long-run invariants — PASS: zero unfinished attempts, artifact hash failures, latest-verification failures, and foreign-key errors.
14. GitHub Actions CI — PASS on release-code commit `8ad94f8ba9c066751417e33a2ed1eb3a3321ec19`, run `30694480642`: Python 3.12 and 3.13 jobs both completed successfully; the Python 3.12 distribution build also passed.

The bounded results are stored in:

- `validation/release-0.3.0.json`
- `validation/core-long-run-3000-v0.3.0.json`
- `validation/opencode-adapter-soak-200-v0.3.0.json`
- `validation/long-run-2000.json` (the prior `0.2.0` campaign)

## OpenCode claim boundary

The adapter contract was checked against the current official OpenCode CLI, permission, and config-precedence documentation. The official `opencode-linux-x64@1.18.10` binary was also installed and passed package acquisition, but this validation host denied its required write to `/root/.local` with `EROFS` before it could initialize a provider. `agentbridge doctor --require-opencode` correctly returned nonzero and recorded `UNAVAILABLE`.

Therefore, the real subprocess boundary, argument contract, policy injection, evidence collection, timeout recovery, and process-group cleanup are established with a controlled OpenCode-compatible executable. Live model/provider effectiveness remains `BLOCKED_HOST`, not PASS.

## General claim boundary

These checks establish a usable local control-plane baseline for the checked source tree, Python 3.12 environment, declared fault injections, bounded SQLite workloads, installed-wheel CLI paths, and a controlled OpenCode-compatible subprocess. They do not establish universal correctness, multi-host coordination, external model effectiveness, or portability across every operating system and OpenCode release.
