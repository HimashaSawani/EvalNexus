# AgentWindTunnel V2 — AI Agent Reliability & Security Testing Platform

A deterministic evaluation, benchmarking, and fault-injection harness for tool-using AI agents in the e-commerce refund domain. FastAPI serves an interactive single-page dashboard across 11 sections. SQLAlchemy persists benchmark runs, a persistent queue, scenario fixtures, ordered execution traces, evaluator checks, custom agent adapters, custom scenarios, and simulated refund requests in SQLite (WAL mode with busy timeouts) or PostgreSQL. A concurrent queue worker daemon processes jobs using either the deterministic mock simulator, custom HTTP agent endpoints, or live tool-calling providers (Google Gemini / OpenAI).

V2 covers three simulated refund tools (`get_order`, `check_refund_eligibility`, and idempotent `request_refund`) with multi-layered defenses: ownership verification, fixed scenario clocks, duplicate operation key detection, cancellation token late-write blocking, fine-grained failure classifications, SSRF protections, and automated regression scorecards.

---

## 1. What's New in V2 Advanced Architecture

- **Custom Agent HTTP Adapter:** Modular `CustomHTTPAgentProvider` allowing developers to evaluate their own external AI agents over authenticated HTTP/HTTPS endpoints without executing arbitrary user code. Includes SSRF protection (blocking link-local & cloud metadata IPs) and masked token management.
- **Custom Scenario Builder & Import/Export:** Interactive and JSON-based scenario builder with deep Pydantic validation, strict path-traversal prevention, automatic versioning, and JSON import/export.
- **Automated Regression Testing & Scorecards:** Compares baseline vs candidate agent runs, identifies behavioral tool-call sequence drift, classifies regressions (`REGRESSION_DETECTED`, `IMPROVED`, `PARITY`), calculates latency percentiles ($p50$/$p90$), and computes token/cost deltas with explicit disclaimers and sample-size statistical warnings.
- **Root-Cause Failure Analysis:** Visual breakdown and filterable audit logs categorizing failures into Behavioral Policy Violations, Operational Limits Exceeded, and Provider Transport Outages.
- **Configurable API Authentication & Rate Limiting:** API key / Bearer token security (`AWT_API_KEY`, `AWT_REQUIRE_AUTH`), sliding-window rate limiting, and trusted CORS origin enforcement (`AWT_ALLOWED_ORIGINS`).
- **Multi-Process Concurrency & Spending Controls:** Database-backed `PaidProviderGuard` and atomic queue claiming preventing runaway cloud spend and race conditions across multiple worker processes.
- **Automated Verification:** **102 passing automated tests** (100% pass rate, 0 failures, 0 deprecation warnings) across unit, API, database isolation, security hardening, custom adapters, regression engines, Alembic migration verification, and Playwright browser E2E suites covering all 11 dashboard sections.

---

## 2. Architecture & Worker Topologies

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Service (V2)                            │
│  - REST API with Configurable Auth & Rate Limiting                     │
│  - Static Dashboard (served at / from backend/static/index.html)       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
                     ┌─────────────────────────────┐
                     │   Database (SQLite / PG)    │
                     │  - Alembic Version Tracking │
                     │  - Persistent Job Queue     │
                     │  - Scoped Fixtures & Traces │
                     └──────────────┬──────────────┘
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
┌─────────────────────────────┐           ┌─────────────────────────────┐
│  Mode A: Embedded Worker    │           │  Mode B: Standalone Worker  │
│  (AWT_EMBEDDED_WORKER=1)    │           │  (AWT_EMBEDDED_WORKER=0)    │
│  Background worker thread   │           │  Dedicated process via      │
│  inside API process         │           │  python -m backend.worker   │
└─────────────────────────────┘           └─────────────────────────────┘
```

- **Mode A (All-in-One Embedded Worker - Recommended for Local Testing):**
  - Set `$env:AWT_EMBEDDED_WORKER = '1'`.
  - The API process starts an internal background worker thread that polls the queue every 1.0s.
- **Mode B (Split Production Topology):**
  - Set `$env:AWT_EMBEDDED_WORKER = '0'`.
  - Service 1 runs the FastAPI web API; Service 2 runs `python -m backend.worker`.
  - Workers atomically claim jobs via conditional SQL updates with thread-safe locking and busy-wait retry.
  - Active jobs send heartbeats every 3.0s; orphaned jobs exceeding 30s are reaped as `FAILED`.
  - **Paid executions (`is_paid=1`) are never automatically replayed upon abandonment.**

---

## 3. Windows PowerShell Startup Commands

### Local Development Mode (Default Port 8001)

```powershell
Set-Location D:\AgentWindTunnel\AgentWindTunnel

# Setup environment
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
$env:AWT_REQUIRE_AUTH = '0'

# Run database migrations
python -m backend.database.migrate

# Start application server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Open **`http://127.0.0.1:8001/`** in your browser.
- Health probe: `http://127.0.0.1:8001/healthz`
- Database readiness: `http://127.0.0.1:8001/readyz`

### Authenticated Staging Mode

