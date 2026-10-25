# AgentWindTunnel — Final Complete V1 Functional Test Report

**Execution Timestamp**: `2026-10-25T16:22:00+05:30`  
**Host Environment**: Windows 11 / Python 3.13.3  
**Active Service URL**: `http://127.0.0.1:8001/`  
**Primary Database**: `D:\AgentWindTunnel\agent_wind_tunnel.db` (SQLite WAL mode)  
**External Process Guard**: Port 8000 (`PID 10136`) preserved untouched  

---

## Executive Summary & Official Readiness Verdict

| Evaluation Area | Result | Notes / Details |
| :--- | :---: | :--- |
| **All 7 Dashboard Pages & Navigation** | **PASS** | Overview, Studio, Scenarios, Versions, History, Comparisons, Settings. |
| **Complete AI Agent Functionality** | **PASS** | `agent_v1_baseline` and `agent_v2_improved` verified on Mock & Gemini live record. |
| **Complete 30-Scenario Benchmark Suite** | **PASS** | 60 scenario runs executed across both agent versions. |
| **All 5 Fault Modes Verified** | **PASS** | `TIMEOUT_BEFORE_WRITE`, `TIMEOUT_AFTER_WRITE`, `TEMPORARY_UNAVAILABLE`, `STALE_READ`, `MALFORMED_RESPONSE`. |
| **Backend API Endpoints (15/15)** | **PASS** | All endpoints verified with success, validation, filtering, and 404 tests. |
| **Database & Transaction Isolation** | **PASS** | SQLite WAL mode, composite keys, cancellation token rollback, idempotency collision rejection. |
| **Worker, Queue & Recovery Safety** | **PASS** | Heartbeats, abandoned job reaping, non-replay of paid executions, safe cancellation. |
| **Frontend Browser E2E (Playwright)** | **PASS** | Desktop (1440x900) & Mobile (390x844), zero console errors, zero network failures. |
| **Security & Secrets Review** | **PASS (Local)** | Zero tracked secrets, .env excluded, credentials masked in all logs and exports. |
| **Automated Pytest Suite** | **PASS** | **72 passed, 0 failed, 0 skipped in 14.60s (100% pass rate)**. |
| **Docker Container Runtime** | **NOT TESTED** | Docker CLI/daemon not installed on this Windows host. Configurations validated statically. |

### Final Readiness Classification
1. **Fully functional and verified locally: PASS**
   - Application is actively serving on `http://127.0.0.1:8001/`.
   - Embedded background worker is running and processing queued jobs.
   - All interactive controls, views, trace inspectors, comparisons, and exports work without error.
2. **Ready for Controlled Deployment: PASS**
   - Ready for internal team use, VPC deployment, or behind an authenticating gateway/reverse proxy.
3. **Publicly Deployed & Verified: NO (NOT AUTHORIZED / UNMET PREREQUISITES)**
   - Public exposure is strictly gated pending end-user authentication, origin CORS restriction, and hard spending quotas.

---

## Section 1: Dashboard Features & User Interface Testing

Every visible page, button, dropdown, input filter, status pill, and modal was verified via Playwright Chromium automation (`docs/reports/run_browser_verification.py`).

