# EvalNexus: AI Agent Evaluation and Reliability Platform

## Step 1: Project Scope & Specification

### Overview
EvalNexus is an AI Agent Evaluation and Reliability Platform that helps engineers benchmark agents, inspect execution traces, compare versions, test failure scenarios, and evaluate reliability before deployment. It subjects AI agents to deterministic edge cases, system faults (timeouts, stale reads, network partitions), and security assertions before they reach production.

### Initial Release (V1) Scope: E-Commerce Refund Support Agent
The initial release targets a dedicated, high-risk e-commerce customer support use-case: **Order Refund Evaluation and Processing**.

#### In-Scope (V1)
1. **Core Agent Tools (3 Tools Only)**:
   - `get_order(order_id)`: Fetches order status, line items, amounts, and delivery timestamps. Customer identity is bound strictly from the authenticated session context (session isolation).
   - `check_refund_eligibility(order_id)`: Applies deterministic store policies against a fixed scenario clock to evaluate if a refund is permitted.
   - `request_refund(order_id, amount, operation_key)`: Initiates a refund request idempotently with database-level uniqueness constraints.
2. **Deterministic Evaluation Framework**:
   - Automated assertions on Ownership, Eligibility, Duplicate Protection, Database State, and Execution Limits.
3. **Execution Trace Logging**:
   - Sequential audit logs of all tool inputs, outputs, timestamps, durations, and state transitions.
4. **Fault Injection**:
   - Synthetic timeouts (before/after write), stale reads, malformed responses, and temporary failures.
5. **Dashboard & Web Runner**:
   - Runs overview, version comparison (Baseline Prompt vs Robust Agent), scenario drilldown, and trace inspector.

#### Explicitly Out-of-Scope (V1)
- Browser automation / GUI clicking.
- Voice / audio agents.
- Real payment gateway API integration (all financial mutations run in isolated sandboxed DB sessions).
- External agent interconnects / multi-agent negotiation.
- Partial line-item refunds (V1 supports full order refund only).

### Success Metric
A single reproducible test runner can spin up isolated scenario data, execute tool invocations, persist structured traces, and evaluate business constraints with 100% determinism.
