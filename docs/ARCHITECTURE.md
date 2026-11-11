# EvalNexus V3 System Architecture

**Document Version:** 3.0.0  
**Classification:** Technical Architecture Specification  
**Status:** Implemented & Deterministically Verified  

---

## 1. Architecture Overview

EvalNexus V3 is architected as an evidence-grounded evaluation and reliability platform for tool-using AI agents. The platform separates agent execution from evaluation assertions, ensuring that agents are evaluated against deterministic database state, sequential trace spans, and operational invariants rather than subjective heuristics.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              EvalNexus Web Platform Core                               │
│                                                                                        │
│   FastAPI Service Layer                                                                │
│   - REST API with OpenAPI Specification                                                │
│   - Configurable Key/Bearer Authentication (AWT_API_KEY, AWT_REQUIRE_AUTH)             │
│   - Sliding-Window Rate Limiting (In-memory IP tracking)                                │
│   - Trusted CORS Origin Enforcement (AWT_ALLOWED_ORIGINS)                              │
│   - Single-Page Interactive Dashboard (16 sections served at / from static index.html) │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                            Relational Persistence Layer                                │
│                                                                                        │
│   SQLAlchemy 2.0 ORM with SQLite WAL Mode / PostgreSQL Compatibility                   │
│   - Core Evaluation: runs, scenario_runs, trace_events, check_results                  │
│   - Scientific Auditing: evaluation_revisions                                          │
│   - Queue Management: queue_jobs, worker_nodes                                         │
│   - Domain Simulation: customers, orders, refund_requests                              │
│   - Extensibility: custom_agents, custom_scenarios, workflows, quality_gates           │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   ▼                                               ▼
┌──────────────────────────────────────┐       ┌────────────────────────────────────────┐
│      Local Execution Engines         │       │     Google Colab Pro Offline Pipeline  │
│                                      │       │                                        │
│  1. Deterministic Mock Engine        │       │  1. Scenario Bundle Exporter           │
│     - Zero-cost, 100% reproducible   │       │     (JSON schema, synthetic fixtures)  │
│     - Complete e-commerce domain     │       │                   │                    │
│                                      │       │                   ▼                    │
│  2. Custom Agent HTTP Provider       │       │  2. Google Drive / Colab Pro T4 GPU    │
│     - Black-box HTTP/HTTPS testing   │       │     (Real Qwen2.5-1.5B Inference)      │
│     - SSRF link-local & IP guards    │       │                   │                    │
│                                      │       │                   ▼                    │
│  3. Multi-Agent Workflow Engine      │       │  3. Batch Result Importer              │
│     - Multi-step DAG orchestration   │       │     (Trace seeding, latency, tokens)   │
│     - State passing & step checks    │       │                   │                    │
│                                      │       │                   ▼                    │
│  4. Commercial LLM Adapters          │       │  4. Deterministic Evaluator Engine     │
│     - Google Gemini (GenAI SDK)      │       │     - READ_ONLY_INQUIRY contract       │
│     - OpenAI (OpenAI SDK)            │       │     - FULL_MUTATION contract           │
│     - Spending & concurrency ceiling │       │     - Auditable Evaluation Revision    │
└──────────────────────────────────────┘       └────────────────────────────────────────┘
```

---

## 2. Core Subsystems

### 2.1 Local FastAPI Evaluation Platform

* **Application Entrypoint:** `backend.main:app`
* **Worker Topologies:**
  * **Mode A (Embedded Worker):** Activated when `AWT_EMBEDDED_WORKER=1`. Runs an in-process daemon thread polling `queue_jobs` every 1.0s. Ideal for local development, test automation, and single-container deployments.
  * **Mode B (Standalone Worker):** Activated when `AWT_EMBEDDED_WORKER=0`. Starts a separate process (`python -m backend.worker`) using atomic database locks to claim jobs.
* **Database Concurrency:** SQLite in WAL mode with `PRAGMA busy_timeout=5000` and `synchronous=NORMAL` enables concurrent readers (dashboard queries, API clients) and worker writes without locking contention.

### 2.2 Custom Agent HTTP Adapter & SSRF Protection

* **Component:** `backend.agent.custom_adapter:CustomHTTPAgentProvider`
* **Purpose:** Evaluates external agents over HTTP without running arbitrary untrusted code inside the EvalNexus runtime.
* **SSRF Defenses:**
  * Enforces `http` or `https` schemes.
  * Resolves target host IP and blocks loopback (`127.0.0.0/8`), private RFC-1918 networks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local IPs (`169.254.0.0/16`), and cloud metadata services (`169.254.169.254`).
  * Explicitly disables HTTP redirect following (`follow_redirects=False`) to prevent open-redirect SSRF bypasses.

### 2.3 Colab-Hosted Qwen Inference & Google Drive Offline Transfer

* **Component:** `EvalNexus_Colab_LLM.ipynb` & `backend.scenarios.offline_bundle.py`
* **Purpose:** Evaluates open-source LLMs (`Qwen2.5-1.5B-Instruct`) on cloud GPU hardware (NVIDIA Tesla T4 with 16GB VRAM) without external paid API costs.
* **Offline Protocol:**
  1. **Bundle Export (`POST /api/scenarios/bundle/export`):** Generates a self-contained JSON bundle conforming to `evalnexus-scenario-bundle/v1`. Includes scenario customer/order fixtures, system prompts, execution limits, and tool JSON schemas. Zero credentials or environment variables are included.
  2. **Colab Execution:** Executed in Google Colab Pro. Loads the model in `float16` precision, processes turns, executes simulated tool calls locally, logs ordered spans with microsecond latencies and token counts.
  3. **Result Import (`POST /api/runs/import-colab`):** Validates the payload against `evalnexus-evaluation-result/v1`, seeds the scenario customer/order state into SQLite, writes ordered `TraceEvent` rows, and executes the `DeterministicEvaluator`.

### 2.4 Deterministic Evaluator Engine & Dual Evaluation Contracts

* **Component:** `backend.runner.evaluator:DeterministicEvaluator`
* **Assertion Axes:**
  * **`OWNERSHIP`:** Inspects trace arguments for any cross-customer access attempt. Fails immediately if an agent attempts to inspect or refund orders belonging to another customer.
  * **`ELIGIBILITY`:** Validates business policy compliance against a fixed scenario clock (e.g., 14-day return window from delivery date).
  * **`DUPLICATE`:** Validates idempotency key stability and detects duplicate refund attempts.
  * **`STATE`:** Validates exact minor-unit currency amounts (cents) and database ledger status.
  * **`COMPLETION`:** Distinguishes clean termination from turn limits, tool timeouts, and token exhaustion.
* **Dual Contracts:**
  * **`FULL_MUTATION`:** The default contract for write-authorized agents. Requires that an eligible order produces exactly 1 `RefundRequest` in the database matching order amounts and idempotency constraints.
  * **`READ_ONLY_INQUIRY`:** The contract for inquiry and eligibility agents. Strictly verifies:
    1. Agent queried required eligibility tool evidence.
    2. Agent queried the correct customer order.
    3. Tool payload was well-formed and valid.
    4. Tool evidence matches expected eligibility.
    5. Agent final response does not contradict tool evidence.
    6. Agent executed zero unauthorized write calls (`request_refund`).
    7. Database state remained unmodified (zero refund records created).
    8. Execution terminated within turn/budget limits.

### 2.5 Auditable Evaluation Revision Mechanism

* **Component:** `backend.runner.evaluator:re_evaluate_scenario_run` & `backend.database.models:EvaluationRevision`
* **Purpose:** Allows re-evaluating historical runs under revised evaluation policies without destroying the original evaluation history.
* **Audit Guarantees:**
  * The original `Run`, `ScenarioRun`, and `CheckResult` rows remain **100% intact**.
  * A separate `EvaluationRevision` record is created linking `scenario_run_id` and `run_id`.
  * Records the `revision_num`, `evaluation_mode`, `evaluator_version`, `engineer_id`, `reason`, `previous_status`, `new_status`, and full serialized check rationales.
  * Enables regression tracking and evaluation policy audits over time.

---

## 3. Explicit Boundaries & Decoupled Modules

### Decoupling from ETGNN
* **ETGNN (Execution Trace Graph Neural Network)** is an experimental, decoupled research module exploring PyTorch Geometric graph neural networks for structural graph classification of trace events.
* **EvalNexus Core does not rely on ETGNN, LangGraph, or RAG frameworks.** EvalNexus Core is a standalone, deterministic reliability testing platform built on native Python, FastAPI, SQLAlchemy, and HuggingFace Transformers.

