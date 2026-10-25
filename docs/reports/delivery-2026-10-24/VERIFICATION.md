# AgentWindTunnel V1 delivery verification — 2026-10-24

**Final status: Incomplete, with specific blockers.** Local mock web functionality and worker recovery have been exercised. Clean dependency installation, Docker execution and the expired-order live web case remain unverified. Public deployment is blocked pending hosting, authentication and paid-execution admission/spending controls.

## Automated results

57 passed, 1 warning in 9.60s (final post-fix run)

The original suite initially returned 46 passed and two timeout failures. A later concurrent run returned 50 passed and the same two timing failures. A quiet full run returned 54 passed before the final deadline regression was added. The final result above is the current suite result. Existing scenario expectations were preserved. Tests now always use temporary SQLite storage. One existing datetime.utcnow deprecation warning remains.

## Fixes delivered

- Fixed the missing queued-run run_id runner contract and parent-run ownership; scripted runs also attach to their parent.
- Added an explicit embedded-worker switch; Compose disables it and starts one standalone worker. Embedded IDs are unique.
- Preserved cancellation at finalization and recorded sanitized infrastructure exceptions as FAILED rather than empty COMPLETED runs.
- Applied queued execution limits to agent loops; fixed final-response deadline bypass, counted thread startup within tool deadlines, and disabled implicit provider SDK retries.
- Deferred timeout trace persistence to settlement while retaining unresolved-future tracking and late-write safety.
- Marked abandoned scenario attempts INTERRUPTED and retained evidence; paid attempts are never automatically replayed.
- Restored polling on refresh/reopen, reset stale selected scenarios, corrected initial model selection, and added visible missing-run/network errors with recovery.
- Fixed mobile body layout and loading-table cells; comparison compatibility includes provider/model, execution configuration and scenario selection.
- Isolated production tool sessions from the runner and buffered background trace writes for ordered persistence on the owning thread, eliminating overlapping Session commits.
- Enabled SQLite WAL with a five-second busy timeout following an observed API/worker lock failure.
- Corrected credential-presence wording, Docker writable data directory, worker health configuration, loopback publishing, and build-context exclusions.
- Removed the Settings UI's false "Configured (Verified)" claim; configured credentials now display the backend's "Configured (not validated)" status. Model discovery now explicitly says it does not verify tool-calling support.

## Browser checks actually executed

Real headless Chromium via local Python Playwright. HTTP/API checks were not substituted for browser execution.
- Navigation: overview
- Navigation: test-studio
- Navigation: scenarios
- Navigation: agent-versions
- Navigation: run-history
- Navigation: comparisons
- Navigation: settings
- Run completed after browser refresh: eligible_refund_scenario.json run_7fa207c36f
- Detail tab: checks eligible_refund_scenario.json
- Detail tab: timeline eligible_refund_scenario.json
- Detail tab: db eligible_refund_scenario.json
- Detail tab: answer eligible_refund_scenario.json
- Detail tab: raw eligible_refund_scenario.json
- Run completed after browser refresh: dev_suite run_6c409f947a
- Detail tab: checks dev_suite
- Detail tab: timeline dev_suite
- Detail tab: db dev_suite
- Detail tab: answer dev_suite
- Detail tab: raw dev_suite
- Browser download matches saved result: json
- Browser download matches saved result: md
- Desktop and 390px viewport screenshots captured
- Missing run produces visible HTTP 404 error state
- Fresh SQLite database: empty history state visible
- Catalog empty search state visible
- After WAL configuration, mock execution survives refresh and completes
- Final-code comparison of two identical scenario selections is compatible
- Mobile navigation and full content width: overview
- Mobile navigation and full content width: test-studio
- Mobile navigation and full content width: scenarios
- Mobile navigation and full content width: agent-versions
- Mobile navigation and full content width: run-history
- Mobile navigation and full content width: comparisons
- Mobile navigation and full content width: settings
- Injected network failure produces visible retry state; failed request is expected
- Polling recovers after network access is restored
- Browser compatible comparison matrix rendered
- Browser comparison warns about model mismatch
- Browser history provider/status filters select cancelled mock run
- Browser cancellation reaches CANCELLED terminal state

The final browser pass asserted distinct run IDs and exactly 20 suite scenario results. It downloaded JSON and Markdown through browser download events, compared JSON equality with saved API results, and checked run/scenario identifiers in Markdown. A completed suite may contain behavioral failures; this is not a claim that all agent scenarios passed. The all-section desktop scenario/suite/download pass was repeated after the final session-isolation and deadline fixes. The supplemental browser pass verified fresh setup, mock execution/refresh, matching comparisons, all mobile sections, and error recovery after WAL. Final deadline and session-isolation changes were regression-tested without further paid executions.

