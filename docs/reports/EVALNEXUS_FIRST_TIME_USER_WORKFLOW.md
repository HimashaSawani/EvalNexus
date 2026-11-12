# EvalNexus V3 — First-Time User Experience & Custom AI Agent Workflow Report

**Document ID:** `EVALNEXUS-UX-WORKFLOW-20261112`  
**Date:** November 12, 2026  
**Roles:** Senior AI Platform Product Engineer, UX Engineer, Full-Stack QA Engineer  
**Repository:** `D:\AgentWindTunnel\AgentWindTunnel` (Branch: `main`)  
**Status:** **VERIFIED & FUNCTIONAL** (100% Pass Rate across Unit, Integration, Playwright E2E, and Live HTTP Synthetic Agent Verification)

---

## 1. Executive Summary & Problem Diagnosis

### The Problem
When a first-time developer arrived at the EvalNexus dashboard, the Test Studio interface primarily presented internal predefined dropdowns (`Version A (Baseline)`, `Version B (Robust Compliant)`, `Scripted Deterministic Runner`, `Mock Simulator`, `dev_suite`). 

For external developers, this created confusion:
1. **Unclear Purpose:** The platform appeared as an internal research demo rather than an open AI Agent Evaluation & Benchmarking Platform.
2. **Missing Developer Journey:** There was no obvious onboarding explaining:
   - How to test built-in simulated models (**Mode A: Try Demo Evaluation**).
   - How to connect and evaluate their own AI agent (**Mode B: Evaluate My Own AI Agent**).
3. **Disconnected Features:** While the backend supported a `CustomAgent` registry (`/api/custom-agents`) and `CustomScenario` builder (`/api/scenarios/custom`), they were disconnected from Test Studio:
   - `providerSelect` was missing the `custom_http` provider.
   - `agentSelect` did not list registered custom agents.
   - `suiteSelect` did not populate custom scenarios created in Scenario Builder.
   - No direct "Test in Studio" action existed in the Custom Agents or Scenario Builder tables.

### The Solution Implemented
Without introducing fragile new backend frameworks or breaking existing contracts, we seamlessly bridged the existing architecture:
- Added a high-level **"Get Started with EvalNexus"** onboarding section to System Overview.
- Implemented an intuitive **Mode Switcher** in Test Studio:
  - **Mode A (🧪 Try Demo Evaluation):** Zero-setup simulated mock testing with educational banners.
  - **Mode B (🚀 Evaluate My Own Agent):** Dedicated custom HTTP agent testing workflow with live endpoint probing, preflight verification, and expandable HTTP API contract specifications.
- Dynamically populated `suiteSelect` with user-created custom scenarios from Scenario Builder.
- Added one-click **"⚡ Test in Studio"** buttons to both the Custom Agent Registry and Scenario Builder.
- Fixed backend runner parameter forwarding so registered agent secret tokens and headers are automatically resolved from SQLite during queue execution.

---

## 2. Capability Audit Matrix

| Component / Layer | Pre-Existing State | Gaps Identified | Enhancement Implemented | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Overview Dashboard** | Real-time KPIs & Recent Runs table | No onboarding or path selection for first-time visitors | Added 2-card onboarding banner (Demo vs Custom Agent) | **COMPLETED** |
| **Test Studio Modes** | Single hardcoded view for mock agents | No distinction between demo simulation and external agent testing | Dual-mode tab switcher (Mode A vs Mode B) with dynamic guidance banners | **COMPLETED** |
| **Provider Selection** | `mock`, `gemini`, `openai` | Missing `custom_http` option | Added `Custom External Agent (HTTP)` (`custom_http`) to `providerSelect` | **COMPLETED** |
| **Custom Agent Binding** | Isolated in separate view | Test Studio could not select registered agents from DB | Dynamic custom agent dropdown with live endpoint ping probe and status pill | **COMPLETED** |
| **Custom Scenarios** | Saved to disk / DB, but isolated | Test Studio `suiteSelect` had hardcoded choices only | Dynamic `<optgroup>` loading custom scenarios from `/api/scenarios/custom` | **COMPLETED** |
| **HTTP Contract Specs** | Documented only in Python code | Developer had no in-app reference for request/response JSON schema | Expandable inline HTTP Protocol & Contract reference card in Test Studio | **COMPLETED** |
| **Runner Auth Forwarding**| Only checked `os.getenv` for auth token | Registered agents with custom headers/tokens in DB didn't receive tokens in worker | Forwarded `auth_header_name` and `auth_token_secret` through `execution_config` and `resolve_provider` | **COMPLETED** |
| **Order Amount Mapping** | Strict `total_amount_cents` key required | Scenario Builder orders used `amount_cents`, causing `KeyError` | Runner falls back gracefully between `total_amount_cents` and `amount_cents` | **COMPLETED** |

