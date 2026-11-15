# EvalNexus V4 — Comprehensive UI/UX Architecture Audit & Design System Blueprint

**Document ID:** `EVALNEXUS-V4-UIUX-AUDIT-2026-11-14`  
**Platform:** EvalNexus V4 (Reliability Engineering & Evaluation Platform for Autonomous AI Agents)  
**Author:** Senior Enterprise UX Architect, AI Platform Product Designer, Frontend Architecture Auditor  
**Date:** 2026-11-14  
**Audit Status:** COMPLETE — PLANNING & ARCHITECTURE AUDIT ONLY (NO CODE MODIFIED)  

---

## Executive Summary

EvalNexus V4 is a feature-rich, evidence-grounded evaluation platform for autonomous AI agents. Over four rapid iterations (V1 Deterministic Refund Harness $\to$ V2 Custom Agents & Regression $\to$ V3 Enterprise Workflows, Chaos Lab & Quality Gates $\to$ V4 Generic AI Agent Evaluation & Real Qwen Inference), the platform backend and database have achieved enterprise-grade maturity with 204 passing regression and browser tests.

However, frontend presentation currently resides in a single monolithic 4,800-line single-page template (`backend/static/index.html`). Because features were added iteratively across development cycles, the user interface currently exhibits severe **information density challenges, visual fragmentation, navigational sprawl, and disjointed user workflows**.

This document presents a comprehensive, forensic architectural audit of every existing user-facing feature across the 16 dashboard panels, identifies 18 systemic UX failure modes, designs 3 distinct user persona journey paths, proposes a streamlined 5-domain navigation taxonomy, designs an executive-grade Overview Dashboard and a 5-step Test Studio workflow, defines a modern design system inspired by top AI infrastructure platforms (Linear, LangSmith, Grafana), and provides a zero-risk compatibility-preserving implementation strategy.

---

## Phase 1: Complete Functional Inventory

The dashboard currently serves **16 distinct panels** driven by 73 JavaScript controller functions and 58 backend API endpoints. Below is an exhaustive functional census of every feature in the codebase.