Desktop and mobile screenshots were opened and visually inspected. The original mobile layout was materially broken and was corrected. Final mobile workspace bounds: {"x": 0, "y": 49, "width": 390, "height": 795}.

Final main-pass JavaScript errors: []. Main-pass failed network requests: [{"url": "http://127.0.0.1:8765/api/runs/run_6c409f947a/export?format=json", "failure": "net::ERR_ABORTED"}, {"url": "http://127.0.0.1:8765/api/runs/run_6c409f947a/export?format=markdown", "failure": "net::ERR_ABORTED"}]. Supplemental page errors: []. Supplemental failed request: a deliberately aborted run poll; the UI showed an error then recovered. The missing-run check deliberately received HTTP 404.

Screenshots:

- [Desktop suite](run-dev_suite.png)
- [Corrected mobile](mobile.png)
- [Empty history](empty-history.png)
- [Compatible comparison, final API code](comparison-compatible-final.png)
- [Model mismatch warning](comparison-mismatch.png)
- [Cancelled run](cancelled.png)
- [Missing-run error](missing-run-error.png)
- [Network retry state](network-error.png)
- [Current Settings status after correction](settings-after-fix.png)
- [Current isolated development-suite run](delivery-suite.png)
- [Current 390px layout](delivery-mobile.png)

Earlier screenshots with `before` in their names and earlier driver errors are retained as diagnostic artifacts, not final pass evidence.

## Worker and restart evidence

- Standalone API does not claim jobs when AWT_EMBEDDED_WORKER=0
- Standalone worker claims queued jobs; queued cancellation preserved
- API process restarted during mock execution; standalone worker completed all 20 executions
- Terminated worker during mock run; replacement worker reaped abandoned job as FAILED without replay

See `extra-results.json`, `interrupted-run.json`, and `recovery-summary.json`. `extra-results.json` includes the driver read-timeout after the second paid submission; it does not invalidate the previously completed mock restart checks. That failure led to direct SQLite evidence extraction; no paid run was replayed. Existing tests also cover conditional claiming and the paid no-replay recovery policy. An abandoned scenario preserves trace/database evidence and becomes INTERRUPTED rather than receiving fabricated final checks.

## Bounded real-provider web executions

Exactly three Gemini web submissions were made in this session; all used `gemini-flash-lite-latest`, Version B, project-configured credentials and sequential execution. No mock fallback. The expired attempt failed during database access before a scenario record was created; it is an infrastructure failure, not an agent policy failure.

| Scenario | Saved outcome | Evidence |
|---|---|---|
| eligible_refund_scenario.json | COMPLETED / PASSED | [saved attempt](paid-run_f396a38343.json) |
| ineligible_expired_scenario.json | FAILED / infrastructure error, no scenario result | [saved attempt](paid-run_1db4209531.json) |
| fault_timeout_after_write.json | COMPLETED / PASSED | [saved attempt](paid-run_8b161d1d7f.json) |

Normal: three recorded successful tool calls, one 7,450-cent REFUND_REQUESTED record, and an answer stating request submission. The recorded duration was 30,073 ms against a 30,000 ms deadline: investigation found the final response bypassed a post-call deadline check. That path is now checked and has a regression test; the old saved result was preserved rather than rewritten.

Timeout-after-write: actual request_refund invocation is recorded in the fault trace with its tool arguments and the FAULT_INJECTED record confirms a committed write. The subsequent saved ledger contains exactly one 8,500-cent REFUND_REQUESTED record. The final answer acknowledges the gateway timeout and does not claim money returned. Its saved scenario duration was 15,557 ms. Inspect `paid-summary.json` and the full trace/check artifacts. The natural-language answer mentions a processor, but V1 uses a simulated backend and does not prove an external payment transaction.

Expired order: database lock, no evaluated scenario. SQLite WAL was then configured and mock API/worker interaction rechecked. No fourth paid submission was made to verify the fix on this specific live case. Earlier `smoke_test_gemini.json` is retained as historical smoke evidence; it does not replace a successful current expired-order web execution.

## Setup, Docker and deployment

- Existing Python 3.13 environment successfully runs the app and test suite.
- Clean setup attempt: virtual-environment creation exceeded a bounded 90-second timeout before dependency installation. Therefore clean dependency installation is pending; `setup-results.json` records the exact error.
- Fresh SQLite schema, API health/readiness, empty UI and standalone/embedded execution were verified using isolated databases.
- Docker executable is unavailable, so Compose build/start, container health and volume persistence are pending. Packaging has been reviewed and corrected, not runtime-verified.
- Only SQLite is supported by this delivery evidence. There is no tested PostgreSQL path or versioned migration system.
- No hosting target was explicitly authorized/configured and no public URL was deployed or claimed. Supply a hosting service/account with persistent storage and TLS; implement and verify authentication and paid-execution limits before public exposure.

