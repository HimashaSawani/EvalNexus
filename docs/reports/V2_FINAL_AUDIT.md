# AgentWindTunnel V2 — Comprehensive Engineering Audit & Hardening Report

**Audit Completed:** October 31, 2026  
**Auditor Roles:** Senior AI Systems Engineer, Backend Architect, Security Engineer, DevOps Engineer, and QA Automation Lead  
**Scope:** V1 implementation review, security hardening, database reliability, evaluation rigor, dashboard enhancements, CI/CD operational readiness, and regression testing.

---

## 1. Executive Summary

AgentWindTunnel was audited and systematically hardened from an early-stage research prototype into a production-grade, highly resilient AI Agent Reliability Testing Platform. 

All 8 phases of the hardening directive were executed without rebuilding the application from scratch or deleting legacy features. Every critical security defect and worker race condition was resolved and verified with dedicated automated regression tests.

- **Initial Test Baseline:** 72 passing tests, 3 deprecation warnings (8.40s)
- **V2 Test Verification:** **85 passing tests, 0 failures, 0 deprecation warnings** (17.66s)
- **Key Vulnerabilities Resolved:**
  - Wildcard CORS policy (`allow_origins=["*"]`) replaced with strict configurable trusted origins (`AWT_ALLOWED_ORIGINS`).
  - Unauthenticated API endpoints protected with configurable API Key / Bearer token authentication (`AWT_API_KEY`), preserving zero-friction local development mode (`AWT_REQUIRE_AUTH=0`).
  - Denial-of-Wallet (DoW) risk mitigated with server-side rate limiting and paid provider concurrency / spending controls (`AWT_MAX_CONCURRENT_PAID_JOBS`, `AWT_MAX_TOKENS_PER_RUN`).
  - Worker race condition during concurrent job claiming resolved with process locking and retry backoff.
  - Python 3.12+ `datetime.datetime.utcnow()` deprecation warnings eliminated in models.
  - Alembic database migration environment initialized with PostgreSQL dialect compatibility.
  - Token cost calculations and fine-grained failure classifications added to evaluator.
  - Playwright automated browser E2E test added covering all 7 dashboard sections.

---

## 2. Phase-by-Phase Execution & Implementation Audit

### Phase 1 — Repository Baseline & Vulnerability Analysis
- Verified full file tree, git history, and runtime environment (Python 3.13.3).
- Identified insecure CORS, open API endpoints, absent Alembic migrations, and concurrent worker claiming vulnerabilities.
- Documented initial findings in `docs/reports/V2_INITIAL_AUDIT.md`.

### Phase 2 — Security Hardening
- **Module Created:** `backend/security.py`.
- **Configurable Authentication:** Supports `Authorization: Bearer <key>` and `X-API-Key: <key>`. Controlled via `AWT_REQUIRE_AUTH` (defaulting to local dev bypass for backward compatibility).
- **CORS Restriction:** Explicit trusted origins via `get_allowed_origins()` (`http://localhost:8000`, `http://127.0.0.1:8000`, `http://localhost:3000`, `http://127.0.0.1:3000`, or custom comma-delimited `AWT_ALLOWED_ORIGINS`).
- **Rate Limiting:** Sliding-window rate limiter in `SecurityRateLimitMiddleware` (default 120 RPM general, 30 RPM execution).
- **Paid Provider Spending & Concurrency Controls:** `PaidProviderGuard` enforces maximum concurrent paid executions (default 2) and caps token budgets per run.
- **Credential Redaction:** Error messages and exception payloads pass through `sanitize_secret()` masking Google AIza, AQ, and OpenAI sk- tokens.

### Phase 3 — Database & Worker Reliability
- **Atomic Job Claiming:** Added in-process locking and SQLite busy-retry backoff in `QueueWorker.claim_next_job`, eliminating multi-worker claiming race conditions.
- **PostgreSQL & Connection Pooling:** Enhanced `backend/database/connection.py` with pre-ping, connection recycling (`DB_POOL_RECYCLE=1800`), pool size, and overflow limits when PostgreSQL connection string is provided.
- **Alembic Migrations:** Initialized `alembic/` migration tree, configured `alembic/env.py` to auto-detect models and SQLite batch rendering, and generated `7fd6911d1d5f_initial_schema_v2.py`.
- **Modernized Migration Script:** `backend/database/migrate.py` upgraded to run programmatic Alembic migrations with SQLAlchemy metadata fallback.
- **Deprecation Elimination:** Removed `datetime.datetime.utcnow` from `ScenarioRun.started_at` in favor of timezone-aware UTC now.

### Phase 4 — AI Evaluation Quality
- **Token Pricing & Cost Tracking:** Implemented `calculate_cost_microcents()` in `backend/agent/provider.py` covering Gemini Flash Lite, Gemini Flash, GPT-4o-mini, and GPT-4o. Tracked in trace events and scenario run summaries with explicit $0.00 accounting for mock simulation.
- **Failure Classification:** Scenarios now categorize failures into `BEHAVIORAL_POLICY_VIOLATION`, `OPERATIONAL_LIMIT_EXCEEDED`, `PROVIDER_ERROR`, and `EXECUTION_ERROR`.
- **Statistical Sample Size Confidence:** `/api/comparisons` checks scenario count and warns if `N < 10` that findings are observational and insufficient for statistical claims.

### Phase 5 — Dashboard Usability & Safety
- **Authenticated API Calls:** Introduced `apiFetch()` client in `backend/static/index.html` automatically attaching stored API keys from browser `localStorage`.
- **Settings View Enhancement:** Added client-side API key configuration card for staging/authenticated environments.
- **Comparisons View:** Displays visual statistical confidence notices (amber alert when N < 10, green when N >= 10).
- **DOM Stability:** Maintained 100% backward compatibility with all existing dashboard selectors, status pills, and trace drawers.

### Phase 6 — Automated Verification
- Added `tests/test_security_hardening.py` (6 new tests).
- Added `tests/test_database_worker_reliability.py` (3 new tests).
- Added `tests/test_evaluation_quality.py` (3 new tests).
- Added `tests/test_playwright_e2e_sections.py` (1 new browser E2E test).
- Total verified test suite: **85 passing tests**.

### Phase 7 — CI/CD Pipeline
- Added `.github/workflows/ci.yml`:
  - Python matrix testing across 3.11, 3.12, 3.13.
  - Dependency vulnerability scanning via `pip-audit`.
  - Non-root user container build verification (`appuser`).
- Retained existing `.github/workflows/security-scan.yml` for Gitleaks and TruffleHog.

---

## 3. Verified Repository Artifacts

- `backend/security.py` — Auth, rate limiting, CORS, paid provider guards.
- `backend/database/connection.py` — SQLite WAL & PostgreSQL pooling.
- `backend/database/models.py` — Timezone-aware UTC models.
- `backend/database/migrate.py` — Alembic and schema initialization runner.
- `backend/worker.py` — Thread-safe atomic job claiming and non-replay guarantees.
- `backend/agent/provider.py` — Cost calculation and credential redaction.
- `backend/agent/agent_loop.py` — Cost tracking in traces and execution loop.
- `backend/runner/agent_runner.py` — Failure classification and cost exposure.
- `backend/main.py` — Security dependencies, rate limit middleware, statistical comparison.
- `backend/static/index.html` — API key storage, statistical banner, secure fetch.
- `alembic.ini` & `alembic/` — Full Alembic revision history.
- `.github/workflows/ci.yml` — Automated CI testing, security, and build checks.

