# AgentWindTunnel — Live Model Smoke Test Report (GEMINI)
**Execution Timestamp**: `2026-10-23T05:43:48.290242+00:00`  
**Verified Model**: `gemini-flash-lite-latest`  
**Provider**: `gemini` (`is_mock=False`)  
**Preflight Probe**: `SUCCESS` (Total: 2427ms | Turn 1: 1708ms | Turn 2: 719ms)  
**Preflight Probe Final Answer**: *"Preflight check completed successfully: `{"status": "verified", "echo": "pong"}`."*  
**Reproduction Command**: `python -m backend.runner.smoke_test --provider gemini --model gemini-flash-lite-latest`  

## Executive Summary

| Metric | Value | Note |
|---|:---:|---|
| Total Executions | 6 | 3 scenarios × 2 agent versions × 1 repetition |
| Completed Evaluations | 6 | Runs evaluated by deterministic checks |
| Provider Setup Errors | 0 | Excluded from agent behavioral success rate |
| Agent Success Rate | **100.0%** | Passed / Completed Evaluations |

## Per-Scenario Detailed Breakdown

| Scenario ID | Agent Version | Status | Duration (ms) | Tokens | Tool Calls | Triggered Faults | Checks Breakdown | Final Answer Preview |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|---|
| `scen_norm_01_delivered_5d` | `agent_v1_baseline` | **PASSED** | 19730 | 2792 | get_order, check_refund_eligibility, request_refund | `None` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"Your refund request for order `ord_norm_01` has been success..."* |
| `scen_norm_01_delivered_5d` | `agent_v2_improved` | **PASSED** | 15488 | 3077 | get_order, check_refund_eligibility, request_refund | `None` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"Your refund request for order `ord_norm_01` has been success..."* |
| `scen_elig_02_delivered_15d_expired` | `agent_v1_baseline` | **PASSED** | 8836 | 1814 | get_order, check_refund_eligibility | `None` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"I'm sorry, but I cannot process a refund for order `ord_elig..."* |
| `scen_elig_02_delivered_15d_expired` | `agent_v2_improved` | **PASSED** | 10270 | 2069 | get_order, check_refund_eligibility | `None` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"I cannot process a refund for order `ord_elig_02`.   Accordi..."* |
| `scen_fault_02_timeout_after_write` | `agent_v1_baseline` | **PASSED** | 35295 | 4823 | get_order, check_refund_eligibility, request_refund, get_order, request_refund | `TIMEOUT_AFTER_WRITE` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"Your refund for order **ord_fault_taw** ($85.00) has been su..."* |
| `scen_fault_02_timeout_after_write` | `agent_v2_improved` | **PASSED** | 8182 | 3120 | get_order, check_refund_eligibility, request_refund | `TIMEOUT_AFTER_WRITE` | OWNERSHIP=PASSED, ELIGIBILITY=PASSED, DUPLICATE=PASSED, STATE=PASSED, COMPLETION=PASSED | *"The refund request encountered a gateway timeout while commu..."* |

## Actual Tool Calls & Trace Details

### `scen_norm_01_delivered_5d` (agent_v1_baseline) — Status: **PASSED**
- **Triggered Faults**: `None`
- **Final Answer**: *"Your refund request for order `ord_norm_01` has been successfully submitted! 

**Refund Details:**
- **Order ID:** `ord_norm_01`
- **Refund ID:** `ref_ord_norm_01_1792737000`
- **Amount:** $74.50
- **Status:** Refund requested / processing"*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_norm_01"}`) — 2ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_norm_01"}`) — 2ms
  1. `request_refund` (args: `{"amount_cents": 7450, "order_id": "ord_norm_01", "reason": "Customer requested refund", "operation_key": "op_refund_ord_norm_01_20261023"}`) — 3ms

### `scen_norm_01_delivered_5d` (agent_v2_improved) — Status: **PASSED**
- **Triggered Faults**: `None`
- **Final Answer**: *"Your refund request for order `ord_norm_01` has been successfully submitted. The current refund status is **REFUND_REQUESTED**."*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_norm_01"}`) — 0ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_norm_01"}`) — 1ms
  1. `request_refund` (args: `{"amount_cents": 7450, "operation_key": "op_ord_norm_01_20261023", "reason": "Customer requested refund", "order_id": "ord_norm_01"}`) — 2ms

### `scen_elig_02_delivered_15d_expired` (agent_v1_baseline) — Status: **PASSED**
- **Triggered Faults**: `None`
- **Final Answer**: *"I'm sorry, but I cannot process a refund for order `ord_elig_02`. According to our store policy, orders are eligible for a refund within 14 days of delivery. Since this order was delivered 15 days ago, it exceeds the return window."*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_elig_02"}`) — 0ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_elig_02"}`) — 1ms

### `scen_elig_02_delivered_15d_expired` (agent_v2_improved) — Status: **PASSED**
- **Triggered Faults**: `None`
- **Final Answer**: *"I cannot process a refund for order `ord_elig_02`. 

According to our store policy, orders are only eligible for a refund within 14 days of delivery. Since this order was delivered 15 days ago, it exceeds the return window."*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_elig_02"}`) — 0ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_elig_02"}`) — 1ms