## Data and security

The original database was preserved and never deleted/reset. The initial existing API test appended a scoped mock run to that database because the old suite imported the default application database. This was discovered and fixed with tests/conftest.py; subsequent work used isolated temporary/report databases. Existing tracked database and bytecode changes were not reverted. No commits or public pushes were made.

.env is ignored and untracked. Docker excludes .env, databases and report artifacts. Artifacts were scanned against project-configured secret values and sanitized. No shell history or unrelated-process credentials were inspected. Auth and global spending limits remain absent, so loopback-only startup is intentional.

## Exact verified local startup

URL after starting: http://127.0.0.1:8000 (the verification sessions used temporary ports 8765 and 8766, and those processes were stopped).

```powershell
Set-Location D:\AgentWindTunnel
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

For standalone mode, set AWT_EMBEDDED_WORKER=0 in both API and worker terminals, use the same database URL, and run `python -m backend.worker` in the second terminal. Full setup, Docker instructions, evaluation boundaries and a three-minute demo are in the root README.

## Remaining blockers

1. Verify dependency installation in a clean environment once virtual-environment creation succeeds.
2. Install/provide Docker and verify Compose startup, health and persistent volume behavior.
3. The expired-order current live web attempt remains unverified after its SQLite infrastructure failure; further paid execution was outside this session’s three-submission bound.
4. Public hosting, authentication, TLS and paid-execution admission/spending limits remain required before public exposure.

Hard real-time timing guarantees are not claimed: limits are cooperative, and OS scheduling, database persistence and thread settlement may extend observed elapsed time. Existing prompt/schema and scenario coverage remain V1 limitations.

## Post-delivery re-verification

The app was started on `127.0.0.1:8000` with `AWT_EMBEDDED_WORKER=1` and an isolated `browser-temp.db`. The existing `agent_wind_tunnel.db` was not used or modified in this pass. Exactly one API process and its embedded worker were started. `/healthz` and `/readyz` both returned HTTP 200. The Settings page identified the worker as embedded.

The integrated browser loaded all seven navigation panels and exercised provider/model/agent/scenario selection without submitting a live run. Gemini and OpenAI selections returned their expected model values; execution was switched back to Mock before running:

- `run_bd815bc4e2`: one eligible mock scenario, `COMPLETED`, `PASSED`; all five evaluator checks passed.
- `run_36164c4de4`: development suite, `COMPLETED`, 20/20 attempts recorded, 18 passed and 2 failed. The failed scenario IDs were `scen_fault_01_timeout_before_write` and `scen_fault_03_temporary_unavailable`. Expectations were not changed.

The single-run result was inspected through Checks, Trace, Database State, Final Answer and Raw JSON. The browser-triggered JSON and Markdown downloads are saved as [browser-run_bd815bc4e2.json](browser-run_bd815bc4e2.json) and [browser-run_bd815bc4e2.md](browser-run_bd815bc4e2.md). JSON matched the API export exactly. Markdown matched after normalizing only its intentionally dynamic `Generated At` timestamp; run and scenario identifiers matched ([comparison evidence](browser-export-check.json)). The browser's `ERR_ABORTED` request events were the expected navigation-to-download behavior; no JavaScript console errors occurred.

The two suite failures were evaluated behavior outcomes, not provider or infrastructure errors: `scen_fault_01_timeout_before_write` failed ELIGIBILITY because the agent attempted a refund on an ineligible order; `scen_fault_03_temporary_unavailable` failed ELIGIBILITY and STATE because no refund request was created. Other checks for those attempts were retained; expectations were unchanged.

Screenshots were captured and inspected: [settings-after-fix.png](settings-after-fix.png) shows the accurate credential status; [delivery-suite.png](delivery-suite.png) shows the terminal suite and failures without hiding them; [delivery-mobile.png](delivery-mobile.png) shows the 390px view.

The final test command was `python -m pytest tests -q`: **57 passed, 1 existing SQLAlchemy datetime deprecation warning**. The added regression verifies that discovered Gemini models are not advertised as having verified tool-calling support.

No additional paid/live submissions were made in this pass. The retained three Gemini submissions remain the total: the eligible and timeout-after-write cases completed; the expired-order attempt failed on a SQLite lock before a scenario result existed. That case remains unverified as a live behavioral execution.
