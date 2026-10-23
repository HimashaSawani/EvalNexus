# AgentWindTunnel Implementation Audit & Verification Report

**Audit Date:** 2026-10-23  
**Auditor:** DeepMind Antigravity Engineering Pair  
**Repository:** `d:/AgentWindTunnel`  
**Status:** Audit Completed; Corrective Actions Implemented; 28/28 Automated Tests Passing.

---

## 1. What is Actually Implemented & Architecture Stack

| Component | Stack Proposed in Roadmap | Actually Implemented | Status & Reality |
|---|---|---|---|
| **Database Engine** | PostgreSQL via Docker Compose | SQLite 3 (`agent_wind_tunnel.db`) with composite primary keys `(id, scenario_run_id)` for complete test run data isolation. Configured for PostgreSQL connection strings via `DATABASE_URL`. | **Functional**: SQLite allows zero-dependency local runs without Docker daemon. PostgreSQL connection supported via SQLAlchemy. |
| **Migrations** | Alembic | SQLAlchemy Core + programmatic migration script (`backend/database/migrate.py`). | **Documented Deviation**: Working schema managed directly; Alembic installed but migration history files not yet initialized. |
| **Backend & Runner** | FastAPI + Python | FastAPI (`backend/main.py`), Domain Service (`backend/domain/refund_service.py`), Evaluator (`backend/runner/evaluator.py`), Agent Loop (`backend/agent/agent_loop.py`), Runner (`backend/runner/agent_runner.py`). | **Implemented & Verified**. |
| **Scenario Suite** | 30 Scenarios (6 per category, 20 dev / 10 held-out) | Exactly 30 declarative scenarios across 5 categories in `scenarios/dev/` and `scenarios/held_out/`. | **Complete & Verified** via `test_suite_coverage.py`. |
| **Fault Injector** | 5 Synthetic Faults | `TIMEOUT_BEFORE_WRITE`, `TIMEOUT_AFTER_WRITE`, `TEMPORARY_UNAVAILABLE`, `STALE_READ`, `MALFORMED_RESPONSE`. | **Complete & Verified** without simulator information leakage. |
| **Deterministic Evaluator** | 5 Core Assertions | `OWNERSHIP`, `ELIGIBILITY`, `DUPLICATE`, `STATE`, `COMPLETION`. Upgraded to inspect trace history and separate attempted vs blocked vs leaked actions. | **Complete & Verified** with negative test coverage. |
| **Provider Support** | Tool-calling model | `MockToolCallingProvider` (deterministic local infrastructure engine) and `RealOpenAIProvider` (OpenAI / Google Gemini API). | **Real Provider Pending Credentials**: No API keys present in local environment; live runs fail cleanly without silent mock fallbacks. |
| **Dashboard** | Next.js + TypeScript | High-performance single-page dashboard served directly via FastAPI (`backend/static/index.html`) with glassmorphic UI, real-time assertions, timeline inspector, and provider selectors. | **Deviation**: Avoids Node build step overhead; runs natively out of the box with `uvicorn`. |

---

## 2. Mock Execution vs. Real-Model Execution

- **Mock Execution Purpose**: The `MockToolCallingProvider` is strictly for **deterministic infrastructure testing** (testing database locks, trace sequencing, evaluator assertions, and fault delivery).
- **Correction Applied**: Removed mock cheating where the simulator previously inspected `self.agent_version` and returned hardcoded text for Version B. The mock simulator now operates purely on visible conversation history and tool outputs.
- **Run Labeling**: Every run in the database and CLI is explicitly tagged with `provider_type` (`mock` vs `openai` vs `gemini`), `model_name`, `is_mock` (Boolean), and `execution_config`.
- **Strict Credential Validation**: If a user selects `--provider openai` or `--provider gemini` without setting `OPENAI_API_KEY` or `GEMINI_API_KEY`, the system raises a clear `RuntimeError` refusing silent mock fallback.
- **Credential Protection**: API keys are read from environment variables only and are never printed, logged, or serialized to the database or UI.

---

## 3. Simulator Information Leakage Corrections

- **The Issue Identified**: Previously, `FaultInjector` raised error messages that literally stated `"Write committed to DB, but response lost"` and displayed synthetic fault names like `[TIMEOUT_AFTER_WRITE]` in the agent's tool observation history.
- **The Correction**:
  - The agent now receives only realistic, generic upstream errors:  
    `"Gateway Timeout: Connection to upstream payment processor lost while awaiting confirmation."` (HTTP 504)
  - Ground-truth facts (`write_committed = True`, `fault_type = "TIMEOUT_AFTER_WRITE"`) are sequestered exclusively in admin audit traces (`TraceEvent.error_message`), invisible to the agent.
  - Verified via `test_agent_runner.py::test_fault_timeout_after_write`.

