"""
Suite Runner for AgentWindTunnel Benchmark Scenarios.

Executes all 30 benchmark scenarios against the deterministic mock provider.
Captures per-scenario:
- run_id, scenario_run_id, scenario_id, version
- agent_version (v1 baseline vs v2 improved)
- triggered faults (internal ground truth)
- check results (OWNERSHIP, ELIGIBILITY, DUPLICATE, STATE, COMPLETION)
- execution errors (timeouts, limit errors, exceptions)
- provider metadata (provider_type, model_name, is_mock, execution_config)
- manual/automated evidence verification of final answers vs agent-visible evidence
- flags unsupported completion claims (hallucinated successes)
"""

import json
import os
import sys
import datetime
from typing import Dict, Any, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent
from backend.runner.agent_runner import AgentWindTunnelRunner
from backend.agent.provider import MockToolCallingProvider
from backend.scenarios.generate_suite import SCENARIOS


def analyze_final_answer_claims(
    final_answer: str,
    tool_results: List[Dict[str, Any]],
    refund_in_db: bool,
    scenario_category: str
) -> Dict[str, Any]:
    """
    Cross-references final agent answer against agent-visible evidence and ground truth.
    Flags unsupported completion claims (e.g. hallucinating that a refund succeeded when it failed,
    was blocked, or was never recorded in the database).
    """
    if not final_answer:
        return {
            "claims_refund_complete": False,
            "evidence_supports_claim": True,
            "unsupported_completion_claim": False,
            "flag_reason": "No final answer generated"
        }

    ans_lower = final_answer.lower()

    # Detect claims of completion or approved refund
    completion_phrases = [
        "refund request for order",
        "has been recorded",
        "refund has been processed",
        "refund has been issued",
        "refund has been granted",
        "money will be returned",
        "refund of"
    ]
    # Check if answer claims positive refund completion
    claims_refund_complete = any(p in ans_lower for p in completion_phrases) and not (
        "unable to" in ans_lower or "ineligible" in ans_lower or "cannot" in ans_lower or "error" in ans_lower or "not eligible" in ans_lower
    )

    unsupported = False
    reason = "Claims match evidence"

    # If the agent claims completion, but no refund was committed in DB
    if claims_refund_complete and not refund_in_db:
        unsupported = True
        reason = "Agent claimed refund was recorded/processed, but no refund record exists in the database."

    # Check for hallucinated claim despite tool errors
    for tr in tool_results:
        err = tr.get("error")
        if err and claims_refund_complete:
            unsupported = True
            reason = f"Agent claimed refund success despite tool error: {err}"
            break

    return {
        "claims_refund_complete": claims_refund_complete,
        "evidence_supports_claim": not unsupported,
        "unsupported_completion_claim": unsupported,
        "flag_reason": reason
    }


def run_full_suite() -> Dict[str, Any]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    runner = AgentWindTunnelRunner(db=db, provider=MockToolCallingProvider(model_name="mock-deterministic-v1"))

    suite_report = {
        "metadata": {
            "title": "AgentWindTunnel 30-Scenario Mock Provider Execution Report",
            "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_scenarios": len(SCENARIOS),
            "agent_versions_tested": ["agent_v1_baseline", "agent_v2_improved"],
            "provider_metadata": {
                "provider_type": "mock",
                "model_name": "mock-deterministic-v1",
                "is_mock": True,
                "note": "Deterministic mock provider for infrastructure & harness verification. NOT a measured LLM benchmark."
            }
        },
        "summary": {
            "v1_baseline": {"passed": 0, "failed": 0, "unsupported_claims": 0},
            "v2_improved": {"passed": 0, "failed": 0, "unsupported_claims": 0}
        },
        "scenario_runs": []
    }

    for scen in SCENARIOS:
        scen_id = scen["id"]
        scen_cat = scen["category"]
        scen_dataset = scen.get("dataset", "development")

        for agent_version in ["agent_v1_baseline", "agent_v2_improved"]:
            res = runner.run_agent_scenario(scen, agent_version_id=agent_version)
            scen_run_id = res["scenario_run_id"]

            # Inspect DB state
            refund_record = db.query(RefundRequest).filter(
                RefundRequest.scenario_run_id == scen_run_id
            ).first()
            refund_in_db = refund_record is not None

            # Trace events
            traces = db.query(TraceEvent).filter(
                TraceEvent.scenario_run_id == scen_run_id
            ).order_by(TraceEvent.seq_num.asc()).all()

            tool_results = [
                {"tool": t.tool_name, "result": t.tool_result, "error": t.error_message}
                for t in traces if t.event_type in ["TOOL_CALL", "TOOL_RESULT", "TOOL_TIMEOUT", "ERROR"]
            ]

            # Claims analysis
            claims = analyze_final_answer_claims(
                final_answer=res.get("final_answer", ""),
                tool_results=tool_results,
                refund_in_db=refund_in_db,
                scenario_category=scen_cat
            )

            is_passed = res["status"] == "PASSED"
            v_key = "v1_baseline" if "v1" in agent_version else "v2_improved"
            if is_passed:
                suite_report["summary"][v_key]["passed"] += 1
            else:
                suite_report["summary"][v_key]["failed"] += 1

            if claims["unsupported_completion_claim"]:
                suite_report["summary"][v_key]["unsupported_claims"] += 1

            run_entry = {
                "scenario_id": scen_id,
                "scenario_name": scen["name"],
                "category": scen_cat,
                "dataset": scen_dataset,
                "agent_version": agent_version,
                "run_id": res["run_id"],
                "scenario_run_id": scen_run_id,
                "status": res["status"],
                "duration_ms": res["duration_ms"],
                "turns": res["turns"],
                "tool_calls": res["tool_calls"],
                "tokens": res["tokens"],
                "provider_metadata": {
                    "provider_type": res["provider_type"],
                    "model_name": res["model_name"],
                    "is_mock": res["is_mock"],
                    "execution_config": res["execution_config"]
                },
                "triggered_faults": res["triggered_faults"],
                "execution_error": res["execution_error"],
                "check_results": res["check_results"],
                "db_refund_created": refund_in_db,
                "refund_details": {
                    "order_id": refund_record.order_id,
                    "amount_cents": refund_record.amount_cents,
                    "status": refund_record.status,
                    "operation_key": refund_record.operation_key
                } if refund_record else None,
                "final_answer": res.get("final_answer"),
                "claims_analysis": claims
            }
            suite_report["scenario_runs"].append(run_entry)

    db.close()
    return suite_report


