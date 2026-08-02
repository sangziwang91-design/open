# Validation Record

Generated: 2026-08-02

## Checked object

- Package: `sz-agentbridge`
- Version: `0.4.0`
- Source root: `src/agentbridge`
- Browser extension root: `extension`
- Remote baseline before this iteration: `sangziwang91-design/open@2d3c1f231d5b951bb6e6074fe360ec7d5c24f4ce`
- Intended release branch: `agent/windows-chat-bridge`

## Local commands and results

1. `python -m pytest -q` — **PASS**: 97 tests. This includes real loopback HTTP requests; token, Origin, Host, size and authority-escalation rejection; persistent idempotency; queue restart; in-flight fail-closed recovery; scoped SQLite connection closure; executor cancellation; Windows argv rules; extension packaging; and execute → verify → feedback paths.
2. `node --test extension/tests/core.test.js extension/tests/adapter.test.js` — **PASS**: 11 protocol and ChatGPT DOM-adapter tests.
3. `ruff check src tests scripts` — **PASS**.
4. `ruff format --check src tests scripts` — **PASS** after formatting the changed tree.
5. `mypy src tests` — **PASS**: 73 source and test files, no issues.
6. `bandit -q -r src` and `python -m compileall -q src tests` — **PASS**.
7. `npm audit --audit-level=high` — **PASS**: zero reported vulnerabilities.
8. PEP 517 wheel and sdist build from implementation commit `664c86e606d6a6807284c46b7d6b2899de92416a` — **PASS** in GitHub Actions Python 3.12. No final hashes are claimed: the local rebuild attempt after the last source fix was denied by the host's execution-approval quota, and the workflow does not publish those temporary artifacts.
9. Deterministic Manifest V3 package — **PASS**. Two strict-mode rebuilds matched byte-for-byte and the ZIP integrity check passed; SHA-256: `25faef2b287cd24114ed668377fc888a108556700185154292975eb097f5e2f5`.
10. Fresh dependency-resolving wheel checkpoint — **PASS** before the final SQLite lifetime fix: installed CLI reported `0.4.0`, `pip check` reported no broken requirements, and the fake-executor and authenticated HTTP paths reached `FINISHED / COMPLETED / EXECUTED`. The final tree is instead covered by 97 tests, the SQLite close regression, the GitHub PEP 517 build, and Linux/Windows bridge soaks; a post-fix local wheel-install claim is intentionally not made.
11. Final bridge soak — **PASS**: 1,000/1,000 completed jobs, 100 idempotent duplicate checks and 39 controller restarts.
12. Final core long run — **PASS**: 3,000 completed cycles, 3,324 attempts, 16,620 integrity-checked artifacts, 120 service restarts, 167 injected executor failures and 157 acceptance-repair cycles. The concurrent probe persisted 500 tasks across 12 workers with SQLite integrity `ok` and zero foreign-key errors.
13. Final OpenCode adapter soak — **PASS**: 200 cycles, 217 real subprocess attempts, 11 injected nonzero exits, 6 injected timeouts with child processes, 10 service restarts and 1,302 integrity-checked artifacts. Zero active children, unfinished attempts, artifact failures, policy-event failures and foreign-key errors remained.

The bounded machine-readable results are stored in:

- `validation/bridge-soak-1000-v0.4.0.json`
- `validation/core-long-run-3000-v0.4.0.json`
- `validation/opencode-adapter-soak-200-v0.4.0.json`
- `validation/release-0.4.0.json`

## GitHub gates

- Workflow [run 30751492180](https://github.com/sangziwang91-design/open/actions/runs/30751492180) for implementation commit `664c86e606d6a6807284c46b7d6b2899de92416a` — **PASS**, all four jobs.
- Python 3.12 and 3.13 — **PASS**: 97 tests on each version; Ruff, Bandit and expanded mypy (`src tests`, 73 files) passed; Python 3.12 also built both distributions, packaged the extension and completed the restart soak.
- Windows — **PASS**: 97 tests, 11 browser-core tests, extension packaging, 50/50 bridge jobs with 5 duplicate checks and 4 controller restarts, installation of `opencode-ai@1.18.11`, and `agentbridge doctor --require-opencode` reporting `READY` for `C:\npm\prefix\opencode.cmd` version `1.18.11`.
- Real browser fixture — **PASS**: Chrome for Testing `151.0.7922.34` loaded the unpacked Manifest V3 extension and reported `{"status":"PASS","steps":1}` after automatic result writeback. The browser version is derived from the pinned Playwright package and downloaded from the official Chrome for Testing public bucket, avoiding runner/browser version drift and the region-blocked Playwright CDN route.

## OpenCode and browser claim boundary

The controlled OpenCode-compatible executable establishes the real subprocess boundary, current argument shape, policy injection, evidence collection, timeout recovery and process-tree cleanup. The official `opencode-linux-x64@1.18.11` binary was acquired locally, but this sandbox denied its required write to `/root/.local` with `EROFS`; live provider execution is therefore not a local PASS. The Windows GitHub job independently installed and probed the pinned real CLI without model credentials.

The browser harness loads the actual unpacked extension in Chromium and drives a controlled ChatGPT-shaped page through prompt injection, task extraction, service-worker HTTP proxying, terminal result and automatic composer writeback. It does not use a logged-in ChatGPT account. Live owner-host compatibility with the current `chatgpt.com` DOM remains an explicit acceptance step, not an automated claim.

## General claim boundary

These checks establish a bounded, evidence-gated Windows-web bridge implementation and repeatable controlled execution chain. They do not establish an operating-system sandbox, universal correctness, native-app automation, provider/model effectiveness, future ChatGPT DOM compatibility, or token-free OpenCode execution. The bridge reduces planning-token demand by using the web Chat as the brain; OpenCode execution can still consume provider tokens.
