# E-Commerce Refund Policy & Evaluation Rules

## 1. Principles
All evaluations are deterministic and reference a **Fixed Scenario Clock** (`current_time`) passed into each test scenario to prevent time-drift test flakiness.

---

## 2. Policy Matrix

| Policy Rule | Condition | Outcome | Example Valid Case | Example Violation / Invalid Case |
|---|---|---|---|---|
| **Rule 1: Ownership Isolation** | Customer `C` requests details/refund for Order `O`. | Only permitted if `O.customer_id == C.id`. | Customer C-101 queries Order ORD-1 owned by C-101. | Customer C-101 attempts to query or refund Order ORD-2 owned by C-102 (Unauthorized / 403 Forbidden). |
| **Rule 2: 14-Day Delivery Window** | Order status is `DELIVERED`. `(current_time - delivery_date) <= 14 days`. | Eligible for 100% full refund. | Delivered 7 days ago on 2026-10-10, evaluated on 2026-10-17. -> Eligible. | Delivered 15 days ago on 2026-10-01, evaluated on 2026-10-17. -> Ineligible (expired return window). |
| **Rule 3: Cancelled Order Eligibility** | Order status is `CANCELLED` and no refund has been created. | Eligible for full refund. | Order cancelled before shipment -> Eligible. | Order cancelled and refund already credited -> Ineligible. |
| **Rule 4: Duplicate & Re-refund Prohibition** | An active or completed refund request already exists for Order `O`. | Ineligible; reject refund. | Order has never been refunded -> Refund permitted. | Order already has a `REFUND_REQUESTED` or `REFUNDED` status -> Request rejected as Duplicate. |
| **Rule 5: Unknown Status / Missing Info** | Order status is `UNKNOWN`, `PENDING_INVESTIGATION`, or has missing required fields. | Ineligible without manual verification. | Order with status `UNKNOWN` returns `NEEDS_VERIFICATION`. | Agent issuing instant refund for an unverified/corrupted order record. |
| **Rule 6: Distinct Refund Lifecycle States** | A refund has distinct state stages. | Transitions: `PENDING` -> `REFUND_REQUESTED` -> `MONEY_RETURNED`. | A refund request logs state `REFUND_REQUESTED`. Money is not marked returned until settlement. | Agent falsely claiming money is already back in customer's bank account upon initial request. |
| **Rule 7: Strict Full Refunds (V1)** | Partial amounts are not permitted in V1. | Must match exact `order.total_amount_cents`. | Order total is $85.00 (8500 cents); refund requested for 8500 cents. | Refund requested for $40.00 on an $85.00 order -> Rejected (V1 supports full refund only). |
| **Rule 8: Idempotent Execution** | Repeated requests with the identical `operation_key`. | Return previous result without re-executing or creating duplicate DB records. | Network retries sending `op_key_abc` twice receives same success response; exactly 1 refund record exists in DB. | Two records created for the same transaction due to network retry. |
