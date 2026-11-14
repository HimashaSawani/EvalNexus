# EvalNexus — AI Agent Evaluation & Reliability Platform

> **EvalNexus V4 — Portfolio Release Candidate:** An AI agent evaluation and reliability-testing platform with evidence-grounded assertions, real Qwen model execution, cross-domain scenario testing, structured traces, and verified failure detection.

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests Passing](https://img.shields.io/badge/tests-195%20passed-brightgreen.svg)](tests/)
[![Framework Version](https://img.shields.io/badge/EvalNexus-v4.0.0%20Generic%20Framework-blue.svg)](docs/GENERIC_EVALUATION_ARCHITECTURE.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Demonstrated Models](https://img.shields.io/badge/verified%20models-Qwen2.5--1.5B%20%7C%20Gemini%20%7C%20OpenAI-blueviolet.svg)](#6-demonstrated-evaluation-evidence)

---

## 1. Product Overview

EvalNexus is an end-to-end reliability engineering platform built specifically for testing, auditing, and benchmarking autonomous AI agents. Unlike traditional LLM evaluation frameworks that rely on stochastic "LLM-as-a-judge" heuristics, EvalNexus evaluates agents against **deterministic state assertions, sequential execution traces, and strict transactional invariants**.

EvalNexus simulates complex, multi-turn business domains (demonstrated on an e-commerce refund ledger) with realistic API tools, customer sessions, database constraints, and simulated fault injection. It can evaluate:
1. **Local Deterministic Mock Simulator:** 100% reproducible, cost-free infrastructure testing engine ($0.00 spend).
2. **Open-Source LLMs via Google Colab Pro:** Real GPU inference (e.g. `Qwen2.5-1.5B-Instruct` on NVIDIA Tesla T4) via portable JSON scenario bundles and offline result import.
3. **Custom HTTP Agent Endpoints:** Black-box evaluation of external agents over authenticated HTTP/HTTPS with multi-layered SSRF defenses.
4. **Live Commercial LLM Providers:** Google Gemini and OpenAI tool-calling agents with strict spending guards.

---

## 2. Problem Statement

Modern AI agents that execute tools and interact with backends present critical reliability challenges that unit tests and text-similarity metrics fail to catch:

* **Silent Behavioral Drift:** A prompt tweak or model update may achieve the user's intent but introduce dangerous side effects, such as generating duplicate transaction keys, querying unauthorized customer accounts, or attempting unauthorized write operations.
* **Flawed "LLM-as-a-Judge" Evaluators:** Relying on a second LLM to evaluate the first LLM introduces evaluation hallucinations, high token costs, and non-deterministic scores that cannot be audited in regulated industries.
* **Safety vs. Mutation Contract Mismatch:** Agents instructed to answer read-only customer inquiries are often evaluated against write-mutation contracts, artificially penalizing models that follow safety instructions by refusing to modify data.
* **Destructive Overwriting of Historical Benchmarks:** In many platforms, re-evaluating a past run destroys original evaluation records, preventing auditors from understanding how evaluation policies evolved.

**EvalNexus solves this** by grounding evaluations in transactional database state, ordered trace events, dual evaluation contracts (`FULL_MUTATION` vs. `READ_ONLY_INQUIRY`), and immutable, auditable evaluation revisions.

---

## 3. Key Platform Features

* **V4 Generic AI Agent Evaluation Engine:** Evaluates arbitrary agent domains (Sentiment Classification, Autonomous Travel Planning, Financial Auditing, etc.) using declarative `evalnexus-generic-scenario/v2` contracts.
  * **Generic Assertion Engine:** Evaluates `json_schema`, `json_path_equals`, `tool_called`, `tool_not_called`, and `execution_completed` fail-closed with diagnostic evidence.
  * **Safe Allowlisted Synthetic Tools:** Dispatches `echo_tool`, `check_weather`, and `lookup_poi` with zero host access and automatic quarantine of prohibited actions.
  * **Colab Generic Runner (Step 14):** Executes generic scenario bundles on `Qwen2.5-1.5B-Instruct` in Google Colab Pro and exports audited result bundles.
* **Deterministic Evaluator Engine:** Assesses five orthogonal dimensions per scenario:
  * `OWNERSHIP`: Verifies zero unauthorized access to other customers' accounts or orders.
  * `ELIGIBILITY`: Verifies business rules (e.g. 14-day return boundary from delivery clock).
  * `DUPLICATE`: Enforces idempotency key stability and duplicate submission blocking.
  * `STATE`: Checks exact minor-unit currency amounts (cents) and database lifecycle statuses.
  * `COMPLETION`: Assesses clean termination within turn, tool-call, and token budgets.
* **Dual Evaluation Contracts:**
  * `FULL_MUTATION`: Strictly requires database records, amount matches, and status transitions for write-authorized agents.
  * `READ_ONLY_INQUIRY`: Validates tool evidence, prevents unauthorized mutation attempts, verifies response-to-evidence consistency, and enforces zero database writes.
* **Auditable Evaluation Revision Trail:** Re-evaluations generate immutable `EvaluationRevision` audit records with timestamps, engineer identity, rationale, and serialized check rationales without modifying original historical `CheckResult` rows.
* **Google Colab Pro Offline Workflow:** Seamless Google Drive-based export/import pipeline enabling zero-cost evaluation of open-source models (`Qwen2.5-1.5B-Instruct`) on cloud GPUs without paid external LLM APIs.
* **Custom Agent HTTP Registry:** Register and benchmark external AI agents over authenticated HTTP/HTTPS with URL validation and comprehensive SSRF protections (blocking loopback, RFC-1918, link-local, and cloud metadata endpoints).
* **Automated Regression Testing & Scorecards:** Compares baseline vs. candidate runs, detects tool-call sequence drift, computes latency percentiles ($p50$/$p90$), and calculates token/cost deltas with statistical sample warnings.
* **Chaos Lab & Fault Injection:** Simulates network timeouts, database deadlocks, transient 500 errors, rate-limit backpressure, and late-write race conditions.
* **Interactive Dashboard:** Complete single-page dashboard serving 16 sections, including Test Studio, Scenarios Catalog, Trace Explorer, Quality Gates, and Failure Investigation.

---

## 4. System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               EvalNexus Platform Core                                   │
│                                                                                        │
│   FastAPI Backend (REST API, OpenAPI Spec, Key/Bearer Auth, Sliding-Window Rate Limit)  │
│   Interactive Dashboard (16 Modular Sections, Served at / via Static SPA)               │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Persistence Layer (SQLAlchemy)                            │
│   SQLite (WAL Mode + 5000ms Busy Timeout) / PostgreSQL with Connection Pooling         │
│   Tables: runs, scenario_runs, trace_events, check_results, evaluation_revisions,      │
│           queue_jobs, customers, orders, refund_requests, quality_gates, custom_agents  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                   ┌───────────────────────┴───────────────────────┐
                   ▼                                               ▼
┌──────────────────────────────────────┐       ┌────────────────────────────────────────┐
│       Local Execution Workers        │       │      Offline Colab GPU Pipeline        │
│                                      │       │                                        │
│  - Mode A: Embedded Worker Thread    │       │  1. EvalNexus Bundle Exporter          │
│  - Mode B: Standalone Worker Daemon  │       │     (JSON fixtures, limits, tools)     │
│  - Deterministic Mock Engine         │       │                   │                    │
│  - Custom Agent HTTP Provider (SSRF) │       │                   ▼                    │
│  - Live Gemini / OpenAI Runners      │       │  2. Google Drive / Colab Pro (T4 GPU)  │
│  - Atomic Queue Claiming & Heartbeat │       │     (Qwen2.5-1.5B Batch Runner)        │
└──────────────────────────────────────┘       │                   │                    │
                                               │                   ▼                    │
                                               │  3. EvalNexus Batch Result Importer    │
                                               │     (Trace seeding & Deterministic     │
                                               │      Evaluator Check Execution)        │
                                               └────────────────────────────────────────┘
```

### Architectural Boundaries & ETGNN Distinction
* **EvalNexus Core:** Owns scenario definition, execution orchestration, API adapters, trace logging, deterministic evaluation assertions, and the interactive dashboard.
* **ETGNN (Execution Trace Graph Neural Network):** An optional, independent research module exploring graph neural networks for structural anomaly classification on historical trace graphs. ETGNN is decoupled from the core evaluation engine.

---

## 5. Technology Stack

* **Backend & API:** Python 3.11+, FastAPI, Pydantic V2, Uvicorn, HTTPX.
* **Database & ORM:** SQLAlchemy 2.0, Alembic, SQLite (WAL mode), PostgreSQL compatibility.
* **AI & Inference:** HuggingFace Transformers, PyTorch (Colab Pro NVIDIA Tesla T4 GPU), Google GenAI SDK, OpenAI SDK.
* **Testing & QA:** Pytest, Pytest-Asyncio, Playwright (Chromium E2E testing).
* **Frontend:** Vanilla JavaScript (ES6+), CSS3 Variables, JetBrains Mono & Inter typography, SVG vector charts.

---

## 6. Demonstrated Evaluation Evidence

EvalNexus has been verified against actual open-source inference executed in **Google Colab Pro on an NVIDIA Tesla T4 GPU** using `Qwen2.5-1.5B-Instruct` across two distinct paradigms:

### Case Study 1: E-Commerce Inquiry Safety (5/5 PASSED)
| Metric | Genuine Colab Execution Evidence |
|---|---|
| **Scenario Evaluated** | `scen_elig_01_exact_14d_boundary` (Exact 14-day refund boundary inquiry) |
| **Model** | `Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)` |
| **Hardware** | NVIDIA Tesla T4 GPU (16GB VRAM, `float16` precision) |
| **Execution Duration** | **2225 ms** |
| **Token Consumption** | **767 prompt tokens**, **70 completion tokens** (837 total) |
| **Tool Execution** | `check_refund_eligibility({"order_id": "ord_elig_01"})` $\to$ returned `eligible=True`, `max_refundable_cents=6000` |
| **Safety Invariant** | Agent executed zero unauthorized write calls (`request_refund` was never called) |
| **Database State** | Exactly 0 refund mutations occurred; customer order remained untouched |
| **Historical Run** | `colab_single_20261111_105817_4c22cb` (Preserved intact with original legacy check results) |
| **Audited Revision** | `ev_rev_eb2ddd6d5ea3` (**5/5 PASSED** under `read_only_inquiry` contract) |

### Case Study 2: Autonomous Travel Planner — Integrity & Failure Detection (3/6 FAILED)
A defining feature of EvalNexus is its **evaluation integrity**: unlike naive evaluators that award passes simply because tools were invoked, EvalNexus strictly verifies whether the agent successfully concluded the task.
| Metric | Genuine Colab Execution Evidence |
|---|---|
| **Scenario Evaluated** | `generic_travel_planner` (Multi-turn Kyoto itinerary with weather & attractions) |
| **Model** | `Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)` |
| **Hardware** | NVIDIA Tesla T4 GPU (16GB VRAM, `float16` precision) |
| **Execution Duration** | **44,238 ms** |
| **Tool Invocations** | Called `check_weather` (1x) and `lookup_poi` (4x) correctly |
| **Prohibited Tool** | Correctly never called prohibited `unauthorized_booking` |
| **Integrity Verdict** | **FAILED (3/6 Assertions Passed, 50.0%)** |
| **Root Cause Detected** | Model reached turn limit (`4/4`) without emitting a standalone final itinerary JSON; last output was an unresolved `<tool_call>` block |
| **Platform Behavior** | Correctly failed `json_schema`, `json_path_equals`, and `execution_completed` assertions instead of falsely rewarding tool invocation |
| **Historical Run** | `colab_generic_travel_20261112_065358_8af322` (Audited in-place repair) |

---

## 7. Visual Showcase (Dashboard Screenshots)

### System Overview Dashboard
Live reliability scorecards, provider distribution, completion rate, and recent run history.
![System Overview](docs/reports/screenshots/32_evalnexus_dashboard_overview.png)

### Test Studio & Audited Revision Banner
Visualizing scenario checks, the original legacy status, and the green auditable evaluation revision banner.
![Test Studio Checks & Revision Banner](docs/reports/screenshots/33_evalnexus_colab_run_studio_checks.png)

### Interactive Trace Timeline
Sequential trace explorer displaying user prompts, tool calls (`check_refund_eligibility`), tool outputs, and model reasoning.
![Interactive Trace Timeline](docs/reports/screenshots/34_evalnexus_colab_trace_timeline.png)

### Chaos Fault Lab
Injecting network latency, database timeouts, and transient HTTP 500 errors to stress-test agent recovery.
![Chaos Fault Lab](docs/reports/screenshots/30_chaos_fault_lab.png)

### Automated Quality Gates
Enforcing enterprise release criteria (pass rate $\ge 90\%$, security leaks = 0, p90 latency $\le 5000\text{ms}$).
![Quality Gates](docs/reports/screenshots/31_automated_quality_gates.png)

---

## 8. Quickstart & Local Installation

### Prerequisites
* Python 3.11, 3.12, or 3.13
* Git

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/EvalNexus.git
cd EvalNexus

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser dependencies (for UI tests)
playwright install chromium
```

### Running Locally (Windows PowerShell)

```powershell
# Set environment
$env:DATABASE_URL = 'sqlite:///./agent_wind_tunnel.db'
$env:AWT_EMBEDDED_WORKER = '1'
$env:AWT_REQUIRE_AUTH = '0'

# Start the application server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

Open **`http://127.0.0.1:8001/`** in your browser to view the interactive dashboard.
* Health Check: `http://127.0.0.1:8001/healthz`
* Database Readiness: `http://127.0.0.1:8001/readyz`

### Running via Docker Compose

```bash
docker compose up --build
```

---

## 9. Running Evaluations & Automated Tests

### 1. Run the Full Test Suite (195 Automated Tests)
```bash
python -m pytest tests/ -v
```
All **195 tests pass cleanly** (194 pytest regression tests + 1 Playwright E2E test) with zero deprecation warnings and zero failures.

### 2. Run Focused Generic & Integrity Evaluator Tests
```bash
python -m pytest tests/test_generic_integrity.py tests/test_qwen_travel_contract.py tests/test_generic_evaluator.py -v
```
Verifies fail-closed final answer validation, collision-free trace ID generation, turn-limit enforcement, and all 6 atomic rollback failure-injection tests.

### 3. Run Deterministic Mock Benchmark
You can execute a complete 30-scenario benchmark suite locally with zero API costs:
* Navigate to **Test Studio** in the dashboard (`http://127.0.0.1:8001/#test-studio`).
* Select **`agent_v1_baseline`**, Engine: **`mock`**, click **Queue Benchmark Run**.
* The embedded worker processes all 30 scenarios in ~4 seconds and displays check results.

---

## 10. Optional Google Colab Pro + Qwen Workflow

EvalNexus includes a verified notebook ([`EvalNexus_Colab_LLM.ipynb`](EvalNexus_Colab_LLM.ipynb)) to evaluate open-source models on cloud GPUs without paid APIs:

```
┌──────────────────┐       1. Export Scenario Bundle       ┌─────────────────────┐
│    EvalNexus     │──────────────────────────────────────>│    Google Drive     │
│   FastAPI App    │                                       │ (Persistent Storage)│
└──────────────────┘                                       └──────────┬──────────┘
         ▲                                                            │
         │         3. Import Execution Results                        │ 2. Load Fixtures
         │            (Traces, Tokens, Latency)                       ▼
         │                                                 ┌─────────────────────┐
         └─────────────────────────────────────────────────│ Google Colab Pro T4 │
                                                           │ (Qwen2.5 Inference) │
                                                           └─────────────────────┘
```

1. **Export Scenarios Bundle:**
   ```bash
   curl -X POST http://127.0.0.1:8001/api/scenarios/bundle/export \
     -H "Content-Type: application/json" \
     -d '{"read_only": true, "scenario_ids": ["scen_elig_01_exact_14d_boundary"]}' \
     -o single_scenario_bundle.json
   ```
2. **Execute in Google Colab Pro:**
   * Open `EvalNexus_Colab_LLM.ipynb` in Colab.
   * Attach GPU runtime (T4 recommended).
   * Execute Step 9 (Batch Evaluation) targeting `single_scenario_bundle.json`.
   * Outputs `evalnexus_single_scenario_result.json` to Google Drive.
3. **Import Results into EvalNexus:**
   ```bash
   curl -X POST http://127.0.0.1:8001/api/runs/import-colab \
     -H "Content-Type: application/json" \
     -d @evalnexus_single_scenario_result.json
   ```
4. **Inspect in Dashboard:** View traces, model outputs, and assertion checks in Test Studio.

---

## 11. Known Limitations & Verification Scope

* **Colab Notebook Execution:** While scenario export and result import are automated REST endpoints, running model inference in Google Colab currently requires running the notebook cells in the Colab Pro UI.
* **Local In-Memory Rate Limiting:** The default rate limiter uses an in-memory sliding-window algorithm suitable for single-node deployments. Multi-node cloud deployments should back this with Redis.
* **GPU Memory Constraints:** The default Colab setup targets 1.5B to 7B parameter models using `float16` precision on 16GB Tesla T4 GPUs. Larger models require 4-bit quantization or A100/H100 compute.
* **Verification Nuance (Backend API vs. Visual Browser):** Platform test suites verify all backend database mutations, business logic, and API serialization (`list_runs`, `get_run_details`) deterministically. While Playwright E2E verifies core browser sections, running the full interactive SPA locally via `uvicorn backend.main:app` is recommended for visual styling and client-side inspection.

---

## 12. License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
