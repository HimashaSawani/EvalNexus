# EvalNexus V3 — 2-3 Minute Portfolio Demo Walkthrough

This guide provides a structured, step-by-step demonstration walkthrough for showcasing EvalNexus V3 in a technical portfolio presentation, video demo, or recruiter interview.

---

## Demo Overview

| Timestamp | Segment | Dashboard Screen | Key Talking Point |
|---|---|---|---|
| **0:00 – 0:30** | Platform Introduction & Overview | `#overview` | Deterministic reliability vs. stochastic LLM-as-a-judge |
| **0:30 – 1:00** | Agent Benchmarking in Studio | `#test-studio` | Turn limits, tool budgets, and deterministic mock simulator |
| **1:00 – 1:30** | Real Qwen2.5-1.5B Colab Execution | `#test-studio?run=colab_...` | Genuine open-source inference on cloud GPU without paid APIs |
| **1:30 – 2:00** | Execution Traces & Spans | `#test-studio` (Timeline Tab) | Tool execution, latency (2225ms), and token metrics |
| **2:00 – 2:30** | Contract Mismatch & Audited Revision | `#test-studio` (Checks Tab) | Why write-mutation checks failed read-only inquiry, and how audit revisions solve it |
| **2:30 – 3:00** | Regression Scorecards & Quality Gates | `#regression-testing` & `#quality-gates` | Automated drift detection and enterprise release readiness |

---

## Step-by-Step Walkthrough Script

### 1. Platform Overview (0:00 – 0:30)
* **Navigate to:** `http://127.0.0.1:8001/#overview`
* **Visuals:** Highlight the System Overview scorecards, provider breakdown (Mock Simulator vs. Real Colab GPU), and recent runs table.
* **Talking Points:**
  > *"EvalNexus is an AI agent reliability platform designed to evaluate autonomous tool-using agents against deterministic database state, sequential traces, and operational invariants rather than subjective 'LLM-as-a-judge' scorers. Here in the overview, you can see live reliability metrics, execution distribution, and historical benchmarks."*

---

### 2. Test Studio & Deterministic Benchmarking (0:30 – 1:00)
* **Navigate to:** `http://127.0.0.1:8001/#test-studio`
* **Action:** Show the Test Studio controls. Select `agent_v1_baseline`, Engine `mock`, and click **Queue Benchmark Run**.
* **Visuals:** Watch the embedded worker process all 30 benchmark scenarios in ~4 seconds, populating check results.
* **Talking Points:**
  > *"In the Test Studio, teams can benchmark agents across 30 standard scenarios covering normal refund lifecycles, 14-day boundary edge cases, and simulated faults. With the deterministic mock simulator, complete test suites run locally in seconds with zero external API costs."*

---

### 3. Real Open-Source LLM Execution (Qwen2.5 on Colab Pro) (1:00 – 1:30)
* **Navigate to:** `http://127.0.0.1:8001/#test-studio?run=colab_single_20261111_105817_4c22cb`
* **Visuals:** Point out the Run header:
  * Model: `Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)`
  * Provider: `colab_offline`
  * Execution Duration: `2225ms`
* **Talking Points:**
  > *"EvalNexus also supports open-source model evaluation without commercial API keys. We export scenario bundles as portable JSON fixtures, execute real inference on Google Colab Pro using an NVIDIA Tesla T4 GPU with Qwen2.5-1.5B-Instruct, and import the results back into EvalNexus for deterministic evaluation."*

---

### 4. Ordered Execution Traces & Microsecond Latencies (1:30 – 2:00)
* **Action:** Click the **Timeline** tab in Test Studio.
* **Visuals:** Stepper timeline displaying 4 events:
  1. `USER_MESSAGE`: *"Is order ord_elig_01 still eligible for a refund today?"*
  2. `TOOL_CALL`: `check_refund_eligibility({"order_id": "ord_elig_01"})` (962ms)
  3. `TOOL_RESULT`: `{"eligible": true, "max_refundable_cents": 6000}` (5ms)
  4. `MODEL_CALL`: *"Yes, order ord_elig_01 is still eligible for a refund today..."* (1257ms)
* **Talking Points:**
  > *"Every single step the agent took is recorded with microsecond timing and token consumption. The Qwen model consumed 767 prompt tokens and 70 completion tokens, invoked the eligibility tool accurately, and correctly synthesized a natural language confirmation."*

---

### 5. Contract Mismatch Investigation & Audited Revision (2:00 – 2:30)
* **Action:** Click the **Assertion Checks** tab in Test Studio.
* **Visuals:** Show the original `FAILED` status alongside the green **Audited Evaluation Revision Banner** (`ev_rev_eb2ddd6d5ea3` $\to$ `PASSED`).
* **Talking Points:**
  > *"Notice that the original evaluation marked this scenario as FAILED. Why? Because the legacy evaluator expected a database mutation (creating a refund request). But this customer was asking an inquiry! The model followed safety policies and correctly refused to mutate the database.  
  Instead of rewriting historical data, EvalNexus created an immutable, auditable evaluation revision under the `READ_ONLY_INQUIRY` contract. The revision verified tool evidence, answer correctness, and zero database mutations, confirming that all 5 checks passed while keeping historical records intact for auditors."*

---

### 6. Reliability Analytics, Regression Scorecards & Quality Gates (2:30 – 3:00)
* **Navigate to:** `http://127.0.0.1:8001/#regression-testing`
* **Action:** Compare baseline vs. candidate runs to show behavioral tool-call drift, $p50$/$p90$ latency shifts, and statistical confidence warnings.
* **Navigate to:** `http://127.0.0.1:8001/#quality-gates`
* **Visuals:** Show enterprise quality gate evaluation (0 security leaks, pass rate $\ge 90\%$).
* **Closing:**
  > *"With automated regression scorecards, multi-process spending caps, and enterprise quality gates, EvalNexus provides engineering teams with the confidence that autonomous AI agents behave safely, reliably, and within defined policy constraints."*

