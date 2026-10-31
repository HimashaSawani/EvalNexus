# AgentWindTunnel V2 — Comprehensive Security Review Report

**Review Date:** October 31, 2026  
**Auditor:** Application Security Lead & Systems Engineer  
**Classification:** Confidential / Security Architecture Assessment

---

## 1. Security Architecture Overview

AgentWindTunnel V2 incorporates defense-in-depth security mechanisms designed to protect both the operator's infrastructure and external API spending budgets.

```
                           [ Incoming HTTP Request ]
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Restricted Trusted CORS   │
                        │ (AWT_ALLOWED_ORIGINS)     │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Rate Limiter (IP/Window)  │
                        │ 429 Too Many Requests     │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Auth Dependency Check     │
                        │ Bearer / X-API-Key        │
                        │ (Bypassed if local dev)   │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Paid Provider Guard       │
                        │ Concurrency & Token Caps  │
                        └─────────────┬─────────────┘
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ Core Business Handlers    │
                        │ + Secret Redaction        │
                        └───────────────────────────┘
```

---

## 2. Implemented Security Controls

### 2.1 Configurable Authentication & Local Dev Mode
- **Configuration Flags:**
  - `AWT_REQUIRE_AUTH`: Set to `"1"` (or `"true"`) to enforce API key checks on all non-health endpoints. Default is `"0"` for zero-friction local developer workflows.
  - `AWT_API_KEY`: Secret string required in request headers when auth is enforced.
- **Accepted Headers:**
  - `Authorization: Bearer <AWT_API_KEY>`
  - `X-API-Key: <AWT_API_KEY>`
- **Exempt Public Endpoints:**
  - `GET /health` & `GET /healthz` (liveness probe)
  - `GET /readyz` (database readiness probe)
  - `GET /` (static SPA dashboard)

### 2.2 Strict CORS Origin Restriction
- Wildcard `allow_origins=["*"]` with `allow_credentials=True` was completely eliminated.
- Explicit origins are resolved via `get_allowed_origins()`:
  - Default: `["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:3000", "http://127.0.0.1:3000"]`
  - Custom: Configurable via comma-separated `AWT_ALLOWED_ORIGINS`.

### 2.3 Denial-of-Wallet (DoW) & Concurrency Controls
- **Rate Limiting:** `SecurityRateLimitMiddleware` limits requests across all `/api/` paths using a sliding-window algorithm.
- **Paid Concurrency Semaphore:** `PaidProviderGuard` tracks active in-flight paid executions (Google Gemini and OpenAI) and rejects excess traffic with HTTP 429 when `AWT_MAX_CONCURRENT_PAID_JOBS` (default 2) is reached.
- **Token Budget Ceilings:** Automatically caps requested `max_tokens_budget` to `AWT_MAX_TOKENS_PER_RUN` (default 30,000 tokens).

### 2.4 Credential Redaction & Log Safety
- `sanitize_secret()` sanitizes all raw log messages, trace events, and exception strings.
- Regex rules specifically mask:
  - Google Gemini API Keys (`AIzaSy...`, `AQ....`)
  - OpenAI API Keys (`sk-...`)
  - Query parameters formatted as `?key=...` or `&key=...`

### 2.5 Secret Scanning in CI
- Existing Gitleaks and TruffleHog secret scanning workflows (`.github/workflows/security-scan.yml`) were preserved and validated.
- `.gitignore` rigorously excludes `.env`, `*.db`, `*.db-wal`, `*.db-shm`, and test artifacts.

---

## 3. Vulnerability Status & Resolution Matrix

| Vulnerability ID | Description | Initial Severity | Status in V2 | Resolution Evidence |
| :--- | :--- | :---: | :---: | :--- |
| **SEC-01** | Permissive CORS with credentials | CRITICAL | **RESOLVED** | Restricted to trusted origins in `main.py` |
| **SEC-02** | Unauthenticated execution & cancellation | CRITICAL | **RESOLVED** | `verify_api_key` dependency in `security.py` |
| **SEC-03** | Paid provider flooding & DoW risk | HIGH | **RESOLVED** | `PaidProviderGuard` & rate limiter active |
| **SEC-04** | Missing CI automated test/security scan | MEDIUM | **RESOLVED** | `.github/workflows/ci.yml` added |
| **SEC-05** | Credential leakage in error responses | HIGH | **RESOLVED** | `sanitize_secret` regex masking in runner & provider |

---

## 4. Remaining Security Recommendations for Production Deployment

1. **mTLS or Reverse Proxy TLS:** When deploying outside of localhost, terminate TLS via an ingress controller or reverse proxy (Nginx, Caddy, Cloudflare).
2. **Secret Manager Integration:** For staging/production, inject `AWT_API_KEY`, `GEMINI_API_KEY`, and `OPENAI_API_KEY` using AWS Secrets Manager, GCP Secret Manager, or HashiCorp Vault rather than static `.env` files.

