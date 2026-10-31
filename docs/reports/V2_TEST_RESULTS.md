# AgentWindTunnel V2 — Verified Automated Test Results Report

**Execution Date:** October 31, 2026  
**Environment:** Python 3.13.3 (Windows x64)  
**Test Framework:** Pytest 9.1.1, Pytest-Asyncio 1.4.0, AnyIO 4.11.0, Playwright 1.63.0  
**Overall Result:** **85 PASSED, 0 FAILED, 0 WARNINGS** in 17.66s

---

## 1. Test Suite Summary Matrix

| Category | Test File | Tests Passed | Tests Failed | Execution Time |
| :--- | :--- | :---: | :---: | :---: |
| **Agent Runner Core** | `tests/test_agent_runner.py` | 6 | 0 | 0.81s |
| **API Endpoints & Routing** | `tests/test_api.py` | 15 | 0 | 1.15s |
| **Browser UI Regressions** | `tests/test_browser_ui_regressions.py` | 4 | 0 | 0.14s |
| **Database & Worker Reliability** | `tests/test_database_worker_reliability.py` | 3 | 0 | 1.44s |
| **Delivery Regressions** | `tests/test_delivery_regressions.py` | 9 | 0 | 1.65s |
| **Evaluation Quality & Pricing** | `tests/test_evaluation_quality.py` | 3 | 0 | 1.29s |
| **Evaluator Negative Tests** | `tests/test_evaluator_negative.py` | 5 | 0 | 0.45s |
| **Execution Budgets & Limits** | `tests/test_execution_limits.py` | 4 | 0 | 0.62s |
| **Fault Injection Behaviors** | `tests/test_fault_behaviors.py` | 6 | 0 | 0.98s |
| **Playwright Browser E2E** | `tests/test_playwright_e2e_sections.py` | 1 | 0 | 6.21s |
| **Queue Worker Lifecycle** | `tests/test_queue_worker.py` | 4 | 0 | 0.35s |
| **Refund Domain Service** | `tests/test_refund_service.py` | 6 | 0 | 0.28s |
| **Scripted Baseline Runner** | `tests/test_scripted_runner.py` | 2 | 0 | 0.12s |
| **Security & Auth Hardening** | `tests/test_security_hardening.py` | 6 | 0 | 0.65s |
| **Suite Coverage & Partitions** | `tests/test_suite_coverage.py` | 4 | 0 | 0.15s |
| **V1 Operational Baseline** | `tests/test_v1_operational_readiness.py` | 7 | 0 | 1.36s |
| **TOTAL** | **16 Test Suites** | **85** | **0** | **17.66s** |

---

## 2. Detailed Breakdown of New & Hardened Tests

### 2.1 Security & Authentication (`tests/test_security_hardening.py`)
1. `test_public_endpoints_accessible_without_auth`: Verified that `/health`, `/healthz`, `/readyz`, and `/` remain unconditionally accessible for container health checks and UI loading.
2. `test_local_dev_mode_permits_anonymous_access`: Verified zero-friction local developer mode when `AWT_REQUIRE_AUTH=0`.
3. `test_authentication_enforcement_when_configured`: Verified that when `AWT_REQUIRE_AUTH=1`, unauthenticated calls receive HTTP 401, while calls with valid Bearer token or `X-API-Key` header succeed with HTTP 200.
4. `test_rate_limiter_unit`: Verified sliding-window in-memory rate limiter rejecting requests beyond configured RPM.
5. `test_paid_provider_guard_limits`: Verified server-side concurrency throttles and token budget caps on paid provider calls.
6. `test_credential_sanitization`: Verified regex redaction masking Google AIza, AQ, and OpenAI sk- keys in error responses.

### 2.2 Database & Worker Reliability (`tests/test_database_worker_reliability.py`)
1. `test_concurrent_worker_claiming_no_race`: Spawns 5 racing worker threads; verifies that exactly 1 worker claims the queued job with atomic row updates and zero duplicate execution.
2. `test_cancellation_token_blocks_late_writes`: Verified that an in-flight tool call whose timeout or cancellation fires triggers an immediate rollback before database commit.
3. `test_paid_abandoned_job_never_replayed`: Confirmed that orphaned paid jobs are marked `FAILED` without auto-retry, preventing duplicate API charges.

### 2.3 Evaluation Quality & Cost Tracking (`tests/test_evaluation_quality.py`)
1. `test_cost_calculation_semantics`: Verified that mock runs return $0.00 while Gemini and OpenAI models compute accurate microcents.
2. `test_failure_classification_behavioral_vs_provider`: Verified runner returns `failure_category` accurately distinguishing behavioral violations from operational timeouts and provider errors.
3. `test_comparison_statistical_confidence`: Verified that A/B comparisons with sample sizes under 10 display an explicit statistical warning.

### 2.4 Browser E2E Automation (`tests/test_playwright_e2e_sections.py`)
1. `test_playwright_all_seven_sections`: Spawns an isolated live FastAPI Uvicorn instance on an ephemeral port, navigates through all 7 dashboard sections (Overview, Test Studio, Scenarios Catalog, Agent Versions, Run History, Comparisons, Settings), and asserts DOM visibility with zero uncaught console errors.

---

## 3. Deprecation Warning Elimination Evidence

In V1 baseline execution, SQLAlchemy emitted:
```text
C:\Users\...\schema.py:3624: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version.
```
In V2, all models use `datetime.datetime.now(datetime.timezone.utc)` via the `utc_now()` helper in `backend/database/models.py`. The full test suite executes with **0 warnings**.