def write_markdown_report(suite_report: Dict[str, Any], filepath: str):
    runs = suite_report["scenario_runs"]
    meta = suite_report["metadata"]
    summary = suite_report["summary"]

    lines = []
    lines.append("# AgentWindTunnel — Mock Provider Execution Report (30 Scenarios)")
    lines.append(f"**Execution Timestamp**: `{meta['executed_at']}`  ")
    lines.append(f"**Provider**: `{meta['provider_metadata']['provider_type']}` (`{meta['provider_metadata']['model_name']}`) | `is_mock=True`  ")
    lines.append("> [!IMPORTANT]")
    lines.append("> **Mock Provider Transparency Notice**: These results represent deterministic infrastructure tests. The mock provider uses fixed logic and does NOT represent real LLM capabilities, nor does it demonstrate measured AI model improvements.")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Agent Version | Total Scenarios | Passed | Failed | Unsupported Completion Claims |")
    lines.append("|---|:---:|:---:|:---:|:---:|")
    lines.append(f"| **agent_v1_baseline** | 30 | {summary['v1_baseline']['passed']} | {summary['v1_baseline']['failed']} | {summary['v1_baseline']['unsupported_claims']} |")
    lines.append(f"| **agent_v2_improved** | 30 | {summary['v2_improved']['passed']} | {summary['v2_improved']['failed']} | {summary['v2_improved']['unsupported_claims']} |")
    lines.append("")
    lines.append("## Per-Scenario Detailed Breakdown")
    lines.append("")
    lines.append("| Scenario ID | Dataset | Category | Agent | Status | Triggered Faults | Checks (Pass/Fail) | DB Write | Claims Audit |")
    lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

    for r in runs:
        faults_str = ", ".join([f"{f['fault_type']}(call {f['call_num']})" for f in r["triggered_faults"]]) or "None"
        checks_summary = ", ".join([f"{c['check_name']}={c['status']}" for c in r["check_results"]])
        db_write_str = "Committed" if r["db_refund_created"] else "None"
        claims_str = "FLAGGED" if r["claims_analysis"]["unsupported_completion_claim"] else "Supported"

        lines.append(
            f"| `{r['scenario_id']}` | {r['dataset']} | {r['category']} | `{r['agent_version']}` | **{r['status']}** | {faults_str} | {checks_summary} | {db_write_str} | {claims_str} |"
        )

    lines.append("")
    lines.append("## Claims & Hallucination Audit")
    lines.append("")
    unsupported_runs = [r for r in runs if r["claims_analysis"]["unsupported_completion_claim"]]
    if unsupported_runs:
        lines.append("The following scenario runs produced **unsupported completion claims** where the agent claimed a refund was recorded/processed despite failure or policy violations:")
        lines.append("")
        for ur in unsupported_runs:
            lines.append(f"### `{ur['scenario_id']}` ({ur['agent_version']})")
            lines.append(f"- **Category**: {ur['category']}")
            lines.append(f"- **Final Answer**: *\"{ur['final_answer']}\"*")
            lines.append(f"- **Flag Reason**: {ur['claims_analysis']['flag_reason']}")
            lines.append(f"- **DB State**: `refund_created={ur['db_refund_created']}`")
            lines.append("")
    else:
        lines.append("No unsupported completion claims were flagged in this test execution.")
        lines.append("")

    lines.append("## Provider Metadata & Guarantees")
    lines.append("```json")
    lines.append(json.dumps(meta["provider_metadata"], indent=2))
    lines.append("```")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    report = run_full_suite()
    json_path = "docs/reports/mock_suite_report.json"
    md_path = "docs/reports/MOCK_SUITE_REPORT.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    write_markdown_report(report, md_path)
    print(f"Suite execution complete.")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print(f"Summary v1: {report['summary']['v1_baseline']}")
    print(f"Summary v2: {report['summary']['v2_improved']}")
