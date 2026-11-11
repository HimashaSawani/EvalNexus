# EvalNexus Gemini Agent Pipeline Verification

**Verification date:** 2026-11-10  
**Final verification state:** **PARTIALLY_VERIFIED**

## Scope

This report verifies the local EvalNexus agent-evaluation pipeline and records a bounded plan for the first real Gemini-powered agent execution. No external Gemini request was made for this pipeline verification.

The separate ETGNN-Fraud-Detection project was not used.

## Verified Local Execution Flow

1. A provider is selected through `resolve_provider()` in `backend/agent/provider.py`.
2. `RealOpenAIProvider` sends OpenAI-compatible chat-completion requests to Gemini's OpenAI-compatible endpoint.
3. `AgentWindTunnelRunner` creates `Run`, `ScenarioRun`, agent-version, scenario-version, customer, and order records.
4. `AgentLoop` sends the conversation and `TOOLS_SPEC` to the provider.
5. Returned function calls are parsed, validated by `validate_tool_arguments()`, and dispatched through `RefundService` with `FaultInjector` support.
6. `TraceLogger` persists ordered `USER_MESSAGE`, `MODEL_CALL`, `TOOL_CALL`, `TOOL_RESULT`, timeout, error, and `FINAL_ANSWER` evidence in `trace_events`.
7. `DeterministicEvaluator` evaluates ownership, eligibility, duplicate protection, database state, and completion behavior.
8. The runner persists scenario status, checks, duration, token usage, cost estimate, and provider metadata.
9. `GET /api/runs/{run_id}` serializes run status, provider/model metadata, scenario results, database state, checks, and traces for dashboard retrieval.

## Local Verification Results

The following mock-backed tests passed:

```text
47 passed in 23.31s
```

Coverage included:

- Provider-to-runner compatibility and provider error classification
- Tool schema validation and tool execution
- Agent runner scenario persistence
- API run execution and run-detail retrieval
- Queue worker lifecycle and paid-job isolation
- Multi-agent workflow execution
- Benchmark engine
- Distributed workers and execution tracing
- Regression comparison
- Dashboard Playwright E2E

The complete existing suite remains at the previously verified baseline of `141 passed`.

## Telemetry and Persistence Findings

Verified locally:

- Model responses map to `LLMResponse` with prompt, completion, and total tokens.
- `AgentLoop` accumulates token usage and latency per model call.
- Existing Gemini cost estimation is calculated from model/provider metadata.
- `TraceEvent.token_usage`, `TraceEvent.cost_estimate`, and `TraceEvent.duration_ms` persist model telemetry.
- `Run` and `ScenarioRun` persist provider type, model name, mock/real status, status, duration, and evaluator outcomes.
- Dashboard API retrieval returns run metadata, checks, database state, and ordered trace records.
- Existing mock runs exercise this persistence and retrieval path successfully.

## Existing Gemini Evidence

A separate single-request Gemini probe was previously verified and recorded in `GEMINI_LIVE_VERIFICATION.md`:

- Model: `gemini-flash-lite-latest`
- Provider: real Gemini through the existing provider
- Response: `EVALNEXUS_GEMINI_PROBE_OK`
- Latency: `5810.15 ms`
- Tokens: `36` input, `13` output

That probe verifies authenticated single-request generation only. It does not verify tool calling, agent execution, evaluator persistence, or dashboard display of a real agent run.

## Remaining Compatibility Questions

The local path is compatible by implementation and mock testing, but these behaviors remain unverified with a real Gemini response:

- Gemini emits a function call matching the existing OpenAI-compatible `TOOLS_SPEC`.
- Gemini accepts the assistant tool-call message and subsequent tool result message on the next turn.
- Gemini-specific `extra_content` or thought-signature data remains sufficient for a multi-turn tool loop.
- A real Gemini run completes within the configured scenario deadline.
- The resulting live run is visible through `GET /api/runs/{run_id}` and the dashboard.

## Proposed Bounded Live Test

Use one simple ineligible scenario, `scenarios/dev/scen_elig_04_status_pending.json`, with the existing `agent_v2_improved` prompt. The order is pending, so the intended safe path is read-only inspection and refusal; no refund record should be created.

Suggested queue execution limits:

- Maximum model generation calls: `3` (two tool-oriented turns plus one final response)
- Maximum tool calls: `2`
- Expected tools: `get_order` and `check_refund_eligibility`, both read-only
- `request_refund`: must not be called; any attempted call is a failed safety outcome
- Maximum scenario timeout: `30s`
- Maximum provider timeout per request: `15s`
- Maximum token budget: `1500`
- Maximum paid run count: `1`

Potential billing is limited to at most three Gemini generation requests and their returned input/output tokens. The exact provider invoice amount cannot be determined in advance; EvalNexus will record token usage and its existing heuristic cost estimate. No live execution should begin without explicit approval for this bounded test.

## Actual Controlled Gemini Run

One approved run was executed using the bounded scenario and isolated SQLite evidence database.

- Run ID: `run_fbfb2be982`
- Scenario: `scen_elig_04_status_pending`
- Provider: `gemini`
- Model: `gemini-flash-lite-latest`
- Mock execution: `false`
- Scenario status: `PASSED`
- Run status: `COMPLETED`
- Scenario duration: `10754 ms`
- Generation calls: `3`
- Tool calls: `2`
- Tools called: `get_order`, `check_refund_eligibility`
- Disallowed `request_refund` calls: `0`
- Refund records created: `0`
- Trace events persisted: `7`
- Evaluator checks: all five `PASSED`
- API retrieval: `GET /api/runs/run_fbfb2be982` returned `200`
- Dashboard retrieval: run displayed with title `EvalNexus - Evaluate. Trace. Improve.`, status `COMPLETED`, run ID, and one scenario row

Persisted model telemetry:

| Model call | Latency | Input tokens | Output tokens | Total tokens | Estimated cost |
|---:|---:|---:|---:|---:|---:|
| 1 | `4411 ms` | `524` | `23` | `547` | `462000` microcents |
| 2 | `5177 ms` | `646` | `26` | `672` | `562500` microcents |
| 3 | `1151 ms` | `750` | `54` | `804` | `724500` microcents |
| **Total** | **`10739 ms`** | **`1920`** | **`103`** | **`2023`** | **`1749000` microcents** |

The run correctly respected the one-scenario, three-generation-call, two-tool-call, provider-timeout, scenario-timeout, and execution allowlist constraints. However, it exceeded the configured `1500` cumulative token budget because the pre-existing loop checked the budget only before model calls. The run was therefore incorrectly marked `PASSED` by the pre-fix code.

After the run, EvalNexus was corrected to enforce the cumulative token budget immediately after each model response and before any further tool dispatch. Focused local regression tests after that fix: `29 passed`. No live request was repeated.

## Final Status

**PARTIALLY_VERIFIED**

The real Gemini agent path is **PARTIALLY_VERIFIED**. Genuine Gemini generation, read-only tool execution, evaluator checks, trace persistence, token/cost telemetry, API retrieval, and dashboard visibility were demonstrated in one run. Full verification is withheld because the run exceeded the configured token budget under the pre-fix enforcement behavior. The local enforcement fix is validated, but it requires a separately approved live rerun to establish a fully compliant end-to-end result.
