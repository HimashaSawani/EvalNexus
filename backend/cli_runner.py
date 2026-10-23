import json
import os
import sys
import argparse

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.database.connection import engine, Base, SessionLocal
from backend.runner.scripted_runner import ScriptedRunner
from backend.runner.agent_runner import AgentWindTunnelRunner
from backend.database.models import Customer, Order, RefundRequest, TraceEvent, CheckResult


def init_db():
    Base.metadata.create_all(bind=engine)


def run_scenario_from_file(
    file_path: str,
    agent_type: str = "agent_v1_baseline",
    provider_type: str = "mock",
    model_name: str = None
):
    from backend.agent.provider import validate_model_name
    validate_model_name(model_name)
    init_db()
    with open(file_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    db = SessionLocal()
    try:
        print("=" * 68)
        print(f"🚀 [AgentWindTunnel] Running: {scenario_data['name']}")
        print(f"📁 Category: {scenario_data.get('category')} | Agent: {agent_type}")
        print(f"⚙️ Provider: {provider_type.upper()} ({'MOCK SIMULATOR' if provider_type == 'mock' else 'LIVE MODEL'})")
        print(f"🕒 Fixed Clock: {scenario_data.get('fixed_clock')}")
        if scenario_data.get("fault_configs"):
            print(f"⚠️ Fault Config: {scenario_data['fault_configs']}")
        print("=" * 68)

        if agent_type == "scripted":
            runner = ScriptedRunner(db)
            result = runner.run_scenario(scenario_data)
        else:
            runner = AgentWindTunnelRunner(db, provider_type=provider_type, model_name=model_name)
            result = runner.run_agent_scenario(scenario_data, agent_version_id=agent_type)

        print("\n📊 EXECUTION SUMMARY:")
        print(f"  • Run ID:           {result['run_id']}")
        print(f"  • Scenario Run ID:  {result['scenario_run_id']}")
        print(f"  • Engine Mode:      {'[MOCK SIMULATOR - Infrastructure Test]' if result.get('is_mock', True) else '[LIVE LLM RUN]'}")
        print(f"  • Model Name:       {result.get('model_name', 'scripted')}")
        print(f"  • Duration:         {result['duration_ms']} ms")
        print(f"  • Trace Events:     {result['trace_events_count']} events logged")
        if "tokens" in result:
            print(f"  • Turns / Calls:    {result.get('turns', 0)} turns | {result.get('tool_calls', 0)} tool calls")
            print(f"  • Token Usage:      {result.get('tokens', 0)} tokens")
        print(f"  • Overall Status:   [{result['status']}]")

        if result.get("final_answer"):
            print(f"\n💬 AGENT FINAL ANSWER:")
            print(f"  \"{result['final_answer']}\"")

        print("\n🔍 DETERMINISTIC EVALUATOR CHECKS:")
        for chk in result["check_results"]:
            icon = "✅" if chk["status"] == "PASSED" else "❌"
            print(f"  {icon} {chk['check_name']:<12}: {chk['status']:<8} - {chk['message']}")

        print("\n💾 DATABASE STATE AUDIT (Scoped by scenario_run_id):")
        cust = db.query(Customer).filter(Customer.scenario_run_id == result['scenario_run_id']).first()
        orders = db.query(Order).filter(Order.scenario_run_id == result['scenario_run_id']).all()
        refunds = db.query(RefundRequest).filter(RefundRequest.scenario_run_id == result['scenario_run_id']).all()
        traces = db.query(TraceEvent).filter(TraceEvent.scenario_run_id == result['scenario_run_id']).order_by(TraceEvent.seq_num).all()

        print(f"  • Customer:  {cust.name} ({cust.id})")
        for ord_item in orders:
            print(f"  • Order:     {ord_item.id} | Status: {ord_item.status} | Amount: ${ord_item.total_amount_cents / 100:.2f}")

        if refunds:
            for rf in refunds:
                print(f"  • Refund:    {rf.id} | Amount: ${rf.amount_cents / 100:.2f} | Status: {rf.status} | OpKey: {rf.operation_key}")
        else:
            print("  • Refund:    None recorded (as expected for ineligible cases)")

        print("\n📜 TRACE EVENT TIMELINE:")
        for tr in traces:
            tool_info = f"({tr.tool_name})" if tr.tool_name else ""
            err_info = f"[ERR: {tr.error_message[:40]}...]" if tr.error_message else ""
            print(f"  [{tr.seq_num:02d}] {tr.event_type:<15} {tool_info:<26} {err_info:<30} {tr.duration_ms}ms")

        print("=" * 68)
        return result
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AgentWindTunnel Terminal Scenario Runner")
    parser.add_argument("scenario", nargs="?", default="scenarios/eligible_refund_scenario.json", help="Path to scenario JSON")
    parser.add_argument("--agent", choices=["agent_v1_baseline", "agent_v2_improved", "scripted"], default="agent_v1_baseline", help="Agent version to evaluate")
    parser.add_argument("--provider", choices=["mock", "openai", "gemini"], default="mock", help="Provider type (mock simulator or real LLM)")
    parser.add_argument("--model", default=None, help="Specific model name (e.g. gpt-4o-mini, gemini-1.5-flash)")
    args = parser.parse_args()

    run_scenario_from_file(args.scenario, agent_type=args.agent, provider_type=args.provider, model_name=args.model)
