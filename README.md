# 🌪️ AgentWindTunnel

> **Automated Reliability, Compliance, and Fault-Injection Benchmarking Platform for AI Agents.**

AgentWindTunnel is an open-source evaluation and stress-testing platform ("wind tunnel") for AI agents. Just as physical wind tunnels test aircraft aerodynamics under extreme turbulence, AgentWindTunnel subjects AI customer support agents to deterministic edge cases, system faults (network timeouts, transient 503s, stale reads), and security policies before production release.

---

## ⚡ Core Capabilities

1. **Deterministic Business Simulation**:
   - E-commerce refund support tools: `get_order`, `check_refund_eligibility`, `request_refund`.
   - Fixed scenario clocks to eliminate temporal flakiness.
   - Session-bound customer ownership enforcement (403 Forbidden on cross-account leaks).
   - Database constraints ensuring idempotent operations and zero double refunds.

2. **Step 10 Synthetic Fault Injector**:
   - `TIMEOUT_BEFORE_WRITE`: Tool network timeout before any mutation.
   - `TIMEOUT_AFTER_WRITE`: DB commit succeeds, but upstream connection drops (504).
   - `TEMPORARY_UNAVAILABLE`: Transient 503 failure requiring retry.
   - `STALE_READ`: Outdated state / cache hit.
   - `MALFORMED_RESPONSE`: Missing schema keys or corrupted payloads.

3. **Autonomous Agent Loop & Multi-Turn Reasoning (Step 8)**:
   - Tool-calling loop with strict operational limits (turns, calls, timeouts, token budgets).
   - Zero-cost, 100% reproducible offline simulator engine (`MockToolCallingProvider`).
   - Real OpenAI / Google Gemini API support (`RealOpenAIProvider`).

4. **Version A vs Version B Benchmarking (Step 12)**:
   - **Version A (Baseline)**: Basic tool-calling prompt.
   - **Version B (Robust Compliant)**: Policy and fault-aware prompt with idempotency communication.

5. **Deterministic Evaluator (Step 9)**:
   - `OWNERSHIP`: Zero cross-account data leakage.
   - `ELIGIBILITY`: Respects 14-day delivery return window & cancelled status.
   - `DUPLICATE`: Prevents multiple refund records.
   - `STATE`: Exact matching of final amounts and refund lifecycle stages.
   - `COMPLETION`: Clean termination within limits.

6. **Interactive Web Benchmark Dashboard (Step 13)**:
   - Studio for executing benchmarks directly in the browser.
   - Live assertion pass/fail badges and timeline trace inspector.
   - Version A vs Version B comparison matrix.

---

## 🚀 Quickstart Guide

### 1. Launch the Interactive Web Dashboard
```bash
uvicorn backend.main:app --reload --port 8000
```
Open your browser at **[http://localhost:8000](http://localhost:8000)**.
- Interactive Dashboard: `http://localhost:8000/`
- API Health Check: `http://localhost:8000/health`
- Swagger OpenAPI Docs: `http://localhost:8000/docs`

---

### 2. Run Terminal CLI Benchmarks

#### Run an Eligible Order Refund (Version B):
```bash
python -m backend.cli_runner scenarios/eligible_refund_scenario.json --agent agent_v2_improved
```

#### Run an Ineligible Expired Order Refund:
```bash
python -m backend.cli_runner scenarios/ineligible_expired_scenario.json --agent agent_v1_baseline
```

#### Run a Fault Injection Scenario (Timeout After Write):
```bash
# Compare Version A vs Version B under network drop:
python -m backend.cli_runner scenarios/fault_timeout_after_write.json --agent agent_v1_baseline
python -m backend.cli_runner scenarios/fault_timeout_after_write.json --agent agent_v2_improved
```

---

### 3. Run Automated Pytest Suite
```bash
python -m pytest -v
```

---

## 📂 Repository Layout

```
AgentWindTunnel/
├── backend/
│   ├── agent/
│   │   ├── agent_loop.py        # Multi-turn execution loop & budget limiter
│   │   ├── provider.py          # Mock Simulator & Real OpenAI/Gemini providers
│   │   └── tools_schema.py      # OpenAI-compliant function definitions & validators
│   ├── database/
│   │   ├── connection.py        # SQLAlchemy engine & session factory
│   │   └── models.py            # Business + Testing platform schemas
│   ├── domain/
│   │   └── refund_service.py    # Mock shop backend & 3 core tools
│   ├── faults/
│   │   └── fault_injector.py    # 5 deterministic synthetic fault modes
│   ├── runner/
│   │   ├── agent_runner.py      # WindTunnel autonomous agent runner
│   │   ├── evaluator.py         # 5 deterministic objective checks
│   │   ├── scripted_runner.py   # Deterministic scripted runner
│   │   └── trace_logger.py      # Sequential audit event recorder
│   ├── static/
│   │   └── index.html           # Dark-theme interactive web dashboard
│   ├── cli_runner.py            # Terminal scenario execution CLI
│   └── main.py                  # FastAPI server & REST API
├── docs/
│   ├── SCOPE.md                 # 1-page V1 Scope definition
│   └── RULES.md                 # Business policy & edge case matrix
├── scenarios/
│   ├── eligible_refund_scenario.json
│   ├── ineligible_expired_scenario.json
│   ├── fault_timeout_after_write.json
│   └── fault_temporary_unavailable.json
├── tests/
│   ├── test_agent_runner.py     # Agent reasoning & fault injection tests
│   ├── test_api.py              # Web API & dashboard route tests
│   ├── test_refund_service.py   # Domain policy & edge case unit tests
│   └── test_scripted_runner.py  # Scripted baseline tests
├── .env.example
└── README.md
```