| # | Feature Name | Current Sidebar Location | Related Backend API | Current UI Functionality | Actively Used? | Retain in UI? | Recommended Future Location |
| :- | :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| **1** | System Overview & KPIs | Top Group (`#nav-overview`) | `GET /api/overview/metrics` | 4 KPI summary cards, onboarding banner, 10-row recent run log table with status badges | **Yes** (Primary entry) | **Yes** | **OVERVIEW $\to$ Dashboard** |
| **2** | Test Studio | Top Group (`#nav-test-studio`) | `GET /api/models`, `GET /api/scenarios`, `POST /api/runs/queue`, `GET /api/runs/{id}`, `POST /api/runs/{id}/cancel` | Mode A (Demo) / Mode B (Custom Agent) toggle, provider/model/scenario selectors, run progress bar, 2-column layout with 5 detail tabs (Checks, Timeline, DB State, Final Answer, Raw JSON) | **Yes** (Core execution engine) | **Yes** | **EVALUATE $\to$ Test Studio** |
| **3** | Scenarios Catalog | Top Group (`#nav-scenarios`) | `GET /api/scenarios` | Searchable, filterable table of 35 built-in scenarios (Refund, Sentiment, Travel) with individual "Run in Studio" action buttons | **Yes** | **Yes** | **BUILD & CONFIGURE $\to$ Scenarios** |
| **4** | Agent Versions & Prompts | Top Group (`#nav-agent-versions`) | `GET /api/agent-versions` | Grid of system prompt cards (`agent_v1_baseline`, `agent_v2_strict_rules`, etc.) with description and safety invariants | **Yes** | **Yes** | **BUILD & CONFIGURE $\to$ Agents** (Unified view) |
| **5** | Run History & Evidence | Top Group (`#nav-run-history`) | `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/export`, `POST /api/runs/{id}/re-evaluate` | Paginated/scrollable audit log of historical runs with provider/status filters, export actions, and re-evaluation modal | **Yes** (Essential audit trail) | **Yes** | **ANALYZE $\to$ Run History** |
| **6** | Version Comparisons | Top Group (`#nav-comparisons`) | `GET /api/comparisons?run_a=&run_b=` | Side-by-side run comparison matrix comparing Pass Rate delta, Tool-call drift, and Latency delta between two selected runs | **Yes** | **Yes** | **ANALYZE $\to$ Comparisons** |
| **7** | Custom Agent Registry | Advanced V2 Suite (`#nav-custom-agents`) | `GET /api/custom-agents`, `POST /api/custom-agents`, `DELETE /api/custom-agents/{id}`, `POST /api/custom-agents/{id}/ping` | Agent registration form (URL, Bearer token, timeout), live ping testing with round-trip latency, SSRF warning, active agents list | **Yes** (Essential for external users) | **Yes** | **BUILD & CONFIGURE $\to$ Agents** (Primary tab) |
| **8** | Scenario Builder & Import | Advanced V2 Suite (`#nav-scenario-builder`) | `POST /api/scenarios/custom`, `GET /api/scenarios/custom`, `DELETE /api/scenarios/custom/{id}`, `POST /api/scenarios/custom/import` | Drag-and-drop JSON scenario import, 5 quick templates, interactive form with live JSON sync/preview, validation button, catalog save | **Yes** | **Yes** | **BUILD & CONFIGURE $\to$ Scenarios** (Builder sub-tab) |
| **9** | Regression Testing & Scorecards | Advanced V2 Suite (`#nav-regression-testing`) | `POST /api/regression/compare`, `GET /api/regression/report/{b}/{c}` | Baseline vs candidate run comparison, automated verdict pill (`REGRESSION_DETECTED`), latency $p50$/$p90$ deltas, tool drift breakdown | **Yes** | **Yes** | **EVALUATE $\to$ Regression Testing** |
| **10** | Failure Analysis & Triage | Advanced V2 Suite (`#nav-failure-analysis`) | Parsed from `GET /api/runs` and scenario runs | Category filter (Policy violations, missing answers, turn limits, schema errors), failure count cards, detailed forensic failure table | **Yes** | **Yes** | **ANALYZE $\to$ Failure Analysis** |
| **11** | Multi-Agent Workflows | V3 Enterprise Engine (`#nav-workflows`) | `POST /api/workflows`, `GET /api/workflows`, `POST /api/workflows/{id}/run`, `GET /api/workflows/runs/{run_id}` | DAG workflow JSON editor, sample template loaders, execution trace waterfall with inter-agent message passing, active workflows table | **Yes** | **Yes** | **ADVANCED $\to$ Multi-Agent Workflows** |
| **12** | Distributed Worker Nodes | V3 Enterprise Engine (`#nav-cluster-nodes`) | `GET /api/cluster/nodes`, `POST /api/cluster/nodes/register`, `POST /api/cluster/nodes/{id}/heartbeat`, `POST /api/cluster/reap` | Cluster concurrency table, worker heartbeat pulses, node capacity metrics, stale node reaper trigger | **Yes** | **Yes** | **ADVANCED $\to$ Distributed Workers** |
| **13** | Trace & Span Explorer | V3 Enterprise Engine (`#nav-trace-explorer`) | `GET /api/runs/{run_id}` (OTel trace extraction) | Run ID input, OpenTelemetry hierarchical waterfall span visualization, span attributes drawer, OTel JSON export | **Yes** | **Yes** | **ANALYZE $\to$ Traces** |
| **14** | Chaos Fault Lab | V3 Enterprise Engine (`#nav-fault-lab`) | Client-side fault orchestrator via `POST /api/runs/execute` | 12 fault modes (Timeout, DB Deadlock, 500 error, 429 rate limit, JSON corruption), call trigger, simulated delay, resilience scorecard | **Yes** | **Yes** | **ADVANCED $\to$ Chaos Testing** |
| **15** | CI/CD Quality Gates | V3 Enterprise Engine (`#nav-quality-gates`) | `POST /api/quality-gates/evaluate` | Gate policy rules configurator (min pass rate, max latency, forbidden tools, required checks), evaluate button, verdict badge, CLI command generator | **Yes** | **Yes** | **ADVANCED $\to$ Quality Gates** |
| **16** | Settings & Credential Safety | Bottom Sidebar (`#nav-settings`) | `GET /api/settings` | Masked credential safety audit (Gemini, OpenAI, Bearer), worker thread status, persistent queue depth, system execution bounds | **Yes** | **Yes** | **SYSTEM $\to$ Settings** |

---

## Phase 2: UI/UX Problem Analysis

An exhaustive audit of `backend/static/index.html` revealed 18 major UX friction points:

### 1. Sidebar Navigation Density & Cognitive Overload
* **Evidence:** The sidebar contains **16 primary navigation items** stacked vertically in a single column (`width: 250px`), broken only by two small arbitrary section dividers ("Advanced V2 Suite" and "V3 Enterprise Engine").
* **Impact:** Users suffer cognitive paralysis. Finding a specific feature (e.g. "Where do I see traces?" or "Where do I add my agent?") requires scanning 16 items. Navigation labels reflect engineering release phases ("V2", "V3") rather than user workflow mental models.

### 2. Information Hierarchy & Visual Clutter
* **Evidence:** Headers, badge pills, mode buttons, search filters, and nested tab panels compete simultaneously for user attention without a clear visual anchor.
* **Impact:** Key primary actions (such as "Execute Evaluation") carry visual weight identical to secondary auxiliary actions (such as "Export JSON" or "Sync Form $\to$ JSON").

