import sys
import subprocess
import json
import pytest

from backend.gates.quality_gate_evaluator import evaluate_quality_gate


def test_quality_gate_all_pass():
    rules = {
        "min_pass_rate": 0.90,
        "max_p95_latency_ms": 300.0,
        "max_cost_usd": 0.05,
        "min_resilience_score": 80,
        "forbidden_tools": ["delete_database"],
        "required_checks": ["OWNERSHIP", "ELIGIBILITY"]
    }
    evidence = {
        "pass_rate": 0.98,
        "latency_p95_ms": 180.0,
        "total_cost_usd": 0.0025,
        "resilience_score": 95,
        "tools_called": ["lookup_order", "refund_order"],
        "passed_checks": ["OWNERSHIP", "ELIGIBILITY", "STATE_CONSISTENCY"]
    }

    result = evaluate_quality_gate(rules, evidence)
    assert result.status == "PASSED"
    assert result.score == 100
    assert len(result.rule_evaluations) == 6
    assert all(r.passed for r in result.rule_evaluations)


def test_quality_gate_forbidden_tools_violation():
    rules = {
        "min_pass_rate": 0.80,
        "forbidden_tools": ["execute_shell_command", "drop_table"]
    }
    evidence = {
        "pass_rate": 0.95,
        "tools_called": ["lookup_order", "execute_shell_command"]
    }

    result = evaluate_quality_gate(rules, evidence)
    assert result.status == "FAILED"
    assert result.score < 100
    failed_rule = next(r for r in result.rule_evaluations if not r.passed)
    assert failed_rule.rule_name == "forbidden_tools"
    assert "execute_shell_command" in failed_rule.message


def test_quality_gate_pass_rate_and_latency_violation():
    rules = {
        "min_pass_rate": 0.95,
        "max_p95_latency_ms": 150.0
    }
    evidence = {
        "pass_rate": 0.80,
        "latency_p95_ms": 250.0
    }

    result = evaluate_quality_gate(rules, evidence)
    assert result.status == "FAILED"
    assert result.score == 0
    assert len(result.rule_evaluations) == 2
    assert not result.rule_evaluations[0].passed
    assert not result.rule_evaluations[1].passed


def test_quality_gate_cli_exit_codes():
    rules_json = json.dumps({"min_pass_rate": 0.90})
    pass_evidence = json.dumps({"pass_rate": 0.95})
    fail_evidence = json.dumps({"pass_rate": 0.75})

    # Test CLI Pass -> exit code 0
    proc_pass = subprocess.run(
        [sys.executable, "-m", "backend.cli.quality_gate", "--rules-json", rules_json, "--evidence-json", pass_evidence],
        capture_output=True,
        text=True
    )
    assert proc_pass.returncode == 0
    assert "QUALITY GATE: PASSED" in proc_pass.stdout

    # Test CLI Fail -> exit code 1
    proc_fail = subprocess.run(
        [sys.executable, "-m", "backend.cli.quality_gate", "--rules-json", rules_json, "--evidence-json", fail_evidence],
        capture_output=True,
        text=True
    )
    assert proc_fail.returncode == 1
    assert "QUALITY GATE: FAILED" in proc_fail.stdout
