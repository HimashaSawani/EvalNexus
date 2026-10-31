# Changelog

All notable changes to the AgentWindTunnel project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-10-31

### Added
- **Custom Agent HTTP Adapter:** Modular `CustomHTTPAgentProvider` allowing developers to benchmark external AI agents over authenticated HTTP/HTTPS endpoints without executing untrusted code locally.
- **Custom Scenario Builder & Import/Export:** Interactive visual builder and JSON file import/export service with strict Pydantic validation and path traversal defenses.
- **Automated Regression Testing & Scorecards:** Comparator engine detecting behavioral tool-call sequence drift, latency drift ($p50$/$p90$), and token/cost deltas between baseline and candidate agent runs.
- **Root-Cause Failure Analysis:** Visual breakdown and filterable audit logs categorizing failures into `BEHAVIORAL_POLICY_VIOLATION`, `OPERATIONAL_LIMIT_EXCEEDED`, and `PROVIDER_ERROR`.
- **Alembic Database Migrations:** Production-ready migration system managing all 12 tables (`agent_versions`, `scenario_versions`, `runs`, `scenario_runs`, `trace_events`, `check_results`, `customers`, `orders`, `refund_requests`, `queue_jobs`, `custom_agents`, `custom_scenarios`) with indexes and foreign keys.
- **Security Hardening:**
  - Configurable API authentication enforcing Bearer tokens or `X-API-Key` headers (`AWT_REQUIRE_AUTH`, `AWT_API_KEY`).
  - Strict CORS origin whitelisting (`AWT_ALLOWED_ORIGINS`).
  - Sliding-window in-memory rate limiting on `/api/*` endpoints.
  - Multi-process paid execution concurrency guard enforcing `AWT_MAX_CONCURRENT_PAID_JOBS` via atomic database-backed transactions.
  - SSRF protection rejecting non-HTTP schemes, loopback, private RFC-1918, link-local, and cloud metadata addresses (`169.254.169.254`), with strict HTTP 301/302 redirect rejection (`follow_redirects=False`).
  - Secret masking redacting tokens in `/api/settings` and `/api/custom-agents`.
- **Docker Compose & PostgreSQL Profiles:** Multi-container configuration supporting non-root container execution (`appuser`), persistent volumes (`awt_data`, `postgres_data`), and optional PostgreSQL 16 Alpine container under profile `postgres`.
- **Comprehensive Verification Suite:** 103 automated tests passing with 100% pass rate, including unit, integration, API, security, migration, and Playwright browser E2E suites across all 11 dashboard sections.

### Changed
- Replaced stub Alembic migration with fully reversible revision `7fd6911d1d5f_initial_schema_v2.py`.
- Hardened `QueueWorker.claim_next_job` with atomic post-update invariant verification and transaction rollback to guarantee zero race condition over-claiming across independent worker processes.
- Enhanced Playwright test suite to execute real user interactions (saving custom agents, saving custom scenarios, changing failure analysis filters) rather than static DOM checks.
- Refactored model pricing estimates to prominently include explicit billing disclaimers.

### Security
- Resolved critical SSRF redirect vulnerability by setting `follow_redirects=False` in custom agent HTTP clients.
- Sanitized credential leakage in API endpoints and diagnostic settings payloads.
- Added database-level idempotency and cancellation token checks preventing late-arriving tool calls from committing after timeouts.

---

## [1.0.0] - 2026-10-24

### Added
- Initial release of AgentWindTunnel.
- Deterministic mock simulation and live Gemini/OpenAI tool-calling providers.
- Three simulated refund domain tools: `get_order`, `check_refund_eligibility`, and idempotent `request_refund`.
- 30 benchmark evaluation scenarios.
- 5 deterministic behavioral evaluator assertions (`OWNERSHIP`, `ELIGIBILITY`, `DUPLICATE`, `STATE`, `COMPLETION`).
- FastAPI web dashboard across 7 initial sections.
- SQLite WAL mode persistent queue and worker.