### 3. Typography Inconsistencies
* **Evidence:** Hardcoded inline font sizes range erratically from `11px`, `11.5px`, `12px`, `12.5px`, `13px`, `13.5px`, `14px`, `15px`, `16px` up to `24px` with conflicting weights (`font-weight: 500`, `600`, `700`, `800`).
* **Impact:** Causes a "noisy", amateur aesthetic lacking the mathematical rhythm of high-end developer tools.

### 4. Color System Cohesion
* **Evidence:** The stylesheet defines standard variables (`--primary`, `--sidebar-bg`), but HTML elements frequently override them with hardcoded hex values (e.g. `#0EA5E9`, `#38BDF8`, `#64748B`, `#172554`, `#4F46E5`).
* **Impact:** Visual dissonance between muted slate backgrounds, vibrant sky blue accents, and dark indigo panels.

### 5. Card Layouts & Spacing
* **Evidence:** Cards use inconsistent paddings (`14px`, `18px`, `22px`, `24px`) and uneven borders (`1px solid var(--card-border)` mixed with `border: 1px solid rgba(255,255,255,0.05)`).
* **Impact:** Misaligned margins create visual instability across wide monitors.

### 6. KPI Presentation
* **Evidence:** Overview KPI cards use static text strings below numbers (e.g. `10 of 10 clean`, `30 Pass · 0 Fail`) without trend indicators, baseline comparisons, or visual sparklines.
* **Impact:** Users cannot quickly discern whether performance is improving or degrading over time.

### 7. Table Readability
* **Evidence:** Tables across Overview, Run History, and Scenarios have fixed column widths that truncate critical identifiers (like UUID run IDs or scenario titles) while leaving vast empty space in status columns.
* **Impact:** Horizontal scrolling and awkward ellipses hide actionable trace details.

### 8. Status Badges
* **Evidence:** Status badges (`PASSED`, `FAILED`, `COMPLETED`, `RUNNING`, `QUEUED`, `ONLINE`, `OFFLINE`) use varied casing, inconsistent border-radii (`4px` vs `12px` vs `9999px`), and conflicting color semantics (e.g. `COMPLETED` sometimes displays as blue, sometimes as green).
* **Impact:** Misleads users into confusing a successful evaluation execution (`COMPLETED`) with an agent passing its assertions (`PASSED`).

### 9. Form Usability
* **Evidence:** Forms in Custom Agent Registry and Scenario Builder lack inline field-level validation, helper tooltips, and clear required-field indicators.
* **Impact:** Submitting invalid URLs or malformed JSON produces generic error banners that force users to guess which input failed.

### 10. Test Studio Workflow Disconnect
* **Evidence:** Mode A (Demo) and Mode B (Evaluate My Own Agent) sit inside a small nested toggle above provider and suite selects. Custom Agent selection is detached from the scenario suite dropdown.
* **Impact:** First-time users often fail to realize they must select Mode B, configure an agent, and select custom scenarios before clicking "Run Tests".

### 11. Trace Visualization
* **Evidence:** The Trace Stepper tab displays raw JSON fragments and linear cards without distinct visual syntax differentiation between agent thoughts, tool arguments, database mutations, and final outputs.
* **Impact:** Forensic investigation of multi-turn tool loops requires tedious manual scrolling and JSON mental parsing.

### 12. Responsive Layout Failures
* **Evidence:** Media queries only trigger at `1024px` and `600px`. At standard 1366x768 or 1440x900 laptop resolutions, the 2-column Test Studio layout forces narrow columns where JSON payloads and assertion diffs wrap awkwardly.
* **Impact:** Poor developer experience on standard laptops.

### 13. Accessibility (a11y)
* **Evidence:** Low-contrast text (e.g. `#94A3B8` on white cards), missing `aria-labels` on icon-only buttons, and absence of visible keyboard `:focus-visible` rings on custom buttons.
* **Impact:** Fails WCAG 2.1 AA standards.

### 14. Mobile / Tablet Navigation
* **Evidence:** The sidebar hides off-canvas via `.mobile-open`, but the hamburger button lacks a clear visual touch target and the backdrop overlay fails to trap focus.
* **Impact:** Frustrating navigation on tablet touchscreens.

### 15. Empty States
* **Evidence:** When tables are empty (e.g. zero custom agents, zero runs), they render plain text like `No custom agents registered yet.` inside a table cell.
* **Impact:** Missed opportunity to provide a welcoming call-to-action (e.g. "Register your first agent in 30 seconds").

### 16. Error Messaging
* **Evidence:** Errors often alert via simple JavaScript `alert()` or small inline red text spans (`#customAgentSaveFeedback`) that disappear or go unnoticed.
* **Impact:** Silent failures when local servers or network timeouts occur.