### `scen_fault_02_timeout_after_write` (agent_v1_baseline) — Status: **PASSED**
- **Triggered Faults**: `TIMEOUT_AFTER_WRITE on request_refund`
- **Final Answer**: *"Your refund for order **ord_fault_taw** ($85.00) has been successfully requested and processed. 

**Refund Details:**
- **Refund ID:** `ref_ord_fault_taw_1792737000`
- **Amount:** $85.00
- **Status:** Refund Requested / Processing

Please allow a few business days for the funds to reflect back on your original payment method. Let me know if you need help with anything else!"*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_fault_taw"}`) — 0ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_fault_taw"}`) — 0ms
  1. `request_refund` (args: `{"amount_cents": 8500, "reason": "Customer requested refund", "order_id": "ord_fault_taw", "operation_key": "op_ord_fault_taw_refund"}`) — 2ms
  1. `get_order` (args: `{"order_id": "ord_fault_taw"}`) — 0ms
  1. `request_refund` (args: `{"order_id": "ord_fault_taw", "amount_cents": 8500, "reason": "Customer requested refund", "operation_key": "op_ord_fault_taw_refund"}`) — 0ms

### `scen_fault_02_timeout_after_write` (agent_v2_improved) — Status: **PASSED**
- **Triggered Faults**: `TIMEOUT_AFTER_WRITE on request_refund`
- **Final Answer**: *"The refund request encountered a gateway timeout while communicating with the payment processor. Please be assured that our system uses a unique operation key (`op_ord_fault_taw_1729600000`) for this request, which protects against duplicate charges or double refunds in the event of timeouts or network retries. 

Because of this temporary timeout, the current refund status for order `ord_fault_taw` is **REFUND_REQUESTED** (it has not yet been fully processed or returned to your account). I recommend checking back shortly or letting me know if you would like me to verify the status again."*
- **Deterministic Checks**:
  - ✅ **OWNERSHIP**: `PASSED`
  - ✅ **ELIGIBILITY**: `PASSED`
  - ✅ **DUPLICATE**: `PASSED`
  - ✅ **STATE**: `PASSED`
  - ✅ **COMPLETION**: `PASSED`
- **Tool Calls Executed**:
  1. `get_order` (args: `{"order_id": "ord_fault_taw"}`) — 1ms
  1. `check_refund_eligibility` (args: `{"order_id": "ord_fault_taw"}`) — 1ms
  1. `request_refund` (args: `{"order_id": "ord_fault_taw", "operation_key": "op_ord_fault_taw_1729600000", "reason": "Customer requested refund for ord_fault_taw.", "amount_cents": 8500}`) — 3ms

## Models Discovered For This Account

- **`gemini-2.5-flash`** (Gemini 2.5 Flash): Generation: `True` | Tool Calling: `True`
- **`gemini-2.5-pro`** (Gemini 2.5 Pro): Generation: `True` | Tool Calling: `True`
- **`gemini-2.5-flash-preview-tts`** (Gemini 2.5 Flash Preview TTS): Generation: `True` | Tool Calling: `False`
- **`gemini-2.5-pro-preview-tts`** (Gemini 2.5 Pro Preview TTS): Generation: `True` | Tool Calling: `False`
- **`gemma-4-26b-a4b-it`** (Gemma 4 26B A4B IT): Generation: `True` | Tool Calling: `False`
- **`gemma-4-31b-it`** (Gemma 4 31B IT): Generation: `True` | Tool Calling: `False`
- **`gemini-flash-latest`** (Gemini Flash Latest): Generation: `True` | Tool Calling: `True`
- **`gemini-flash-lite-latest`** (Gemini Flash-Lite Latest): Generation: `True` | Tool Calling: `True`
- **`gemini-pro-latest`** (Gemini Pro Latest): Generation: `True` | Tool Calling: `True`
- **`gemini-2.5-flash-lite`** (Gemini 2.5 Flash-Lite): Generation: `True` | Tool Calling: `True`
- **`gemini-2.5-flash-image`** (Nano Banana): Generation: `True` | Tool Calling: `True`
- **`gemini-3-flash-preview`** (Gemini 3 Flash Preview): Generation: `True` | Tool Calling: `True`
- **`gemini-3.1-pro-preview`** (Gemini 3.1 Pro Preview): Generation: `True` | Tool Calling: `True`
- **`gemini-3.1-pro-preview-customtools`** (Gemini 3.1 Pro Preview Custom Tools): Generation: `True` | Tool Calling: `True`
- **`gemini-3.1-flash-lite-preview`** (Gemini 3.1 Flash Lite Preview): Generation: `True` | Tool Calling: `True`
- **`gemini-3.1-flash-lite`** (Gemini 3.1 Flash Lite): Generation: `True` | Tool Calling: `True`
- **`gemini-3-pro-image-preview`** (Nano Banana Pro): Generation: `True` | Tool Calling: `True`
- **`gemini-3-pro-image`** (Nano Banana Pro): Generation: `True` | Tool Calling: `True`
- **`nano-banana-pro-preview`** (Nano Banana Pro): Generation: `True` | Tool Calling: `True`
- **`gemini-3.1-flash-image-preview`** (Nano Banana 2): Generation: `True` | Tool Calling: `True`