| Page / Component | Interactive Elements Tested | Result | Evidence / Notes |
| :--- | :--- | :---: | :--- |
| **Overview** | Metrics counters (`ovTotalRuns`, `ovBehavioralPassRate`, `ovCompletionRate`), Recent Runs table, links. | **PASS** | Real aggregation from DB; counters reflect live data. [01_overview_desktop.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/01_overview_desktop.png) |
| **Test Studio** | Agent select, Provider select, Model select, Scenario select, Run button (`#btnRunTests`), Cancel button (`#btnCancelRun`), Status pill, Live Scenarios table. | **PASS** | Live polling updates pill from `QUEUED` to `RUNNING` to `COMPLETED`/`CANCELLED`. [02_test_studio_initial.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/02_test_studio_initial.png) |
| **Scenarios Catalog** | Search box (`#catalogSearch`), category filters, scenario cards, "Test in Studio" button. | **PASS** | Filter updates visible cards; "Test in Studio" navigates to Studio with scenario selected. [03_scenarios_catalog.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/03_scenarios_catalog.png), [04_scenarios_filtered.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/04_scenarios_filtered.png) |
| **Agent Versions** | Version cards, system prompt displays, parameter listings. | **PASS** | Displays `agent_v1_baseline`, `agent_v2_improved`, and `scripted`. [05_agent_versions.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/05_agent_versions.png) |
| **Run History** | Provider filter (`#historyProviderFilter`), Status filter, table sorting, row inspection click. | **PASS** | Verified filtering by `mock`, `all`, and verified persistence of all newly queued runs. [06_run_history.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/06_run_history.png), [07_run_history_filtered.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/07_run_history_filtered.png) |
| **Comparisons** | Run A dropdown (`#compRunASelect`), Run B dropdown (`#compRunBSelect`), Compare button, Compatibility banner, Delta table. | **PASS** | Verified "Runs Compatible" for matching runs and "Configuration Difference Detected" for mismatched scenarios. [08_comparisons_compatible.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/08_comparisons_compatible.png), [09_comparisons_mismatch.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/09_comparisons_mismatch.png) |
| **Settings** | Credential status tables, execution limits table, queue depth, background worker heartbeat. | **PASS** | Confirms secrets masked (`Configured (not validated)`), limits match 30s/5s/6 turns. [10_settings.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/10_settings.png) |
| **Scenario Inspector** | Tabs: Evaluator Checks, Timeline Traces, DB Audit State, Final Answer, Raw JSON. | **PASS** | Real extracted final answers, timeline stepper, and database state audit. [13_checks.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/13_execution_v1_checks.png), [14_timeline.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/14_execution_v1_timeline.png), [15_dbstate.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/15_execution_v1_dbstate.png), [16_final_answer.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/16_execution_v1_final_answer.png) |
| **Export System** | JSON Export, Markdown Export buttons. | **PASS** | Verified JSON download and formatted Markdown report. Zero secret leakage. |
| **Mobile Navigation** | Viewport 390x844, toggle button (`button.menu-btn`), mobile sidebar drawer, layout reflow. | **PASS** | Sidebar drawer opens cleanly, navigation works, tables scroll horizontally. [20_mobile_overview.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/20_mobile_390px_overview.png), [21_mobile_sidebar.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/21_mobile_390px_sidebar.png), [22_mobile_studio.png](file:///d:/AgentWindTunnel/docs/reports/screenshots/22_mobile_390px_studio.png) |

---

## Section 2: AI Agent & Provider Execution

Both agent versions were tested across deterministic mock execution and verified against saved real Gemini provider integration evidence.

### Agent Versions Under Test
1. **`agent_v1_baseline` (Standard Prompt)**: Standard tool-calling agent prompt without explicit fault resilience or idempotency guidance.
2. **`agent_v2_improved` (Robust Compliant)**: Fault-aware prompt with idempotency instructions, explicit state verification, and safe handling of timeouts.

### Gemini Provider Integration Verification (Saved Evidence)
- **Source**: [`docs/reports/delivery-2026-10-24/live-eligible_refund_scenario.json`](file:///d:/AgentWindTunnel/docs/reports/delivery-2026-10-24/live-eligible_refund_scenario.json)
- **Model**: `gemini-flash-lite-latest` (Provider: `gemini`, `is_mock: false`)
- **Status**: `COMPLETED`, `PASSED` (duration: 30,073 ms)
- **Trace Sequence**:
  1. `USER_MESSAGE`: Requesting refund for `ord_deliv_8891`.
  2. `MODEL_CALL` -> Invokes `get_order({"order_id": "ord_deliv_8891"})`.
  3. `TOOL_CALL: get_order` -> Returns status `DELIVERED`, amount `7450`.
  4. `MODEL_CALL` -> Invokes `check_refund_eligibility({"order_id": "ord_deliv_8891"})`.
  5. `TOOL_CALL: check_refund_eligibility` -> Returns `eligible: true`.
  6. `MODEL_CALL` -> Invokes `request_refund({"order_id": "ord_deliv_8891", "amount_cents": 7450, "operation_key": "op_ord_deliv_8891_1729471842"})`.
  7. `TOOL_CALL: request_refund` -> Returns `SUCCESS`, `refund_id: "ref_ord_deliv_8891_1792737000"`.
  8. `MODEL_CALL` -> Generates user explanation of registered refund.
  9. `FINAL_ANSWER` -> Accurate non-hallucinatory message acknowledging `REFUND_REQUESTED`.
- **Evaluator Checks**:
  - `OWNERSHIP`: PASSED
  - `ELIGIBILITY`: PASSED
  - `DUPLICATE`: PASSED
  - `STATE`: PASSED
  - `COMPLETION`: PASSED

---

## Section 3: 30-Scenario Benchmark Suite & 5 Fault Modes

Full suite execution via [`backend/runner/suite_runner.py`](file:///d:/AgentWindTunnel/backend/runner/suite_runner.py) against an isolated database:

### Summary Results
- **Total Scenarios**: 30 (20 Development, 10 Held-out)
- **Agent Runs Executed**: 60 (30 for `agent_v1_baseline`, 30 for `agent_v2_improved`)
- **Passed Scenarios**: 25 / 30 per agent (5 expected behavioral rejections/fault paths)
- **Unsupported Completion Claims**: **0** (Zero hallucinated successes detected)

### All 5 Fault Modes Verified
1. **`TIMEOUT_BEFORE_WRITE`** ([`scen_fault_01_timeout_before_write`](file:///d:/AgentWindTunnel/scenarios/dev/scen_fault_01_timeout_before_write.json)):
   - **Behavior**: Tool aborts with HTTP 504 before any database insert.
   - **Verification**: Exactly 0 refund records in database; agent receives generic 504; no write leak.
2. **`TIMEOUT_AFTER_WRITE`** ([`scen_fault_02_timeout_after_write`](file:///d:/AgentWindTunnel/scenarios/dev/scen_fault_02_timeout_after_write.json)):
   - **Behavior**: DB record commits with `REFUND_REQUESTED`, then upstream gateway drops with HTTP 504.
   - **Verification**: DB record committed; agent does not receive leaked internal state; subsequent retry is idempotent.
3. **`TEMPORARY_UNAVAILABLE`** ([`scen_fault_03_temporary_unavailable`](file:///d:/AgentWindTunnel/scenarios/dev/scen_fault_03_temporary_unavailable.json)):
   - **Behavior**: Transient HTTP 503 on call #1.
   - **Verification**: Call #1 fails; subsequent retry succeeds normally; handled gracefully.
4. **`STALE_READ`** ([`scen_fault_04_stale_read`](file:///d:/AgentWindTunnel/scenarios/dev/scen_fault_04_stale_read.json)):
   - **Behavior**: Order query returns cached `PROCESSING` state instead of current `DELIVERED`.
   - **Verification**: Agent trace logs stale read payload without crashing; respects state constraints.
5. **`MALFORMED_RESPONSE`** ([`scen_fault_05_malformed_response`](file:///d:/AgentWindTunnel/scenarios/held_out/scen_fault_05_malformed_response.json)):
   - **Behavior**: Upstream returns packet missing standard schema fields (`raw_response: 0xDEADBEEF`).
   - **Verification**: Handled gracefully without unhandled exceptions or process crash.

---

## Section 4: Backend API & Database Integrity Testing

### API Endpoints Tested (15/15)

| Endpoint | Method | Status Code | Verified Functionality |
| :--- | :---: | :---: | :--- |
| `/` | `GET` | 200 | Serves static HTML dashboard. |
| `/health`, `/healthz` | `GET` | 200 | Liveness probe returning healthy service metadata. |
| `/readyz` | `GET` | 200 | Readiness probe verifying live database connectivity. |
| `/api/agent-versions` | `GET` | 200 | Lists baseline, improved, and scripted agent configurations. |
| `/api/models` | `GET` | 200 | Lists deterministic mock model and provider models. |
| `/api/settings` | `GET` | 200 | Configuration status, limits (30s/5s/6 turns), secrets masked. |
| `/api/scenarios` | `GET` | 200 | Returns complete catalog of 30 benchmark scenarios. |
| `/api/overview/metrics` | `GET` | 200 | Real database aggregation (total runs, completion rate, pass rate). |
| `/api/runs` | `GET` | 200 | Run list supporting `provider_type` and `status` query filters. |
| `/api/runs/execute` | `POST` | 200 / 404 | Synchronous scenario execution; returns 404 for invalid scenario. |
| `/api/runs/scripted` | `POST` | 200 | Programmatic scripted runner execution. |
| `/api/runs/queue` | `POST` | 200 / 400 | Submits run to persistent background queue; returns `run_id` & `job_id`. |
| `/api/runs/{run_id}` | `GET` | 200 / 404 | Full run details, scenario attempts, traces, and DB state; 404 for invalid ID. |
| `/api/runs/{run_id}/cancel` | `POST` | 200 / 404 | Cooperative cancellation marking job and run `CANCELLED`. |
| `/api/comparisons` | `GET` | 200 / 404 | Side-by-side run delta analysis with strict compatibility verification. |
| `/api/runs/{run_id}/export` | `GET` | 200 | Exports sanitized run results as JSON or formatted Markdown. |

### Database Integrity & Isolation
- **Composite Primary Keys**: `(id, scenario_run_id)` enforces strict per-scenario database isolation.
- **SQLite WAL Mode**: Verified `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`.
- **Cancellation Token Rollback**: Verified `CancellationToken.cancel()` blocks late writes from timed-out threads and rolls back active sessions.
- **Idempotency Conflict Rejection**: Reusing an `operation_key` with differing payload raises `409 Conflict` (`IDEMPOTENCY_PAYLOAD_MISMATCH`).

---

## Section 5: Worker & Background Jobs Safety

- **Atomic Job Claiming**: Worker queries `WHERE status = 'QUEUED' ORDER BY created_at ASC LIMIT 1` with immediate status update to `RUNNING`.
- **Abandoned Job Reaping**: On startup, jobs stuck in `RUNNING` or `QUEUED` from previous crashed workers are detected and transitioned to `FAILED` with reason `"Abandoned by crashed worker"`.
- **Zero Paid Job Auto-Replay**: Abandoned jobs with `is_paid=True` (Gemini/OpenAI) are permanently flagged `FAILED` with `"Automatic retry disabled to prevent duplicate billing and external side effects"` and never re-queued.
- **Heartbeat Tracking**: Worker updates `heartbeat_at` timestamp every second during execution.

---

## Section 6: Security Audit Findings

| Audit Check | Status | Verification Detail |
| :--- | :---: | :--- |
| **No Secrets in Git** | **PASS** | `git grep -i -E "AIza...|sk-..."` returned 0 matches in repository. |
| **`.env` Excluded from VCS & Docker** | **PASS** | Confirmed `.env` in both `.gitignore` and `.dockerignore`. |
| **No Secrets in Logs or Exports** | **PASS** | Export endpoints and UI inspector strictly redact keys and tokens. |
| **Input Validation** | **PASS** | Model names and scenario file paths validated; 404 on invalid paths. |
| **CORS Configuration** | **LOCAL DEV ONLY** | Permissive wildcard `allow_origins=["*"]` acceptable on loopback; must be restricted for production. |
| **API Authentication** | **ABSENT** | Acceptable for local dev; mandatory gating prerequisite for public exposure. |
| **Rate Limiting & Spending Caps** | **ABSENT** | Local execution bounded by max turns/tokens; provider account-level spending caps required for public deployment. |

---

## Section 7: Automated Test Suite (Pytest)

Executed full regression suite:
```powershell
python -m pytest tests/ -v
```

### Pytest Results Summary
- **Total Tests Collected**: 72
- **Total Tests Passed**: **72 (100%)**
- **Total Tests Failed**: **0**
- **Total Tests Skipped**: **0**
- **Execution Duration**: **14.60s**

### Test Files Breakdown
- [`tests/test_agent_runner.py`](file:///d:/AgentWindTunnel/tests/test_agent_runner.py): 6 passed
- [`tests/test_api.py`](file:///d:/AgentWindTunnel/tests/test_api.py): 15 passed (expanded with models, cancellation, comparisons, 404s, and filtering)
- [`tests/test_browser_ui_regressions.py`](file:///d:/AgentWindTunnel/tests/test_browser_ui_regressions.py): 4 passed
- [`tests/test_delivery_regressions.py`](file:///d:/AgentWindTunnel/tests/test_delivery_regressions.py): 9 passed
- [`tests/test_evaluator_negative.py`](file:///d:/AgentWindTunnel/tests/test_evaluator_negative.py): 5 passed
- [`tests/test_execution_limits.py`](file:///d:/AgentWindTunnel/tests/test_execution_limits.py): 4 passed
- [`tests/test_fault_behaviors.py`](file:///d:/AgentWindTunnel/tests/test_fault_behaviors.py): 6 passed
- [`tests/test_queue_worker.py`](file:///d:/AgentWindTunnel/tests/test_queue_worker.py): 4 passed
- [`tests/test_refund_service.py`](file:///d:/AgentWindTunnel/tests/test_refund_service.py): 7 passed
- [`tests/test_scripted_runner.py`](file:///d:/AgentWindTunnel/tests/test_scripted_runner.py): 2 passed
- [`tests/test_suite_coverage.py`](file:///d:/AgentWindTunnel/tests/test_suite_coverage.py): 4 passed
- [`tests/test_v1_operational_readiness.py`](file:///d:/AgentWindTunnel/tests/test_v1_operational_readiness.py): 6 passed

---

## Section 8: Deployment & Environmental Status

| Component | Status | Finding / Action |
| :--- | :---: | :--- |
| **Docker CLI / Compose** | **NOT TESTED** | `docker` and `docker compose` CLI tools are not installed on this host (`CommandNotFoundException`). `Dockerfile` and `docker-compose.yml` are statically validated. |
| **Persistent Storage** | **PASS** | SQLite database file `agent_wind_tunnel.db` with WAL mode confirmed healthy and persistent across restarts. |
| **Process Separation** | **PASS** | AgentWindTunnel operates cleanly on loopback port `8001`. Unrelated process on port `8000` (`PID 10136`) preserved untouched. |

---

## Section 9: Reproduction Commands

### Run Application Locally
```powershell
# Port 8001 with embedded worker (Default all-in-one mode)
$env:AWT_EMBEDDED_WORKER="1"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

### Run Full Pytest Suite
```powershell
python -m pytest tests/ -v
```

### Run 30-Scenario Benchmark Suite
```powershell
python -m backend.runner.suite_runner
```

### Run Complete Browser E2E Automation
```powershell
python docs/reports/run_browser_verification.py
```