### 17. Loading States
* **Evidence:** Polling runs displays a single spinner in a status pill. Tables render blank white space while fetching asynchronous data.
* **Impact:** Users perceive the UI as sluggish or frozen. Skeleton loaders are missing.

### 18. User Onboarding
* **Evidence:** The onboarding banner on the Overview panel is a large, static card that cannot be dismissed, permanently occupying 250px of vertical real estate even for veteran engineers.
* **Impact:** Clutters daily workflow for returning developers.

---

## Phase 3: User Personas & Journey Mapping

### Persona A: First-Time External Developer
* **Profile:** Sarah, AI Engineer who built an authenticated Customer Support Agent using LangChain/FastAPI. She wants to benchmark her agent's safety and tool reliability.
* **Entry Point:** Platform URL root (`/`).
* **Required Journey:**
  1. Lands on Overview $\to$ sees "Register Agent" CTA.
  2. Navigates to Custom Agents $\to$ registers `https://api.myagent.internal/v1/invocations` with Bearer token.
  3. Tests endpoint with single-click "Ping".
  4. Navigates to Test Studio $\to$ selects her agent $\to$ runs customer support scenarios $\to$ reviews pass/fail assertions.
* **Current Friction Points:**
  - Sidebar buries "Custom Agents" under "Advanced V2 Suite" at item #8.
  - Test Studio defaults to Mock Simulator (Mode A); Sarah doesn't realize her agent is under Mode B.
  - Unclear whether her agent needs refund tools or generic JSON outputs.
* **UX Improvements:**
  - Prominent "Register New Agent" primary CTA on Dashboard.
  - Guided 5-step wizard in Test Studio automatically selecting newly registered agents.

### Persona B: AI Platform Engineer Running Regression Tests
* **Profile:** Marcus, Senior ML Engineer deploying a prompt update to an existing agent version. He needs to verify that tool-calling accuracy has not degraded and latency remains under 800ms.
* **Entry Point:** Test Studio or Regression Testing.
* **Required Journey:**
  1. Executes evaluation on candidate model prompt $\to$ obtains Run ID.
  2. Navigates to Regression Testing $\to$ selects Baseline Run (v1.2) and Candidate Run (v1.3).
  3. Reviews Regression Scorecard: Pass Rate delta, behavioral drift matrix, $p90$ latency delta.
  4. Exports certified JSON regression report for CI/CD audit.
* **Current Friction Points:**
  - Marcus must remember Run IDs and manually pick them from long unstructured dropdown lists.
  - No one-click "Run Regression Against Baseline" shortcut directly from Test Studio.
* **UX Improvements:**
  - Auto-population of Candidate Run directly from the latest execution.
  - Dedicated "Set as Baseline" button in Run History.

### Persona C: QA Engineer Investigating Failures
* **Profile:** Priya, QA Automation Engineer diagnosing why an agent failed 2 out of 5 scenarios in a nightly test batch.
* **Entry Point:** Run History or Failure Analysis.
* **Required Journey:**
  1. Opens Run History $\to$ clicks failed run row (`3/5 PASSED`).
  2. Inspects Failed Scenario card in Test Studio $\to$ identifies failed assertion (`chk_status_planned` expected `PLANNED`, got `DRAFT`).
  3. Switches to Trace Stepper $\to$ inspects turn 3 LLM tool call.
  4. Switches to Database State $\to$ confirms missing write mutation.
  5. Exports forensic diagnostic report.
* **Current Friction Points:**
  - Test Studio right-column detail tabs require multiple clicks to correlate traces with database state.
  - Final answer text truncates JSON syntax errors.
* **UX Improvements:**
  - Unified Split-View forensic panel: Assertion Diagnostic on left, Synchronized Trace Event timeline on right.
  - Explicit highlight on the exact assertion failure trigger.

---

## Phase 4: Navigation Redesign Proposal

To eliminate cognitive overload, the **16 sidebar items are organized into 5 intuitive, workflow-aligned domains**. Every single implemented feature and API endpoint is preserved with zero feature loss.

```
┌────────────────────────────────────────────────────────┐
│                   EVALNEXUS V4                         │
│             Evaluate. Trace. Improve.                  │
├────────────────────────────────────────────────────────┤
│  OVERVIEW                                              │
│  ├── Dashboard                  [#nav-overview]        │
│                                                        │
│  BUILD & CONFIGURE                                     │
│  ├── Agents                     [#nav-custom-agents]   │
│  │   ├── Custom HTTP Agents     (Stage 2 Registry)     │
│  │   └── Agent Versions         (Prompts & Baselines)  │
│  └── Scenarios                  [#nav-scenarios]       │
│      ├── Scenarios Catalog      (Built-in Suite)       │
│      └── Scenario Builder       (Custom & Import)      │
│                                                        │
│  EVALUATE                                              │
│  ├── Test Studio                [#nav-test-studio]     │
│  └── Regression Testing         [#nav-regression-testing]│
│                                                        │
│  ANALYZE                                               │
│  ├── Run History                [#nav-run-history]     │
│  ├── Version Comparisons        [#nav-comparisons]     │
│  ├── Failure Analysis           [#nav-failure-analysis]│
│  └── Trace & Spans              [#nav-trace-explorer]  │
│                                                        │
│  ADVANCED                                              │
│  ├── Chaos Testing              [#nav-fault-lab]       │
│  ├── Quality Gates              [#nav-quality-gates]   │
│  ├── Multi-Agent Workflows      [#nav-workflows]       │
│  └── Distributed Workers        [#nav-cluster-nodes]   │
│                                                        │
│  SYSTEM                                                │
│  └── Settings & Safety          [#nav-settings]        │
└────────────────────────────────────────────────────────┘
```

