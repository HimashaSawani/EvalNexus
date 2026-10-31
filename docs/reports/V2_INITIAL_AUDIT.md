# AgentWindTunnel V1 — Initial Engineering & Security Audit Report (V2 Baseline)

**Date:** October 31, 2026  
**Auditor:** Senior AI Systems & Reliability Lead, Security Engineer, QA Automation Lead  
**Audit Scope:** Full repository structure, application architecture, database, worker daemon, API security, test suite baseline, evaluator assertions, UI dashboard, and operational readiness.

---

## 1. Executive Summary

AgentWindTunnel V1 is a deterministic evaluation and fault-injection testing harness for AI agents operating in an e-commerce refund domain. The platform features an autonomous multi-turn agent loop, simulated refund tools, a SQLite-backed persistent job queue, deterministic evaluator assertions, and an interactive single-page dashboard.

An independent baseline verification was conducted on **Python 3.13.3 (Windows)** against the existing test suite:
- **Test Baseline Result:** **72 passed, 0 failed, 3 deprecation warnings** (in 8.40s).
- **Core Strengths:**
  - Robust simulated domain logic (`RefundService`) with multi-layered checks (ownership, 14-day eligibility, idempotency keys, duplicate detection, and cancellation token late-write blocking).
  - Clean separation between deterministic mock simulator (`MockToolCallingProvider`) and real paid providers (`RealOpenAIProvider` with Gemini/OpenAI compatibility).
  - Explicit non-replay guarantees for paid jobs upon worker crash or disconnection.
  - Comprehensive negative evaluator tests for data leaks and boundary violations.
- **Key Vulnerabilities & Operational Risks Identified:**
  - **CRITICAL:** Insecure CORS policy (`allow_origins=["*"]` combined with `allow_credentials=True`), violating security specifications and allowing unrestricted cross-origin requests.
  - **CRITICAL:** Missing authentication and authorization across all API endpoints, allowing unauthorized queueing of costly live LLM runs, arbitrary job cancellations, and configuration inspection.
  - **HIGH:** Absence of server-side rate limiting, concurrency throttles, and paid-provider spending limits, exposing operators to denial-of-wallet (DoW) and API quota exhaustion.
  - **HIGH:** Rudimentary, non-standard SQLite-only migration script (`backend/database/migrate.py`) lacking PostgreSQL compatibility and Alembic revision management.
  - **MEDIUM:** Incomplete CI/CD pipeline: GitHub Actions contains only a secret scanner (`security-scan.yml`) with zero automated test execution, dependency scanning, or container build validation.
  - **MEDIUM:** Python 3.12+ `datetime.datetime.utcnow()` deprecation warnings in database models (`backend/database/models.py`).
  - **LOW:** Lack of provider cost calculation estimates in trace logging despite token usage tracking.

---

## 2. Baseline Verification & Current Implementation Audit

### 2.1 Test Suite Verification
- **Command:** `python -m pytest -v`
- **Result:**
  ```text
  72 passed, 3 warnings in 8.40s
  ```
- **Deprecation Warnings:**
  - `datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).` (Originating from `backend/database/models.py:88` in `ScenarioRun.started_at`).

### 2.2 Application Entry Points
- **Web API & Embedded Worker Entry Point:** `backend.main:app` (Uvicorn ASGI server).
  - Contains optional embedded background worker thread controlled via `AWT_EMBEDDED_WORKER=1`.
- **Standalone Queue Worker Entry Point:** `backend.worker:QueueWorker` (`python -m backend.worker`).
- **CLI Direct Scenario Runner:** `backend.cli_runner` (`python -m backend.cli_runner`).
- **Smoke Test Tool:** `backend.runner.smoke_test` (`python -m backend.runner.smoke_test`).
- **Scenario Generator:** `backend.scenarios.generate_suite` (`python -m backend.scenarios.generate_suite`).

---

## 3. Detailed Audit Findings & Classifications

