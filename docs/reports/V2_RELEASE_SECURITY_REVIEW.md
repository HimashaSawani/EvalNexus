# AgentWindTunnel V2 — Release Security Review Report

**Date:** October 31, 2026  
**Auditor Roles:** Senior Security Engineer, AI Platform Architect  
**Scope:** Authentication, Authorization, SSRF Defenses, Secret Management, Concurrency, and Data Integrity  
**Working Directory:** `D:\AgentWindTunnel\AgentWindTunnel`  

---

## 1. Threat Model & Security Controls Matrix

| Threat / Vulnerability Vector | Security Control Implemented | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **Unauthenticated API Access** | Configurable API Authentication (`AWT_REQUIRE_AUTH=1`) validating Bearer tokens or `X-API-Key` headers against `AWT_API_KEY`. | Automated test `test_authentication_enforcement_when_configured` in `test_security_hardening.py`. | **VERIFIED** |
| **Cross-Origin API Abuse** | Explicit CORS origin restriction (`AWT_ALLOWED_ORIGINS`) with specific HTTP methods (`GET`, `POST`, `PUT`, `DELETE`, `OPTIONS`). | Audited in `backend/security.py` and `backend/main.py`. | **VERIFIED** |
| **Denial of Service / Flooding** | In-memory sliding-window rate limiters (`general_limiter`, `execution_limiter`) tracking client IPs across a 60-second window. | Automated test `test_rate_limiter_unit` in `test_security_hardening.py`. | **VERIFIED** |
| **SSRF via Custom Agents** | Strict scheme check (`http`/`https`), DNS pre-resolution, and IP range blocking: loopback (`127.0.0.0/8`), RFC-1918 private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), and cloud metadata (`169.254.169.254`). | Automated test `test_custom_agent_ssrf_protection` in `test_custom_http_agent.py`. | **VERIFIED** |
| **SSRF via HTTP Redirects** | Setting `follow_redirects=False` on `httpx.Client` to prevent attackers using 301/302 redirects to pivot onto internal network services. | Automated test `test_custom_agent_redirect_rejection` in `test_custom_http_agent.py`. | **VERIFIED** |
| **Secret Exposure in Responses** | Credential sanitization (`sanitize_secret`) returning only masked prefixes/suffixes (`awt-***...***` or `sk-***`). Passwords and tokens never returned in cleartext. | Automated test `test_secrets_never_leak_in_api_responses` in `test_security_hardening.py`. | **VERIFIED** |
| **Browser Credential Risks** | The single-page dashboard avoids persisting raw credentials in `localStorage`. API keys entered in the UI are held only in session memory. | Audited in `backend/static/index.html`. | **VERIFIED** |
| **Runaway Cloud Spend** | `PaidProviderGuard` and `AWT_MAX_CONCURRENT_PAID_JOBS` limit concurrent external paid API invocations. | Automated test `test_paid_provider_guard_limits` in `test_security_hardening.py`. | **VERIFIED** |
| **Multi-Process Worker Race** | Database-backed query and post-update invariant check in `QueueWorker.claim_next_job`. If concurrent workers claim paid jobs simultaneously, the ceiling is re-checked under the transaction and excess claims are rolled back immediately. | Automated test `test_concurrent_paid_job_claiming_enforces_ceiling_under_race` in `test_database_worker_reliability.py`. | **VERIFIED** |
| **Scenario Path Traversal** | Sanitization and validation in `custom_scenario_service.py` rejecting `../` path traversal and restricting writes to `scenarios/custom/`. | Automated test `test_scenario_path_traversal_prevention` in `test_custom_scenario_builder.py`. | **VERIFIED** |
| **Late Write After Timeout** | CancellationToken checks verify token validity before tool writes are committed to the database; late writes are rejected and rolled back. | Automated test `test_cancellation_token_blocks_late_writes` in `test_database_worker_reliability.py`. | **VERIFIED** |
| **Idempotency Key Collisions** | Unique constraints on `(scenario_run_id, idempotency_key)` in `refund_requests` table reject duplicate or conflicting payloads. | Automated test `test_idempotency_payload_mismatch_rejected` in `test_v1_operational_readiness.py`. | **VERIFIED** |

---

## 2. Security Status Classifications

- **VERIFIED:**
  - Complete authentication enforcement under `AWT_REQUIRE_AUTH=1`.
  - SSRF protection against private IP ranges and HTTP redirect chaining.
  - Secret redaction in all public and administrative API endpoints.
  - Multi-process worker synchronization preventing runaway paid API invocations.
  - Safe scenario file handling and path traversal blocking.
- **BLOCKED:**
  - *None.* (All local security controls and defensive assertions are fully operational).
- **FAILED:**
  - *None.*
- **NOT TESTED (Production Hardening Scope):**
  - Distributed multi-node rate limiting via Redis (`fastapi-limiter`). Current implementation uses in-process sliding windows, suitable for single-node and local deployments.
  - External Key Management Service (AWS KMS, GCP KMS, or HashiCorp Vault) for envelope encryption of external custom agent tokens at rest in PostgreSQL.

