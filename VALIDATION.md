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

1. `python -m pytest -q` — **PASS**: 95 tests. This includes real loopback HTTP requests; token, Origin, Host, size and authority-escalation rejection; persistent idempotency; queue restart; in-flight fail-closed recovery; executor cancellation; Windows argv rules; extension packaging; and execute → verify → feedback paths.
2. `node --test extension/tests/core.test.js extension/tests/adapter.test.js` — **PASS**: 11 protocol and ChatGPT DOM-adapter tests.
3. `ruff check src tests scripts` — **PASS**.
4. `ruff format --check src tests scripts` — **PASS** after formatting the changed tree.
5. `mypy src` — **PASS**: 45 source files, no issues.
6. `bandit -q -r src` and `python -m compileall -q src tests scripts` — **PASS**.
7. `npm audit --audit-level=high` — **PASS**: zero reported vulnerabilities.
8. Isolated PEP 517 build — **PASS**. Wheel SHA-256: `4573638d3b0cb0dead2ccfded0158b7f6267930c43cdcd8a4fc48731fcd0fba6`; sdist SHA-256: `e40976f323b14bb4abdf1b3afeb6b6655c087051814336c54061c238c5283332`. Python distribution reproducibility is not claimed because the default setuptools archives contain build timestamps.
9. Deterministic Manifest V3 package — **PASS**. Two strict-mode rebuilds matched byte-for-byte and the ZIP integrity check passed; SHA-256: `25faef2b287cd24114ed668377fc888a108556700185154292975eb097f5e2f5`.
10. Fresh dependency-resolving wheel install — **PASS**: installed CLI reported `0.4.0`, `pip check` reported no broken requirements, and the lower-level fake-executor path reached `COMPLETED` with an `EXECUTED` claim.
11. Installed-wheel bridge HTTP smoke — **PASS**: CLI gateway startup with explicit no-sandbox acknowledgement, authenticated POST, persistent worker, command verification, polling and result reached `FINISHED / COMPLETED / EXECUTED`.
12. Final bridge soak — **PASS**: 1,000/1,000 completed jobs, 100 idempotent duplicate checks and 39 controller restarts.
13. Final core long run — **PASS**: 3,000 completed cycles, 3,324 attempts, 16,620 integrity-checked artifacts, 120 service restarts, 167 injected executor failures and 157 acceptance-repair cycles. The concurrent probe persisted 500 tasks across 12 workers with SQLite integrity `ok` and zero foreign-key errors.
14. Final OpenCode adapter soak — **PASS**: 200 cycles, 217 real subprocess attempts, 11 injected nonzero exits, 6 injected timeouts with child processes, 10 service restarts and 1,302 integrity-checked artifacts. Zero active children, unfinished attempts, artifact failures, policy-event failures and foreign-key errors remained.

The bounded machine-readable results are stored in:

- `validation/bridge-soak-1000-v0.4.0.json`
- `validation/core-long-run-3000-v0.4.0.json`
- `validation/opencode-adapter-soak-200-v0.4.0.json`

## Pending remote gates

- GitHub Actions Python 3.12/3.13 quality jobs: **PENDING** until the branch is pushed.
- GitHub Windows full suite, bridge persistence soak and pinned OpenCode `1.18.11` CLI contract probe: **PENDING** until the branch is pushed.
- Real Chromium extension closed loop against the controlled ChatGPT-shaped DOM fixture: **PENDING** until the final GitHub run. CI uses the open-source Chromium already present in GitHub's Ubuntu runner image, avoiding a region-dependent Playwright CDN download. This local host could fetch the npm harness but its network proxy returned a zero-byte browser archive, so no local browser PASS is claimed.

## OpenCode and browser claim boundary

The controlled OpenCode-compatible executable establishes the real subprocess boundary, current argument shape, policy injection, evidence collection, timeout recovery and process-tree cleanup. The official `opencode-linux-x64@1.18.11` binary was acquired locally, but this sandbox denied its required write to `/root/.local` with `EROFS`; live provider execution is therefore not a local PASS. The Windows GitHub job separately probes the pinned real CLI without model credentials.

The browser harness loads the actual unpacked extension in Chromium and drives a controlled ChatGPT-shaped page through prompt injection, task extraction, service-worker HTTP proxying, terminal result and automatic composer writeback. It does not use a logged-in ChatGPT account. Live owner-host compatibility with the current `chatgpt.com` DOM remains an explicit acceptance step, not an automated claim.

## General claim boundary

These checks establish a bounded, evidence-gated Windows-web bridge implementation and repeatable controlled execution chain. They do not establish an operating-system sandbox, universal correctness, native-app automation, provider/model effectiveness, future ChatGPT DOM compatibility, or token-free OpenCode execution. The bridge reduces planning-token demand by using the web Chat as the brain; OpenCode execution can still consume provider tokens.