### Feature Preservation Audit Matrix

| Proposed Navigation Item | Preserved Underlying Features & Existing Views | Existing IDs & Click Handlers Preserved |
| :--- | :--- | :--- |
| **OVERVIEW $\to$ Dashboard** | System KPIs, Recent executions table, Quick-start shortcuts | `#nav-overview`, `navigateView('overview')` |
| **BUILD $\to$ Agents** | Custom HTTP Agent Registration (`#view-custom-agents`), Agent Versions Grid (`#view-agent-versions`), Ping probes | `#nav-custom-agents`, `#nav-agent-versions`, `loadCustomAgents()`, `loadAgentVersions()` |
| **BUILD $\to$ Scenarios** | Scenarios Catalog table (`#view-scenarios`), Scenario Builder form & JSON preview (`#view-scenario-builder`), Template loaders | `#nav-scenarios`, `#nav-scenario-builder`, `loadScenariosCatalog()`, `loadScenarioBuilder()` |
| **EVALUATE $\to$ Test Studio** | Execution controls, Mode A/B switcher, Two-column execution layout, 5 Detail tabs | `#nav-test-studio`, `navigateView('test-studio')`, `switchDetailTab()` |
| **EVALUATE $\to$ Regression** | Baseline vs Candidate comparator (`#view-regression-testing`), Delta scorecards, JSON export | `#nav-regression-testing`, `loadRegressionView()`, `runRegressionComparison()` |
| **ANALYZE $\to$ Run History** | Historical runs table (`#view-run-history`), Run inspection modal, Re-evaluate trigger | `#nav-run-history`, `loadRunHistory()` |
| **ANALYZE $\to$ Comparisons** | Side-by-side run comparison matrix (`#view-comparisons`) | `#nav-comparisons`, `loadComparisonsList()`, `executeComparison()` |
| **ANALYZE $\to$ Failure Analysis**| Failure classification filters (`#view-failure-analysis`), Policy violation metrics, Root-cause table | `#nav-failure-analysis`, `loadFailureAnalysis()` |
| **ANALYZE $\to$ Trace & Spans** | OpenTelemetry span waterfall (`#view-trace-explorer`), OTel export | `#nav-trace-explorer`, `loadTraceExplorer()`, `inspectTraceWaterfall()` |
| **ADVANCED $\to$ Chaos Testing**| 12-mode fault injection lab (`#view-fault-lab`), Resilience scorecards | `#nav-fault-lab`, `loadFaultLab()`, `runChaosSimulation()` |
| **ADVANCED $\to$ Quality Gates**| CI/CD threshold policy rules (`#view-quality-gates`), CLI command generator | `#nav-quality-gates`, `loadQualityGates()`, `evaluateQualityGate()` |
| **ADVANCED $\to$ Workflows** | Multi-agent DAG execution runner (`#view-workflows`), Message waterfall | `#nav-workflows`, `loadWorkflows()`, `saveAndRunWorkflow()` |
| **ADVANCED $\to$ Workers** | Cluster concurrency table (`#view-cluster-nodes`), Node heartbeat, Reaper trigger | `#nav-cluster-nodes`, `loadClusterNodes()`, `triggerReapStaleNodes()` |
| **SYSTEM $\to$ Settings** | Secret-safe credential verification (`#view-settings`), Queue bounds, Worker health | `#nav-settings`, `loadSettings()` |

*Result:* **100% of all 16 existing views and 73 JavaScript controller functions remain active and directly accessible.**

---

## Phase 5: Overview Dashboard Architecture

