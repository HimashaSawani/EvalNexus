# AgentWindTunnel V2 — Advanced Evaluation & Platform Architecture Report

**Engineering Role:** Senior AI Platform Architect, Security Engineer, DevOps Engineer, QA Automation Lead  
**Platform Version:** AgentWindTunnel 2.0 (Enterprise Hardened)  
**Report Date:** 2026-10-31  
**Repository State:** 99 passing automated tests (100% pass rate, 0 failures, 0 warnings)

---

## 1. Executive Summary

AgentWindTunnel V2 has evolved from an e-commerce refund evaluation harness into a modular, production-hardened **AI Agent Reliability Testing Platform**.

The platform now enables enterprise teams and developers to:
1. **Evaluate Custom AI Agents Over HTTP**: Register and benchmark external agents using authenticated, schema-validated HTTP endpoints without executing arbitrary code.
2. **Author and Version Custom Scenarios**: Define user-controlled scenarios with custom domain states, injected faults, and expected assertions via a secure builder with complete JSON import/export and path-traversal prevention.
3. **Automate Behavioral Regression Testing**: Compare baseline vs candidate agent runs, detect behavioral drift in tool-call sequences, evaluate latency percentiles ($p50$/$p90$), and compute token/cost deltas with explicit disclaimers and statistical sample-size safeguards.
4. **Drill Down Into Root-Cause Failures**: Categorize failures cleanly into Behavioral Policy Violations, Operational Limits Exceeded, and Provider Transport Errors.
5. **Enforce Multi-Process Safety and Security**: Enforce DB-backed paid provider concurrency limits across multiple worker processes, SSRF link-local and cloud metadata protections, sliding-window rate limiting, and configurable API authentication.

---

## 2. Implemented Features & Architecture

### A. Custom Agent HTTP Adapter (`backend/agent/custom_adapter.py`)
- **Adapter Interface**: Implements `BaseLLMProvider` via `CustomHTTPAgentProvider`.
- **Zero Arbitrary Code Execution**: Custom agents communicate exclusively over HTTP/HTTPS with strict Pydantic payload serialization.
- **Request/Response Validation**: Validates `CustomAgentRequestPayload` (messages, tool specifications, execution limits) and `CustomAgentResponsePayload` (assistant content, tool calls with structured JSON arguments).
- **Outbound Network Security & SSRF Protection**:
  - Validates protocol scheme (`http://` or `https://`).
  - Blocks cloud provider metadata endpoints (`169.254.169.254`, `metadata.google.internal`, `instance-data`).
  - Blocks link-local ranges (`169.254.0.0/16`, `fe80::/10`).
  - Configurable `AWT_BLOCK_INTERNAL_NETWORKS=1` for production deployments to block private RFC1918 subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
- **Safe Authentication**: Supports custom header names (e.g., `Authorization: Bearer <token>` or `X-API-Key`). Tokens are masked in registry displays (`tok_***123`) and never leaked in logs.
- **Timeout & Resilience**: Configurable HTTP timeout (default 15s, max 60s) with clean timeout error classification.

### B. Custom Scenario Builder & Storage (`backend/scenarios/custom_scenario_service.py`)
- **Structured Definitions**: Pydantic schema `CustomScenarioPayload` validates customer identity, order history, injected faults, and expected evaluator assertions.
- **Path Traversal Protection**: Scenario IDs strictly enforce `^[a-zA-Z0-9_\-]+$`. Any directory traversal sequence (`..`, `/`, `\`) is rejected.
- **Dual Persistence**: Saves to SQLite/PostgreSQL `custom_scenarios` table and exports to `scenarios/custom/{id}.json` for immediate compatibility with background workers and synchronous runners.
- **Versioning**: Automatic version increments on updates.
- **Import / Export**: Full JSON export and validation-checked JSON import.

### C. Automated Regression Comparator (`backend/runner/regression_comparator.py`)
- **Behavioral Comparison**: Tracks tool call sequences per scenario (e.g., `[get_order] -> [check_refund_eligibility] -> [request_refund]`). Flags changes in tool sequence or argument parameters.
- **Status Classification**: Classifies every scenario as:
  - `REGRESSION`: Baseline PASSED, Candidate FAILED or PROVIDER_ERROR.
  - `IMPROVEMENT`: Baseline FAILED, Candidate PASSED.
  - `PARITY`: Baseline and Candidate have identical status.
- **Overall Verdict**: Computes `REGRESSION_DETECTED`, `IMPROVED`, `PARITY`, or `NEUTRAL`.
- **Latency Percentiles**: Computes $p50$ and $p90$ execution durations and deltas.
- **Cost Approximation with Disclaimer**: Calculates token usage and estimated cost deltas with the explicit disclaimer:
  > *"Estimated model costs are heuristic approximations based on published token pricing and do not represent guaranteed provider invoice amounts."*
- **Small-Sample Notice**: Explicitly flags benchmark sample size when $N < 10$:
  > *"INSUFFICIENT_SAMPLE_SIZE (N < 10; observational only, do not claim statistical reliability)"*.

### D. Advanced Studio Dashboard (`backend/static/index.html`)
- **Preserved Existing 7 Sections**: System Overview, Test Studio, Scenarios Catalog, Agent Versions, Run History, Comparisons, Settings & Safety.
- **Added 4 New Advanced Panels**:
  1. **Custom Agent Registry (`#view-custom-agents`)**: Form to register HTTP agents, masked token management, table of active external agents, live ping probe with latency and response preview.
  2. **Scenario Builder (`#view-scenario-builder`)**: Form controls, quick templates (Eligible, Expired, Injected Fault), dual-synced JSON editor, schema validation, export/import buttons, saved catalog table.
  3. **Regression Testing & Scorecards (`#view-regression-testing`)**: Run selector dropdowns, scorecards with verdict badges, pass-rate delta, latency deltas, cost delta, sample size warnings, and detailed behavioral scenario table.
  4. **Failure Analysis (`#view-failure-analysis`)**: Category metric cards (Behavioral Policy, Operational Limits, Provider Errors), filterable failure log table with evaluator evidence.

---

## 3. Multi-Process Concurrency & Database Safety

- **Atomic Job Claiming**: `QueueWorker.claim_next_job` implements atomic database updates (`UPDATE queue_jobs SET status='RUNNING' WHERE id=? AND status='QUEUED'`).
- **Multi-Process Paid Concurrency Enforcement**: Querying running jobs in the database (`QueueJob.is_paid == 1, QueueJob.status == 'RUNNING'`) guarantees that regardless of how many Uvicorn worker processes or standalone worker daemons are started, paid external provider limits (`AWT_MAX_CONCURRENT_PAID_JOBS`) are strictly enforced at the database level.
- **Non-Replay of Paid Executions**: Abandoned or crashed jobs with `is_paid == 1` are permanently marked `FAILED` with an audit message and are never automatically retried, preventing duplicate external billing.
- **Idempotency Protection**: Financial state operations reject conflicting payloads using stable operation keys.