### [CRITICAL-01] Permissive CORS Configuration with Credentials Enabled
- **Severity:** CRITICAL
- **Affected File:** `backend/main.py` (lines 67–72)
- **Evidence:**
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  ```
- **Impact:**
  - Under CORS specifications, setting `allow_origins=["*"]` alongside `allow_credentials=True` is an invalid and insecure configuration that allows arbitrary third-party websites to issue cross-origin requests to the local/staging instance.
- **Proposed Fix:**
  - Introduce configurable trusted origins via environment variable `AWT_ALLOWED_ORIGINS` (defaulting strictly to `["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:3000"]`). Reject wildcard origins when credentials are enabled.

---

### [CRITICAL-02] Complete Absence of API Authentication and Authorization
- **Severity:** CRITICAL
- **Affected File:** `backend/main.py`
- **Evidence:**
  - Endpoints `/api/runs/execute`, `/api/runs/queue`, `/api/runs/{run_id}/cancel`, `/api/settings`, and `/api/runs/{run_id}` have zero authentication checks or API token dependencies.
- **Impact:**
  - Any client reachable over the network can:
    1. Trigger unthrottled live paid runs using Google Gemini or OpenAI, causing financial loss.
    2. Cancel in-flight benchmark executions initiated by other users or workers.
    3. Read raw execution traces and system configuration.
- **Proposed Fix:**
  - Implement a configurable API Key / Bearer token authentication dependency (`AWT_API_KEY`).
  - Support a clearly documented local-development bypass (`AWT_REQUIRE_AUTH=0` for local dev/testing), while enforcing authentication by default in production/staging environments.
  - Add client headers support to dashboard and test harnesses.

---

### [HIGH-01] Missing Server-Side Paid Provider Concurrency & Spending Controls
- **Severity:** HIGH
- **Affected Files:** `backend/main.py`, `backend/worker.py`, `backend/agent/provider.py`
- **Evidence:**
  - `/api/runs/queue` permits arbitrary submission of runs with `provider_type="gemini"` or `provider_type="openai"`.
  - No rate limiting or concurrency bounds are enforced for paid executions; workers process jobs sequentially, but queue depth and turn budgets are unbound.
- **Impact:**
  - Risk of unintended cloud provider billing spikes, rate-limit bans (HTTP 429), or exhaustion of user API quotas.
- **Proposed Fix:**
  - Implement an in-memory rate limiter / concurrency semaphore for paid provider requests (`AWT_MAX_CONCURRENT_PAID_JOBS=2`).
  - Introduce per-run and global token budget limits (`AWT_MAX_TOKENS_PER_RUN=25000`).
  - Return clear HTTP 429 (Too Many Requests) when paid queue thresholds are exceeded.

---

### [HIGH-02] Lack of Alembic Migrations & Unverified PostgreSQL Dialect Support
- **Severity:** HIGH
- **Affected Files:** `backend/database/migrate.py`, `backend/database/connection.py`, `backend/database/models.py`
- **Evidence:**
  - `migrate.py` is a 27-line script executing raw SQLite PRAGMA commands (`PRAGMA table_info(runs)` and `ALTER TABLE runs ADD COLUMN ...`).
  - No Alembic configuration (`alembic.ini` or `alembic/` migration tree) exists in the repository.
  - While `connection.py` supports non-SQLite connection strings, PostgreSQL connection pooling (`pool_size`, `max_overflow`), connection recycling, and dialect-specific JSON/DateTime behavior have not been formalized or tested.
- **Impact:**
  - Schema changes cannot be reliably tracked, applied, or rolled back in multi-developer or production PostgreSQL environments.
- **Proposed Fix:**
  - Initialize standard Alembic migration environment (`alembic.ini`, `alembic/env.py`, `alembic/versions/`).
  - Generate baseline initial migration covering all V1/V2 tables.
  - Preserve SQLite development compatibility (using WAL and busy timeouts) while providing tested PostgreSQL engine configuration.

---

### [MEDIUM-01] Python 3.12+ Deprecated DateTime Usage in Models
- **Severity:** MEDIUM
- **Affected File:** `backend/database/models.py` (line 88)
- **Evidence:**
  ```python
  started_at = Column(DateTime, default=datetime.datetime.utcnow)
  ```
- **Impact:**
  - Emits runtime deprecation warnings on Python 3.12/3.13; will fail on future Python versions when `datetime.utcnow()` is removed.
- **Proposed Fix:**
  - Replace `default=datetime.datetime.utcnow` with `default=utc_now` (defined at line 18 as `datetime.datetime.now(datetime.timezone.utc)`).

---

### [MEDIUM-02] Incomplete CI/CD Workflows
- **Severity:** MEDIUM
- **Affected File:** `.github/workflows/security-scan.yml`
- **Evidence:**
  - Only Gitleaks and TruffleHog secret scanning exist.
  - No automated test execution workflow (`pytest`).
  - No dependency vulnerability scanning (`pip-audit`).
  - No Docker container build verification or image vulnerability scan.
- **Impact:**
  - Regressions, broken dependencies, or Docker container failures are not caught automatically on pull requests.
- **Proposed Fix:**
  - Create `.github/workflows/ci.yml` running pytest across Python 3.11, 3.12, and 3.13.
  - Add dependency scanning (`pip-audit`) and container build verification.

---

### [MEDIUM-03] Evaluator Cost Calculation Missing
- **Severity:** MEDIUM
- **Affected Files:** `backend/runner/trace_logger.py`, `backend/runner/agent_runner.py`, `backend/database/models.py`
- **Evidence:**
  - `TraceEvent.cost_estimate` defaults to 0 and is never calculated for Gemini or OpenAI runs despite prompt/completion token metrics being recorded.
- **Impact:**
  - Users and operators cannot track testing expenditures or compare costs across agent versions.
- **Proposed Fix:**
  - Add deterministic token pricing calculation for real models (e.g. Gemini Flash Lite, GPT-4o-mini) and record micro-cents in trace events and scenario run summaries, with explicit documentation that mock runs cost $0.00.

---

### [LOW-01] Local Gitignored Files Present on Disk
- **Severity:** LOW
- **Affected Files:** `agent_wind_tunnel.db`, `agent_wind_tunnel.db-wal`, `agent_wind_tunnel.db-shm`, `.env`
- **Evidence:**
  - Local database and `.env` files are present in the working tree.
  - Verified that `.gitignore` correctly lists `*.db`, `*.db-wal`, `*.db-shm`, and `.env`.
  - Git history audit confirmed no committed credentials in git history (`git log` clean).
- **Proposed Fix:**
  - Retain `.gitignore` rules and provide structured cleanup scripts for developer environments.

---

## 4. Phase-by-Phase Remediation Plan

1. **Phase 2 — Security Hardening:**
   - Implement `AWT_API_KEY` authentication middleware and route dependencies.
   - Configure strict trusted CORS origin handling via `AWT_ALLOWED_ORIGINS`.
   - Add in-memory rate limiting and concurrency throttling for paid provider execution.
   - Add automated security regression tests.

2. **Phase 3 — Database & Worker Reliability:**
   - Fix `datetime.datetime.utcnow()` deprecation in `models.py`.
   - Initialize Alembic migrations for schema tracking.
   - Harden worker transaction isolation and retry handling for SQLite WAL / PostgreSQL.
   - Add database isolation and worker concurrency tests.

3. **Phase 4 — AI Evaluation Quality:**
   - Enhance failure classification (Behavioral vs Setup/Provider vs Timeout).
   - Add token cost calculation for paid providers.
   - Improve scenario comparison statistics and multi-run aggregates.

4. **Phase 5 — Dashboard Improvements:**
   - Update `backend/static/index.html` to support API Key headers.
   - Add explicit loading, empty, and error states.
   - Ensure accessible colors, status indicators, and responsive layouts.

5. **Phase 6 — Automated Verification:**
   - Run unit, API, evaluator negative, worker concurrency, and security tests.
   - Document pass/fail counts.

6. **Phase 7 — CI/CD & Operational Readiness:**
   - Add GitHub Actions CI workflow (tests, pip-audit, docker build check).
   - Document backup, restore, shutdown, and restart procedures.

7. **Phase 8 — Final Documentation & Audit:**
   - Generate `V2_FINAL_AUDIT.md`, `V2_TEST_RESULTS.md`, `V2_SECURITY_REVIEW.md`, and `V2_DEPLOYMENT_READINESS.md`.
   - Update README.md.