The proposed Overview Dashboard is organized into four clean horizontal visual bands:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  HEADER: Product Title, Platform Tagline, Environment Badge                            │
│  [ Primary CTA: + New Evaluation ]      [ Secondary CTA: Register Agent ]              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  KPI ROW (4 Responsive Cards with Trend Sub-labels)                                    │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐   │
│  │ Total Benchmark  │ │ Behavioral Pass  │ │ Execution Rate   │ │ Average Latency  │   │
│  │ Runs: 127        │ │ Rate: 98.4%      │ │ (Completed): 100%│ │ (p50): 142ms     │   │
│  │ 24 Mock · 103 Real│ │ 0 Policy Breaches│ │ 127 of 127 Clean │ │ p90: 890ms       │   │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘ └──────────────────┘   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  MAIN CONTENT (Two-Column 65% / 35% Grid)                                              │
│  ┌──────────────────────────────────────────────┐ ┌────────────────────────────────┐   │
│  │ Recent Evaluations (Live Database Log)       │ │ Agent Performance & Safety     │   │
│  │ [Filter: All / Real / Mock]                  │ │ ------------------------------ │   │
│  │ Table: Run ID · Date · Agent · Provider ·    │ │ - agent_v1_baseline: 100% Pass │   │
│  │        Status · Score · Latency · Action     │ │ - fresh_user_support: 80% Pass │   │
│  │                                              │ │ - Qwen2.5-1.5B (Colab): 50%    │   │
│  │                                              │ │ Failure Category Breakdown     │   │
│  │                                              │ │ [Bar: 60% Schema, 40% Timeout] │   │
│  └──────────────────────────────────────────────┘ └────────────────────────────────┘   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│  SECONDARY CONTENT (Infrastructure Health Grid)                                        │
│  ┌────────────────────────┐ ┌────────────────────────┐ ┌───────────────────────────┐   │
│  │ System Health          │ │ Provider Status        │ │ Worker Engine             │   │
│  │ SQLite WAL: Connected  │ │ Gemini API: Configured │ │ Embedded Worker: Active   │   │
│  │ Schema Revision: v4.0  │ │ OpenAI API: Configured │ │ Queue Depth: 0 Pending    │   │
│  │ PRAGMA Integrity: ok   │ │ Custom HTTP: 1 Online  │ │ Concurrency: 1 Worker     │   │
│  └────────────────────────┘ └────────────────────────┘ └───────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Data Feasibility Matrix (No Invented Metrics)

| Displayed Metric | Source API Endpoint | Backend Data Field | Status |
| :--- | :--- | :--- | :---: |
| **Total Runs** | `GET /api/overview/metrics` | `data.total_runs`, `data.mock_runs`, `data.real_runs` | **Exists Today** |
| **Behavioral Pass Rate** | `GET /api/overview/metrics` | `data.behavioral_pass_rate` | **Exists Today** |
| **Execution Rate** | `GET /api/overview/metrics` | `data.completion_rate`, `data.completed_runs` | **Exists Today** |
| **Recent Runs Table** | `GET /api/overview/metrics` | `data.recent_runs` array (id, model, status, scenarios) | **Exists Today** |
| **Average Latency (p50/p90)**| `GET /api/runs` or `GET /api/regression/report` | Available in run execution payloads; simple aggregation helper in `/api/overview/metrics` recommended | **Data Exists in DB** |
| **Provider Status** | `GET /api/settings` | `data.credentials` masked status flags | **Exists Today** |
| **Worker Engine Health** | `GET /api/settings` | `data.worker_status`, `data.queue_depth` | **Exists Today** |
| **Database Integrity** | `GET /readyz` | `status: "ready", database: "connected"` | **Exists Today** |

---

## Phase 6: Test Studio UX Workflow

The Test Studio is the heart of the platform. We replace the cramped dual-mode controls with a structured **5-Step Evaluation Workflow Stepper**:

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  STEP 1: SELECT AGENT       STEP 2: SCENARIOS      STEP 3: LIMITS       STEP 4: RUN       STEP 5: REVIEW│
│  (●) Agent Selected         (●) 5 Scenarios        (●) Default Bounds   [ Run Tests ]     [ 5/5 PASSED ]│
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step User Experience

* **Step 1: Agent Selection & Provider Resolution**
  - Dropdown categorized into 3 clean groups:
    1. *Registered Custom HTTP Agents:* e.g. `fresh_user_support_agent` (shows live green `ONLINE` indicator).
    2. *Local Deterministic Mock Simulator:* e.g. `agent_v1_baseline` ($0.00 zero-cost).
    3. *Live Commercial Providers (API Key Required):* Google Gemini, OpenAI.
  - *Offline Note:* An informational card clarifies that **Google Colab Pro (Qwen2.5-1.5B)** evaluations operate via JSON Bundle Export/Import ([`EvalNexus_Colab_LLM.ipynb`](EvalNexus_Colab_LLM.ipynb)) and are not polled as continuous live HTTP endpoints.
* **Step 2: Scenario Selection**
  - Radio toggle between:
    - *Full Benchmark Suite (All Scenarios)*
    - *Category Batch:* e.g. Refund Invariants, Sentiment Analysis, Autonomous Travel Planner.
    - *Single Targeted Scenario:* Instant search filter across all 35 built-in and custom scenarios.