---

## 4. Refund Recovery & Idempotency Verification

- **Timeout-After-Write Demonstration**: Tests prove that when `TIMEOUT_AFTER_WRITE` triggers, the `RefundRequest` record is committed to the database with status `REFUND_REQUESTED` prior to returning the 504 timeout to the caller.
- **Conflicting Operation Key Rejection**: Implemented strict payload matching on `operation_key`. If an operation key is reused with a different `order_id` or `amount_cents`, the backend raises `RefundDomainError("IDEMPOTENCY_PAYLOAD_MISMATCH", status_code=409)`.
- **Safe Replay**: If the operation key matches the original payload, it safely replays the previous record (`idempotent_replay: True`) without creating a duplicate record or throwing an error.

---

## 5. Evaluator Audit & Negative Testing

The `DeterministicEvaluator` was upgraded from superficial database record counting to comprehensive audit-trace inspection:

1. **`OWNERSHIP`**: Inspects tool call history for any query targeting another customer's order. Distinguishes:
   - `UNAUTHORIZED_ACCESS_ATTEMPTED`: Agent attempted an illegal query (Policy Failure).
   - `BLOCKED_BY_BACKEND`: Backend returned 403 Forbidden.
   - `UNAUTHORIZED_WRITE_SUCCEEDED`: Critical security breach.
2. **`ELIGIBILITY`**: Checks whether the agent attempted to call `request_refund` on an ineligible order, even if the backend ultimately blocked the transaction.
3. **`DUPLICATE`**: Validates database record count $\le 1$ and checks trace events for operation key churn.
4. **`STATE`**: Verifies exact matching of order amount cents and status `REFUND_REQUESTED`.
5. **`COMPLETION`**: Evaluates whether execution halted within budget limits and categorizes error types (Budget Limit vs Provider Crash vs Infrastructure Error).

**Negative Test Suite (`tests/test_evaluator_negative.py`)**:
- `test_evaluator_detects_unauthorized_read_attempt`: PASSED
- `test_evaluator_detects_unauthorized_write_leak`: PASSED
- `test_evaluator_detects_attempted_ineligible_refund`: PASSED
- `test_evaluator_detects_duplicate_operation_key_churn`: PASSED
- `test_evaluator_detects_state_amount_mismatch`: PASSED

---

## 6. Limits & Operational Budget Enforcement

In `backend/agent/agent_loop.py`:
- `max_turns` (default 6): Checked at the start of each turn loop.
- `max_tool_calls` (default 10): Checked before each tool invocation.
- `max_tokens_budget` (default 15,000 tokens): Checked before and after model calls.
- `scenario_timeout_sec` (default 30.0s): Checked on each loop iteration.
- Tool schemas and argument types are strictly validated before tool dispatch.

---

## 7. 30 Reviewed Benchmark Scenarios Suite

Partitioned into **20 Development Scenarios** (`scenarios/dev/`) and **10 Held-out Scenarios** (`scenarios/held_out/`):

1. **Normal Requests (6)**: Delivered 5d, 1d, 10d, Cancelled pre-ship, High value 7d (held-out), Cancelled immediate (held-out).
2. **Eligibility Boundaries (6)**: Exact 14.0d boundary, 15d expired, 30d expired, Status pending, Status unknown (held-out), Already refunded (held-out).
3. **Ownership & Permissions (6)**: Query other customer, Refund other customer, Social engineering gift claim, Prompt injection admin override, Sequential ID enumeration (held-out), Cross-tenant isolation (held-out).
4. **Tool Failures & Faults (6)**: Timeout before write, Timeout after write, 503 transient error, Stale read, Malformed response packet (held-out), Idempotent recovery retry (held-out).
5. **Duplicate & Misleading (6)**: Repeated prompt message, Refund already pending, Partial refund demand, Future delivery timestamp, Conflicting operation key reuse (held-out), Hallucinated order ID (held-out).

---

## 8. Summary of Automated Tests Run

```bash
pytest -v
```
**Results: 28 Passed, 0 Failed, 0 Warnings in 2.01s**

---

## 9. Remaining Limitations & Pending Items

1. **Live Model Verification Pending Credentials**: Because `OPENAI_API_KEY` and `GEMINI_API_KEY` are not set in the local environment, all live model tests are staged and verified via unit tests, but live cloud inference runs remain pending user credentials.
2. **Background Task Queue**: The background runner currently executes asynchronously in-process. High-throughput distributed benchmark runs (e.g., 500+ parallel runs) would benefit from Redis/Celery queueing as planned in the later roadmap phases.
