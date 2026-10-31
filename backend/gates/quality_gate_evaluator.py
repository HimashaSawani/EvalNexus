from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class QualityGateRules(BaseModel):
    min_pass_rate: Optional[float] = Field(default=None, description="Minimum allowed pass rate between 0.0 and 1.0")
    max_p95_latency_ms: Optional[float] = Field(default=None, description="Maximum allowed p95 latency in milliseconds")
    max_cost_usd: Optional[float] = Field(default=None, description="Maximum total cost in USD")
    min_resilience_score: Optional[int] = Field(default=None, description="Minimum resilience score (0-100)")
    forbidden_tools: List[str] = Field(default_factory=list, description="Tools that must never be invoked")
    required_checks: List[str] = Field(default_factory=list, description="Mandatory assertion check names that must pass")


class RuleEvaluation(BaseModel):
    rule_name: str
    passed: bool
    threshold: Any
    actual: Any
    message: str


class GateEvaluationResult(BaseModel):
    status: str  # PASSED, FAILED
    score: int   # 0 to 100
    rule_evaluations: List[RuleEvaluation]
    summary: str


def evaluate_quality_gate(
    rules_dict: Dict[str, Any],
    evidence: Dict[str, Any]
) -> GateEvaluationResult:
    """
    Evaluates evidence from an execution run or benchmark against gate rules.
    """
    rules = QualityGateRules(**rules_dict)
    evaluations: List[RuleEvaluation] = []

    # 1. min_pass_rate
    if rules.min_pass_rate is not None:
        actual_pass_rate = float(evidence.get("pass_rate", 0.0))
        passed = actual_pass_rate >= rules.min_pass_rate
        evaluations.append(RuleEvaluation(
            rule_name="min_pass_rate",
            passed=passed,
            threshold=rules.min_pass_rate,
            actual=actual_pass_rate,
            message=f"Pass rate {actual_pass_rate:.2%} {'satisfies' if passed else 'violates'} requirement (>={rules.min_pass_rate:.2%})"
        ))

    # 2. max_p95_latency_ms
    if rules.max_p95_latency_ms is not None:
        actual_p95 = float(evidence.get("latency_p95_ms", evidence.get("duration_ms", 0.0)))
        passed = actual_p95 <= rules.max_p95_latency_ms
        evaluations.append(RuleEvaluation(
            rule_name="max_p95_latency_ms",
            passed=passed,
            threshold=rules.max_p95_latency_ms,
            actual=actual_p95,
            message=f"Latency {actual_p95:.1f}ms {'satisfies' if passed else 'exceeds'} ceiling (<={rules.max_p95_latency_ms}ms)"
        ))

    # 3. max_cost_usd
    if rules.max_cost_usd is not None:
        actual_cost = float(evidence.get("total_cost_usd", 0.0))
        passed = actual_cost <= rules.max_cost_usd
        evaluations.append(RuleEvaluation(
            rule_name="max_cost_usd",
            passed=passed,
            threshold=rules.max_cost_usd,
            actual=actual_cost,
            message=f"Cost ${actual_cost:.4f} {'is within' if passed else 'exceeds'} budget limit (<=${rules.max_cost_usd:.4f})"
        ))

    # 4. min_resilience_score
    if rules.min_resilience_score is not None:
        actual_resilience = int(evidence.get("resilience_score", 100))
        passed = actual_resilience >= rules.min_resilience_score
        evaluations.append(RuleEvaluation(
            rule_name="min_resilience_score",
            passed=passed,
            threshold=rules.min_resilience_score,
            actual=actual_resilience,
            message=f"Resilience score {actual_resilience} {'meets' if passed else 'falls below'} threshold (>={rules.min_resilience_score})"
        ))

    # 5. forbidden_tools
    if rules.forbidden_tools:
        tools_called = set(evidence.get("tools_called", []))
        forbidden_invoked = tools_called.intersection(set(rules.forbidden_tools))
        passed = len(forbidden_invoked) == 0
        evaluations.append(RuleEvaluation(
            rule_name="forbidden_tools",
            passed=passed,
            threshold=rules.forbidden_tools,
            actual=list(forbidden_invoked),
            message="No forbidden tools invoked." if passed else f"Forbidden tools invoked: {list(forbidden_invoked)}"
        ))

    # 6. required_checks
    if rules.required_checks:
        passed_checks = set(evidence.get("passed_checks", []))
        missing_checks = set(rules.required_checks) - passed_checks
        passed = len(missing_checks) == 0
        evaluations.append(RuleEvaluation(
            rule_name="required_checks",
            passed=passed,
            threshold=rules.required_checks,
            actual=list(passed_checks),
            message="All required checks passed." if passed else f"Missing required check passes: {list(missing_checks)}"
        ))

    if not evaluations:
        return GateEvaluationResult(
            status="PASSED",
            score=100,
            rule_evaluations=[],
            summary="No gate rules were configured. Passed by default."
        )

    passed_count = sum(1 for e in evaluations if e.passed)
    total_rules = len(evaluations)
    score = int((passed_count / total_rules) * 100)
    overall_status = "PASSED" if passed_count == total_rules else "FAILED"

    failed_messages = [e.message for e in evaluations if not e.passed]
    summary = (
        f"Quality gate PASSED: {passed_count}/{total_rules} rules met (Score: {score}/100)."
        if overall_status == "PASSED"
        else f"Quality gate FAILED: {len(failed_messages)} rule violations ({'; '.join(failed_messages)})."
    )

    return GateEvaluationResult(
        status=overall_status,
        score=score,
        rule_evaluations=evaluations,
        summary=summary
    )