```powershell
Set-Location D:\AgentWindTunnel\AgentWindTunnel

$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
$env:AWT_REQUIRE_AUTH = '1'
$env:AWT_API_KEY = 'awt-prod-secret-key-9988'
$env:AWT_ALLOWED_ORIGINS = 'http://127.0.0.1:8001,http://localhost:8001'

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Clients must provide either `Authorization: Bearer awt-prod-secret-key-9988` or `X-API-Key: awt-prod-secret-key-9988`.

---

## 4. Providers, Credentials & Execution Limits

1. **Mock Simulator (`mock`):** Deterministic infrastructure testing engine; requires no API keys and makes zero network requests. Estimated cost: **$0.00**.
2. **Real Providers (`gemini`, `openai`):** Reads server-side environment variables `GEMINI_API_KEY` or `OPENAI_API_KEY`. If keys are missing or invalid, provider setup fails cleanly with `PROVIDER_ERROR` (never falls back silently to mock).
3. **Execution Guardrails:**
   - Turn budget: Max 6 turns per scenario.
   - Tool call budget: Max 10 tool invocations per scenario.
   - Token budget ceiling: 15,000 tokens default (capped at `AWT_MAX_TOKENS_PER_RUN=30000`).
   - Timeouts: 30-second scenario wall-clock deadline; 5.0-second individual tool timeout.
   - Concurrency: `AWT_MAX_CONCURRENT_PAID_JOBS` restricts active live provider executions.
   - Late-write protection: `CancellationToken` actively interrupts and rolls back database mutations if tool calls exceed deadline.

---

## 5. Evaluator Assertions & Failure Classification

The `DeterministicEvaluator` checks five core assertions per scenario:
- **`OWNERSHIP`**: Enforces customer/order scope; verifies agent never queried or modified orders belonging to other customers.
- **`ELIGIBILITY`**: Evaluates policy against a fixed scenario clock (e.g. 14-day return window from delivery timestamp).
- **`DUPLICATE`**: Validates idempotency key stability and ensures at most one refund record exists.
- **`STATE`**: Verifies exact database amounts (minor units / cents) and ledger status (`REFUND_REQUESTED`). Marks check as **`INDETERMINATE`** if background write tasks timed out and state cannot be established with certainty.
- **`COMPLETION`**: Verifies clean termination within turn, tool-call, and token budgets.

Scenarios that do not pass are classified into structured failure categories:
- `BEHAVIORAL_POLICY_VIOLATION`: Agent attempted ineligible refund, crossed customer boundaries, or churned idempotency keys.
- `OPERATIONAL_LIMIT_EXCEEDED`: Exceeded max turns, tool timeouts, or token limits.
- `PROVIDER_ERROR`: Network, authentication, quota exhaustion, or 429 response from upstream LLM.

---

## 6. Automated Verification Suites (102 Tests)

### Run Full Pytest Test Suite
```powershell
Set-Location D:\AgentWindTunnel\AgentWindTunnel
python -m pytest tests/ -v
```
All **102 tests pass** cleanly with **0 failures and 0 warnings**:
- Unit and domain logic (`test_agent_runner.py`, `test_refund_service.py`)
- API endpoints & 404 routing (`test_api.py`)
- Custom Agent HTTP Adapter lifecycle & SSRF/redirect protection (`test_custom_http_agent.py`)
- Custom Scenario Builder validation, path traversal prevention, & import/export (`test_custom_scenario_builder.py`)
- Automated Regression Comparator, latency percentiles, & scorecards (`test_regression_comparison.py`)
- Security hardening, credential redaction, rate limiting, and multi-process paid guards (`test_security_hardening.py`)
- Multi-process worker concurrency & atomic claiming (`test_database_worker_reliability.py`)
- Playwright browser E2E test covering all 11 dashboard sections (`test_playwright_e2e_sections.py`)
- Evaluator negative leak detection (`test_evaluator_negative.py`)
- Fault injection and late-write blocking (`test_fault_behaviors.py`)
- Playwright browser E2E verification across all 11 dashboard sections (`test_playwright_e2e_sections.py`)

---

## 7. Visual Showcase (Dashboard Screenshots)

### System Overview
Real-time reliability metrics, provider distribution (Mock Simulator vs. Live Real), behavioral pass rate, and recent execution logs.
![System Overview](docs/reports/screenshots/01_overview_desktop.png)

### Test Studio & Runner
Execute and inspect agent behavior under simulated real-world conditions, execution budgets, and fault injections with real-time status polling.
![Test Studio](docs/reports/screenshots/02_test_studio_initial.png)

### Scenarios Catalog
Comprehensive 30-scenario benchmark library covering normal refund paths, 14-day boundary edge cases, and all 5 fault modes with instant "Test in Studio" routing.
![Scenarios Catalog](docs/reports/screenshots/03_scenarios_catalog.png)

### Agent Versions & System Prompts
Direct side-by-side comparison of baseline (`agent_v1_baseline`) vs. robust fault-compliant (`agent_v2_improved`) system prompts and policy directives.
![Agent Versions](docs/reports/screenshots/05_agent_versions.png)

### Run History & Saved Evidence
Immutable execution records persisted in SQLite database (WAL mode), filterable by engine mode and status, with deep inspection and JSON/Markdown export.
![Run History](docs/reports/screenshots/06_run_history.png)

### Run Comparisons & Compatibility Analysis
Evaluates behavioral deltas, execution duration, and check results with automated compatibility verification and statistical sample size confidence indicators.
![Run Comparisons](docs/reports/screenshots/08_comparisons_compatible.png)

### Settings & Redacted Configuration
Displays runtime execution limits (30s timeout, 6 turns, 15,000 token budget), worker heartbeats, and credential masking (zero secret leakage).
![Settings & Safety](docs/reports/screenshots/10_settings.png)