* **Step 3: Execution Bounds & Invariants**
  - Collapsible drawer revealing execution guardrails:
    - Max Turns Budget (Default: 4 turns)
    - Scenario Timeout (Default: 20.0s)
    - Token Budget (Default: 5,000 tokens)
    - Dual Contract Enforcement (`FULL_MUTATION` vs `READ_ONLY_INQUIRY`)
* **Step 4: Live Execution Stepper**
  - Primary button: `[ 🚀 Execute Evaluation Run ]` (with cancel button `[ ✕ Cancel ]`).
  - Progress bar updating per completed scenario.
  - Scenario checklist on left column showing real-time state transitions: `QUEUED` $\to$ `RUNNING` $\to$ `PASSED` / `FAILED`.
* **Step 5: Synchronized Forensic Results Panel**
  - Two synchronized panels:
    - *Top / Left:* **Assertion Verification Matrix** showing each assertion type (`json_schema`, `tool_called`, `tool_not_called`, `execution_completed`), target parameter, expected value, actual evaluated value, and diagnostic rationale.
    - *Bottom / Right:* **Structured Timeline** separating Turn 1 $\to$ Tool Invocation $\to$ Synthetic Tool Return $\to$ Final Agent Answer with formatted JSON syntax highlighting.

---

## Phase 7: Industrial Design System

Inspired by elite developer tools (**Linear, LangSmith, Grafana, Weights & Biases**), the design system emphasizes clarity, low visual fatigue, high contrast, and dense technical readability.

### 1. Color Palette

```css
:root {
  /* Slate Neutral Foundation (Linear Dark-Slate Vibe) */
  --color-bg-canvas: #0B0F17;        /* Ultra-dark workspace canvas */
  --color-bg-surface: #111827;       /* Card & panel surface */
  --color-bg-surface-elevated: #1F2937; /* Elevated dropdowns & modals */
  --color-border-subtle: #1F2937;    /* Subtle structural borders */
  --color-border-default: #374151;   /* Card & input borders */
  
  /* Text Typography Colors */
  --color-text-primary: #F9FAFB;     /* High-contrast headers & active values */
  --color-text-secondary: #9CA3AF;   /* Body text & labels */
  --color-text-muted: #6B7280;       /* Metadata, timestamps, placeholders */
  
  /* Brand Accent (Electric Blue / Indigo) */
  --color-accent-primary: #3B82F6;   /* Primary actions & active tabs */
  --color-accent-hover: #2563EB;     /* Hover state */
  --color-accent-subtle: rgba(59, 130, 246, 0.12); /* Selected row highlight */
  
  /* Strict Semantic Status Tokens */
  --color-status-pass-bg: rgba(16, 185, 129, 0.12);
  --color-status-pass-text: #34D399;   /* Crisp Emerald Green */
  --color-status-pass-border: rgba(16, 185, 129, 0.3);
  
  --color-status-fail-bg: rgba(239, 68, 68, 0.12);
  --color-status-fail-text: #F87171;   /* High-visibility Coral Red */
  --color-status-fail-border: rgba(239, 68, 68, 0.3);
  
  --color-status-warn-bg: rgba(245, 158, 11, 0.12);
  --color-status-warn-text: #FBBF24;   /* Amber Warning */
  --color-status-warn-border: rgba(245, 158, 11, 0.3);
  
  --color-status-info-bg: rgba(59, 130, 246, 0.12);
  --color-status-info-text: #60A5FA;   /* Information Blue */
  --color-status-info-border: rgba(59, 130, 246, 0.3);
}
```

### 2. Typography Scale

* **Primary Font:** `'Inter'`, system-ui, sans-serif (Clean UI labels and metrics).
* **Code & Trace Font:** `'JetBrains Mono'`, monospace (JSON payloads, trace IDs, tool parameters).

| Role | Font Size | Line Height | Weight | Letter Spacing |
| :--- | :---: | :---: | :---: | :---: |
| **Display H1** | 22px | 28px | 700 (Bold) | -0.4px |
| **Section H2** | 16px | 22px | 600 (Semi-bold)| -0.2px |
| **Card Header H3** | 14px | 20px | 600 (Semi-bold)| 0px |
| **Body Regular** | 13.5px | 20px | 400 (Regular) | 0px |
| **Body Medium** | 13.5px | 20px | 500 (Medium) | 0px |
| **Label / Caption** | 11.5px | 16px | 600 (Semi-bold)| +0.3px (Uppercase) |
| **Code / Traces** | 12px | 18px | 500 (Mono) | 0px |

### 3. Button Hierarchy & Interactive States

