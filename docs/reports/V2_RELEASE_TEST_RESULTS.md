# AgentWindTunnel V2 — Release Test Results Report

**Date:** October 31, 2026  
**Auditor Roles:** QA Automation Lead, Senior Systems Architect  
**Test Suite:** Pytest 9.1.1, Playwright (Chromium Headless), Python 3.13.3  
**Working Directory:** `D:\AgentWindTunnel\AgentWindTunnel`  
**Execution Command:** `python -m pytest -v`  
**Total Test Count:** **103 Collected / 103 Passed / 0 Failed / 0 Warnings**  
**Execution Duration:** 14.10 seconds (100% Pass Rate)

---

## 1. Test Suite Breakdown

| Suite File | Tests | Status | Scope & Purpose |
| :--- | :---: | :---: | :--- |
| `tests/test_agent_runner.py` | 6 | **VERIFIED** | Core runner execution: eligible flow, ineligible expired flow, fault timeout after write, credential failure detection, tool timeouts, and provider error classification. |
| `tests/test_api.py` | 15 | **VERIFIED** | FastAPI endpoints: `/health`, `/healthz`, `/readyz`, `/api/scenarios`, `/api/runs/scripted`, `/api/agent-versions`, `/api/runs`, `/api/overview/metrics`, `/api/settings`, `/api/models`, and 404 handlers. |
| `tests/test_browser_ui_regressions.py` | 4 | **VERIFIED** | Browser UI regression checks: index.html existence, final answer extraction, dynamic catalog scenario selection, and status pill reset behavior. |
| `tests/test_custom_http_agent.py` | 10 | **VERIFIED** | Custom HTTP agent adapter lifecycle: URL validation, ping success/timeout, schema generation, timeout errors, CRUD API, SSRF blocking, redirect rejection, and full scenario runner execution. |
| `tests/test_custom_scenario_builder.py` | 3 | **VERIFIED** | Custom scenario builder: path traversal prevention (`../../`), Pydantic schema validation, and CRUD / export / import API. |
| `tests/test_database_worker_reliability.py` | 4 | **VERIFIED** | Concurrency and atomicity: racing worker claiming (single job), racing worker claiming under paid concurrency ceiling (`AWT_MAX_CONCURRENT_PAID_JOBS`), cancellation token late-write blocking, and paid abandoned job non-replay. |
| `tests/test_delivery_regressions.py` | 9 | **VERIFIED** | Delivery regression safeguards: standalone mode embedded worker suppression, unverified model claims prevention, timeout evidence persistence, SQLite WAL mode verification, and deadline enforcement. |
| `tests/test_evaluation_quality.py` | 3 | **VERIFIED** | Evaluation quality checks: cost calculation semantics, failure classification (behavioral vs provider), and statistical confidence warnings on small samples. |
| `tests/test_evaluator_negative.py` | 5 | **VERIFIED** | Evaluator negative leak detection: unauthorized read detection, unauthorized write leak, attempted ineligible refund, duplicate operation key churn, and state amount mismatch. |
| `tests/test_execution_limits.py` | 4 | **VERIFIED** | Execution budget controls: tool call timeout interruption, turn limit interruption, token budget enforcement, and wall-clock timeout interruption. |
| `tests/test_fault_behaviors.py` | 6 | **VERIFIED** | Fault injection modes: timeout before write, timeout after write (commits before timeout), temporary unavailable retry, stale read cache return, malformed response handling, and timed out thread late-write rollback. |
| `tests/test_playwright_e2e_sections.py` | 1 | **VERIFIED** | Browser end-to-end automation: live Uvicorn instance, Chromium browser context, navigation across all 11 sections, custom agent registration form submission, custom scenario saving, failure analysis filter selection, and zero console errors. |
| `tests/test_queue_worker.py` | 4 | **VERIFIED** | Queue worker operations: atomic claim, mock job recovery, paid job abandonment non-replay, and job cancellation honoring. |
| `tests/test_refund_service.py` | 7 | **VERIFIED** | Domain logic & idempotency: customer ownership, 14-day eligibility boundary, expired order rejection, cancelled order rejection, idempotent refund requests, duplicate key rejection, and payload mismatch conflict rejection. |
| `tests/test_regression_comparison.py` | 2 | **VERIFIED** | Regression comparison engine: percentile calculations ($p50$/$p90$), tool call sequence drift, cost deltas, and markdown/JSON report exports. |
| `tests/test_scripted_runner.py` | 2 | **VERIFIED** | Deterministic scripted runner: eligible refund scenario and ineligible refund scenario execution. |
| `tests/test_security_hardening.py` | 8 | **VERIFIED** | Security controls: public endpoint unauth access, local dev anonymous access, authentication enforcement when `AWT_REQUIRE_AUTH=1`, sliding-window rate limiting, paid provider limits, credential sanitization, secret masking in API responses, and database-backed multi-process concurrency guards. |
| `tests/test_suite_coverage.py` | 4 | **VERIFIED** | Benchmark integrity: 30 scenario balance, category distribution, 5 fault mode coverage, and scenario JSON parse verification. |
| `tests/test_v1_operational_readiness.py` | 6 | **VERIFIED** | Operational guarantees: fresh database creation constraints, abandoned job reaping, paid Gemini abandonment non-replay, indeterminate evaluation on unresolved writes, cancellation token rollback, and idempotency payload mismatch rejection. |
| **TOTAL** | **103** | **VERIFIED** | **103 PASSED / 0 FAILED / 0 WARNINGS** |

---

## 2. Infrastructure & System Status

- **Docker Desktop Daemon:** **BLOCKED** (`Wsl/E_ACCESSDENIED` on Windows host blocks WSL2 initialization).
- **PostgreSQL Live Instance:** **BLOCKED** (No server running on host port 5432).
- **PostgreSQL Migration DDL:** **VERIFIED** (`alembic upgrade head --sql` generates 6,417 bytes of valid PostgreSQL DDL).
- **SQLite Concurrency & WAL:** **VERIFIED** (`PRAGMA journal_mode=WAL` with `busy_timeout=5000` enables concurrent readers and writers without lock contention).
- **Cloud Paid APIs:** **NOT TESTED** (Preserved mock simulator defaults to prevent unapproved external spend).
