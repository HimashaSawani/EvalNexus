# Execution Limits, Timeouts, and Operational Guarantees

This document specifies the operational guardrails, timeouts, accounting mechanisms, and technical boundaries enforced within the **EvalNexus** benchmarking platform.

---

## 1. Operational Limits & Timeouts Overview

EvalNexus implements a multi-layered boundary defense to prevent runaway agent loops, denial-of-service, excessive billing, and thread deadlocks.

| Limit Mechanism | Scope | Default Value | Enforcement Layer | Interruption Behavior |
|---|---|:---:|---|---|
| **Tool-Call Timeout** | Per individual tool call | `10.0s` | `AgentLoop._execute_tool_with_timeout` via `ThreadPoolExecutor` | Actively interrupts waiting; caller loop resumes immediately; agent receives generic HTTP 504 Gateway Timeout |
| **Provider Request Timeout** | Per LLM inference call | `15.0s` | `RealOpenAIProvider` HTTP socket client (`timeout=provider_timeout_sec`) | Socket timeout triggers `TimeoutError` / `APITimeoutError`; halts inference turn |
| **Scenario Wall-Clock Limit** | Total end-to-end scenario run | `30.0s` | `AgentLoop.execute_turn_loop` start-of-turn clock check | Raises `AgentExecutionLimitError(SCENARIO_TIMEOUT)`; aborts scenario execution |
| **Model Turn Limit** | Total LLM turns per scenario | `6` turns | `AgentLoop` `while turns < max_turns` | Halts agent loop; produces partial trace; passes state to deterministic evaluator |
| **Tool Call Volume Limit** | Total tool invocations | `10` calls | `AgentLoop.max_tool_calls` counter check | Raises `AgentExecutionLimitError(MAX_TOOL_CALLS_EXCEEDED)` |
| **Token Budget Accounting** | Cumulative token consumption | `15,000` tokens | In-flight tracking via `llm_res.total_tokens` | Raises `AgentExecutionLimitError(TOKEN_BUDGET_EXCEEDED)` before next turn |
| **Estimated Cost Accounting** | Financial expenditure | Model rate table | `TraceLogger` micro-cents calculation | Recorded in audit trace per turn |

---

## 2. Active Interruption Mechanics

### Tool-Call Timeout (`tool_timeout_sec`)
Tool execution is isolated in a worker thread via `concurrent.futures.ThreadPoolExecutor`. 
```python
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
try:
    future = executor.submit(self._execute_tool_internal, customer_id, tool_name, arguments)
    return future.result(timeout=self.tool_timeout_sec)
except concurrent.futures.TimeoutError:
    executor.shutdown(wait=False, cancel_futures=True)
    # Log TOOL_TIMEOUT and return HTTP 504 to agent
```
- **Active Interruption**: `future.result(timeout=...)` raises `TimeoutError` immediately when the deadline expires.
- **Non-blocking Shutdown**: `executor.shutdown(wait=False, cancel_futures=True)` guarantees the agent loop does not block waiting for the hanging worker thread to exit.
- **Agent Visibility**: The agent receives a realistic generic error payload (`{"error": "Gateway Timeout: Tool '...' timed out after 10.0s."}`). Internal fault identifiers and write commitment status are never exposed in the agent's observation window.

### Provider Request Timeout (`provider_timeout_sec`)
For real LLM providers (`gpt-4o-mini`, `gemini-1.5-flash`), HTTP read and connect timeouts are configured directly on the underlying HTTP client (`openai.OpenAI(timeout=15.0)`). If the provider network hangs, the socket read is aborted after 15 seconds, raising an explicit `TimeoutError`.

---

## 3. Guarantees That CANNOT Be Enforced (Technical Boundaries)

In accordance with system-level constraints of modern operating systems, Python runtimes, and distributed payment architectures, the following guarantees **cannot** be enforced:

### 1. Preemptive Python Thread Cancellation vs. State Settling
- **Limitation**: CPython does not provide a mechanism to asynchronously kill or abort an arbitrary running thread (`Thread.abort()` does not exist in standard Python).
- **Hazard**: If a tool times out before committing to the database, the unkilled worker thread could potentially complete its write after the evaluator has already evaluated the scenario.
- **Architectural Solution Implemented in EvalNexus**:
  1. **`CancellationToken`**: An explicit cancellation token is bound to `RefundService`. The moment a tool call exceeds `tool_timeout_sec`, `token.cancel()` is immediately flagged.
  2. **Late-Write Blocking**: `RefundService.request_refund` checks `self.cancel_token.is_cancelled` before and after database commit. If cancellation is flagged, the write is immediately rolled back (`self.db.rollback()`), guaranteeing no orphan records pollute the database.
  3. **`settle_in_flight_tasks(timeout_sec=0.5)` Barrier**: Before deterministic evaluation runs, `agent_runner` drains and settles any active worker thread, ensuring the database transaction is finalized and SQLite locks are released.

### 2. Remote Side-Effect Rollback on Timeout (`TIMEOUT_AFTER_WRITE`)
- **Limitation**: Client-side network timeouts occur after bytes are transmitted across the network. If an upstream payment gateway or SQL database commits the write but the TCP connection drops before the HTTP response header returns, the client cannot un-commit the upstream state.
- **Architectural Safeguard**: Client-side rollback cannot be guaranteed. Instead, **idempotency keys** (`operation_key`) and database unique constraints (`uq_order_scenario_refund`, `uq_opkey_scenario_refund`) guarantee that retries with the same key will never result in duplicate debit or double refund.

### 3. Provider-Side Token Billing Cancellation Mid-Generation
- **Limitation**: When making synchronous HTTP completion requests to external LLM APIs without Server-Sent Events (SSE) cancellation streams, dropping the client TCP connection on a client-side timeout does not guarantee the remote provider cancels GPU inference immediately.
- **Consequence**: Incurred tokens may still be billed by the provider provider-side even if the client times out and discards the response.

### 4. Exact Real-Time Cost Precision
- **Limitation**: Providers report exact token counts (`prompt_tokens`, `completion_tokens`, `total_tokens`), but financial cost is derived from static rate cards (e.g., $0.15 / 1M input tokens).
- **Consequence**: Rate cards do not account for custom enterprise discounts, regional pricing differences, tiered volume caching discounts (e.g. Gemini context cache hits or OpenAI prompt cache discounts), or currency conversions. Cost values are strictly documented as **estimates**.