1. **Primary Action (`.btn-primary`):** Solid `--color-accent-primary` (#3B82F6), white text, bold font, subtle glow shadow. Max 1 primary button per visual region.
2. **Secondary Action (`.btn-secondary`):** Dark surface background, subtle border, secondary text color, transitions to primary text on hover.
3. **Ghost Action (`.btn-ghost`):** Borderless, transparent background, used for refresh icons, copy buttons, and table row actions.
4. **Destructive Action (`.btn-danger`):** Red tinted background (`rgba(239, 68, 68, 0.12)`), red border, used for cancel run or delete agent actions.

---

## Phase 8: Implementation Safety & Compatibility Preservation

Because the frontend is tested by Playwright and browser regression suites, any UI modernization must adhere to strict **zero-breakage contracts**:

### 1. Element ID Immutability Contract
All element IDs checked by `tests/test_playwright_e2e_sections.py` and referenced by JavaScript controller functions **must be preserved exactly**:
* `#ovTotalRuns`, `#ovRecentTbody`, `#ovBehavioralRate`, `#ovCompletionRate`
* `#providerSelect`, `#modelSelect`, `#suiteSelect`, `#btnRunTests`, `#btnCancelRun`
* `#tabBtn-checks`, `#tabBtn-timeline`, `#tabBtn-db`, `#tabBtn-answer`, `#tabBtn-raw`
* `#customAgentUrl`, `#btnSaveCustomAgent`, `#customAgentSaveFeedback`
* `#scenBuilderId`, `#btnSaveScenario`, `#scenBuilderStatus`
* `#regBaselineSelect`, `#btnRunRegression`
* `#faCategoryFilter`, `#faPolicyCount`
* `#wfDefinitionJson`, `#btnSaveAndRunWf`, `#wfMetricCount`
* `#clusterNodesTbody`, `#clusterActiveNodes`
* `#traceInputId`, `#traceWaterfallContainer`
* `#faultModeSelect`, `#faultResilienceScore`
* `#gateMinPassRate`, `#gateVerdictBadge`

### 2. URL Hash-Routing Compatibility
The hash-based routing mechanism (`#overview`, `#test-studio`, `#custom-agents`, etc.) and `navigateView(viewId)` must remain the underlying routing protocol so that bookmarks, direct links, and Playwright tests continue navigating seamlessly.

### 3. Non-Destructive Phased Migration Strategy
* **Phase A (CSS & Token Modernization):** Update CSS design tokens (`var(--bg)`, typography, buttons, tables) without moving any HTML elements. Re-run Playwright suite.
* **Phase B (Navigation Hierarchy Grouping):** Introduce accordion/group styling into the sidebar while keeping the existing `id="nav-*"` elements functional. Re-run Playwright suite.
* **Phase C (Overview Dashboard Modernization):** Reorganize the top overview cards and recent table layout. Re-run Playwright suite.
* **Phase D (Test Studio Stepper Enhancement):** Wrap the existing Test Studio controls in the 5-step visual stepper while maintaining all underlying select and button IDs. Re-run Playwright suite.

---

## Phase 9: Implementation Priorities, Risks & Verification Plan

### Recommended Implementation Roadmap

| Priority | Step / Deliverable | Objective | Verification Gate |
| :---: | :--- | :--- | :--- |
| **P1** | **Design Token Foundation** | Establish modern slate color tokens, typography scale, and button classes in `index.html` style block | Visual sanity check; zero test regressions |
| **P2** | **Navigation Sidebar Modernization** | Group the 16 sidebar items into the 5 proposed domains with clean chevron toggles | Playwright 16-section navigation test passes 100% |
| **P3** | **Executive Overview Dashboard** | Redesign Overview KPI row, system health cards, and recent executions table | Overview test passes; `loadOverviewMetrics()` verified |
| **P4** | **Test Studio 5-Step Stepper** | Streamline agent, scenario, and limit selectors into the guided stepper layout | Test Studio run execution test passes 100% |
| **P5** | **Forensic Trace & Check Cards** | Enhance Check Result cards with clear expected vs actual diffs and colored timeline stepper | Playwright assertion inspection verified |

### Key Risks & Dependencies

1. **Risk:** Renaming or removing an element ID breaks Playwright E2E tests.  
   *Mitigation:* Element ID immutability contract strictly enforced; automated test runs after each phase.
2. **Risk:** CSS changes alter dropdown options or modal positions.  
   *Mitigation:* Keep native HTML select and input structures; apply modern styling via CSS wrapper classes.
3. **Risk:** Offline Colab inference confused with live API.  
   *Mitigation:* Prominent informational badge and tooltip explaining the Google Drive bundle workflow.

---

## Final Instruction & Status

$$\mathbf{AUDIT\ STATUS:}\quad \mathbf{COMPLETE}$$

**NO FILES HAVE BEEN MODIFIED.**  
**NO CODE CHANGES HAVE BEEN IMPLEMENTED.**  

This architecture blueprint is submitted for review and approval before any frontend modifications proceed.
