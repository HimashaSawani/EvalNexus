import sys
import json
import argparse
from typing import Dict, Any

from backend.gates.quality_gate_evaluator import evaluate_quality_gate


def main():
    parser = argparse.ArgumentParser(
        prog="agentwindtunnel-gate",
        description="AgentWindTunnel Automated CI/CD Quality Gate CLI"
    )
    parser.add_argument("--rules-file", type=str, help="Path to JSON file containing quality gate rules")
    parser.add_argument("--rules-json", type=str, help="Inline JSON string containing quality gate rules")
    parser.add_argument("--evidence-file", type=str, help="Path to JSON file containing run/benchmark evidence")
    parser.add_argument("--evidence-json", type=str, help="Inline JSON string containing run/benchmark evidence")

    args = parser.parse_args()

    # Load rules
    rules_dict: Dict[str, Any] = {}
    if args.rules_file:
        with open(args.rules_file, "r", encoding="utf-8") as f:
            rules_dict = json.load(f)
    elif args.rules_json:
        rules_dict = json.loads(args.rules_json)
    else:
        print("ERROR: Either --rules-file or --rules-json must be provided.", file=sys.stderr)
        sys.exit(2)

    # Load evidence
    evidence_dict: Dict[str, Any] = {}
    if args.evidence_file:
        with open(args.evidence_file, "r", encoding="utf-8") as f:
            evidence_dict = json.load(f)
    elif args.evidence_json:
        evidence_dict = json.loads(args.evidence_json)
    else:
        print("ERROR: Either --evidence-file or --evidence-json must be provided.", file=sys.stderr)
        sys.exit(2)

    result = evaluate_quality_gate(rules_dict, evidence_dict)

    print("\n==================================================")
    print(f" AGENTWINDTUNNEL QUALITY GATE: {result.status} (Score: {result.score}/100)")
    print("==================================================")
    for rule in result.rule_evaluations:
        symbol = "[PASS]" if rule.passed else "[FAIL]"
        print(f" {symbol} {rule.rule_name}: {rule.message}")
    print("--------------------------------------------------")
    print(f" Summary: {result.summary}")
    print("==================================================\n")

    if result.status == "PASSED":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