---

## 3. End-to-End User Journey Verification

A genuine synthetic FastAPI HTTP agent was deployed locally at `http://127.0.0.1:8009/invocations` requiring `Authorization: Bearer test-secret-token-12345`. The complete first-time user journey was executed and verified via [`scripts/verify_first_time_user_journey.py`](file:///D:/AgentWindTunnel/AgentWindTunnel/scripts/verify_first_time_user_journey.py).

### Execution Evidence Log
```text
[INFO] === Starting EvalNexus First-Time User Journey Verification ===
[PASS] Backend is healthy (HTTP 200)
[INFO] Step 2: Registering Synthetic AI Agent...
[PASS] Registered agent 'synthetic-refund-agent-v1' with masked token 'tes***345'
[INFO] Step 3: Probing Synthetic Agent Endpoint via Ping...
[PASS] Agent Ping ONLINE! Latency: 641ms, Preview: '{"content":"synthetic-agent-v1-online","tool_calls":[],"prompt_tokens":10,"completion_tokens":5}'
[INFO] Step 4: Creating Compatible Custom Test Scenario in Scenario Builder...
[PASS] Created custom scenario 'scen_custom_synthetic_01' (Synthetic Agent 3-Day Delivered Order Refund)
[INFO] Step 5: Queuing Evaluation Run against Registered Custom Agent...
[PASS] Queued run 'run_d04dc42165' with provider 'custom_http' and model 'synthetic-refund-agent-v1'
[INFO] Step 6: Polling run 'run_d04dc42165' for completion...
[PASS] Run run_d04dc42165 COMPLETED with 1/1 passed scenarios!
[INFO] Step 7: Verifying genuine agent tool execution traces from run record...
[INFO] Retrieved 7 execution trace events from scenario run scen_run_1c595d36
[INFO] Traces retrieved: 7 events. Tools called: ['check_refund_eligibility', 'request_refund']
[PASS] Genuine tool calls verified: ['check_refund_eligibility', 'request_refund']
[INFO] Step 8: Testing Negative Edge Cases...
[PASS] 8a: Unauthorized auth token probe cleanly caught (HTTP_401)
[PASS] 8b: Malformed schema rejected and recorded as failed scenario
[PASS] 8c: SSRF metadata endpoint registration blocked (HTTP 400)
[PASS] === ALL FIRST-TIME USER JOURNEY TESTS PASSED SUCCESSFULLY! ===
```

### Verification Findings:
1. **Genuine Invocations Confirmed:** Traces confirm that the synthetic agent executed multi-turn tool calling (`check_refund_eligibility` followed by `request_refund` with idempotency key `op_synth_key_999`), and synthesized a final compliant customer answer. It was **not** replaced by the mock simulator.
2. **Deterministic Evaluation Assertion:** Evaluator verified all 5 checks (`OWNERSHIP`, `ELIGIBILITY`, `DUPLICATE`, `STATE`, `COMPLETION`) and passed the scenario with 100% score.
3. **Idempotency & Masking:** Secret tokens remain masked (`tes***345`), never exposed in plaintext.
4. **Security & SSRF:** Link-local and cloud metadata addresses (`169.254.169.254`) are strictly blocked (HTTP 400).

---

## 4. Visual Evidence & Screenshots

### Evidence 1: System Overview Onboarding Paths
![System Overview Onboarding](file:///D:/AgentWindTunnel/AgentWindTunnel/docs/reports/screenshots/uat_onboarding_01_overview.png)
*Figure 1: Welcome banner presenting two distinct evaluation paths: "Option 1: Try Demo Evaluation" and "Option 2: Evaluate My Own AI Agent".*

---

### Evidence 2: Test Studio — Mode A: Try Demo Evaluation
![Test Studio Demo Mode](file:///D:/AgentWindTunnel/AgentWindTunnel/docs/reports/screenshots/uat_onboarding_02_demo_mode.png)
*Figure 2: Test Studio in Demo Mode with educational banner indicating simulated execution without external API costs.*

---

### Evidence 3: Test Studio — Mode B: Custom Agent with HTTP Contract Specs
![Test Studio Custom Agent Mode](file:///D:/AgentWindTunnel/AgentWindTunnel/docs/reports/screenshots/uat_onboarding_03_custom_agent_mode.png)
*Figure 3: Custom Agent mode active with endpoint status indicator, preflight ping probe, and expanded HTTP integration protocol specifications.*

---

### Evidence 4: Custom Agent Registry with One-Click Studio Actions
![Custom Agent Registry](file:///D:/AgentWindTunnel/AgentWindTunnel/docs/reports/screenshots/uat_onboarding_04_custom_agent_registry.png)
*Figure 4: Custom Agent Registry showing registered agents, masked tokens, and the new "⚡ Test in Studio" action button.*

---

## 5. Automated Regression Verification

The complete regression suite was executed to guarantee zero breaking changes across existing features:

```text
======================================================================
PYTEST REGRESSION SUITE:
- Unit & Integration Tests: 162 passed in 18.65s (100%)
- Playwright E2E Sections:    1 passed in 9.94s  (100%)
======================================================================
TOTAL AUTOMATED REGRESSION: 163 / 163 PASSED
```

---

## 6. Review of Repository Artifacts & Cleanup Recommendations

In response to the repository audit findings:
1. **`docs/reports/` Artifacts:**
   The reports and screenshot PNGs document historical testing and acceptance verification. For release distribution, we can add `docs/reports/*.json`, `docs/reports/*.db*` to `.gitignore` while retaining primary markdown architectural reports.
2. **Synthetic Sensitive-Looking Data:**
   Test card numbers (`4111-2222-3333-4444`) and SSN-like values in `backend/policies/policy_eval.py` and `tests/` are standard RFC-compliant synthetic test vectors used to test PII leakage detection.
3. **Dummy Secrets in Templates:**
   Placeholders in `.env.example` and `docker-compose.yml` can be updated to `<set-locally>` or empty strings to prevent scanner false positives.
4. **Historical Token `awt-prod-secret-key-9988`:**
   Confirmed to be a legacy local test token not present in active configuration.

---

## 7. Limitations & Operational Scope

1. **Protocol:** Custom agents must communicate over standard HTTP/HTTPS POST matching the `CustomAgentRequestPayload` / `CustomAgentResponsePayload` schemas. Agents utilizing raw WebSockets or proprietary binary RPC protocols require a lightweight HTTP proxy/adapter.
2. **SSRF Guardrail:** Evaluates hostname and link-local IP boundaries. In production environments where agents run on internal private IP blocks, set `AWT_BLOCK_INTERNAL_NETWORKS=0` for internal VPC testing.
3. **Execution Limits:** Custom agent turn execution is bounded by `timeout_sec` (default 15.0s, configurable up to 60.0s) and turn budgets to prevent runaway costs.

