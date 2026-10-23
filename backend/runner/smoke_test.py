"""
Development Smoke Test for Live LLM Providers.
Executes a targeted verification run:
- Preflight:
  1. Inspects credentials and queries provider endpoint to list available models for this account.
  2. Rejects placeholders and unverified model IDs locally before making generation requests.
  3. Verifies a complete tool-calling round trip (Turn 1 tool call + Turn 2 final response after tool output).
- 3 Scenarios:
  1. Normal Case (scen_norm_01_delivered_5d)
  2. Ineligible Case (scen_elig_02_delivered_15d_expired)
  3. Fault Case: Timeout-After-Write (scen_fault_02_timeout_after_write)
- 2 Agent Versions:
  1. agent_v1_baseline
  2. agent_v2_improved
- 1 Repetition (total 6 executions)

CRITICAL FIDELITY:
- No silent mock fallback.
- Classifies provider setup/network failures as PROVIDER_ERROR.
- Marks checks as NOT_EVALUATED on provider errors and excludes from agent success rate.
- Measures real duration and preserves unknown token usage as None.
- Never logs or exposes credentials.
"""

import argparse
import json
import os
import sys
import datetime

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent
from backend.runner.agent_runner import AgentWindTunnelRunner
from backend.agent.provider import (
    resolve_provider,
    list_available_models,
    verify_tool_calling_preflight,
    validate_model_name,
    sanitize_secret,
    KNOWN_PLACEHOLDERS
)


SMOKE_SCENARIOS = [
    "scenarios/dev/scen_norm_01_delivered_5d.json",
    "scenarios/dev/scen_elig_02_delivered_15d_expired.json",
    "scenarios/dev/scen_fault_02_timeout_after_write.json"
]


def write_smoke_markdown_report(report: dict, filepath: str):
    meta = report["metadata"]
    results = report["results"]
    preflight = report.get("preflight", {})

    lines = []
    lines.append(f"# AgentWindTunnel — Live Model Smoke Test Report ({meta['provider_type'].upper()})")
    lines.append(f"**Execution Timestamp**: `{meta['executed_at']}`  ")
    lines.append(f"**Verified Model**: `{meta['model_name']}`  ")
    lines.append(f"**Provider**: `{meta['provider_type']}` (`is_mock=False`)  ")
    lines.append(
        f"**Preflight Probe**: `{preflight.get('status', 'SKIPPED')}` "
        f"(Total: {preflight.get('elapsed_ms', 0)}ms | Turn 1: {preflight.get('turn1_ms', 0)}ms | Turn 2: {preflight.get('turn2_ms', 0)}ms)  "
    )
    if preflight.get("final_answer"):
        lines.append(f"**Preflight Probe Final Answer**: *\"{preflight['final_answer']}\"*  ")
    lines.append(f"**Reproduction Command**: `python -m backend.runner.smoke_test --provider {meta['provider_type']} --model {meta['model_name']}`  ")
    lines.append("")

    # Summary table
    passed_count = sum(1 for r in results if r["status"] == "PASSED")
    failed_count = sum(1 for r in results if r["status"] == "FAILED")
    prov_err_count = sum(1 for r in results if r["status"] == "PROVIDER_ERROR")
    eval_count = passed_count + failed_count
    rate_str = f"{(passed_count / eval_count) * 100:.1f}%" if eval_count > 0 else "N/A (Provider Errors)"

    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Metric | Value | Note |")
    lines.append("|---|:---:|---|")
    lines.append(f"| Total Executions | {len(results)} | 3 scenarios × 2 agent versions × 1 repetition |")
    lines.append(f"| Completed Evaluations | {eval_count} | Runs evaluated by deterministic checks |")
    lines.append(f"| Provider Setup Errors | {prov_err_count} | Excluded from agent behavioral success rate |")
    lines.append(f"| Agent Success Rate | **{rate_str}** | Passed / Completed Evaluations |")
    lines.append("")

    lines.append("## Per-Scenario Detailed Breakdown")
    lines.append("")
    lines.append("| Scenario ID | Agent Version | Status | Duration (ms) | Tokens | Tool Calls | Triggered Faults | Checks Breakdown | Final Answer Preview |")
    lines.append("|---|:---:|:---:|:---:|:---:|:---:|:---:|---|---|")

    for r in results:
        tok_str = str(r["tokens"]) if r["tokens"] is not None else "unknown"
        raw_faults = r.get("triggered_faults", [])
        faults_str = ", ".join([f.get("fault_type", str(f)) if isinstance(f, dict) else str(f) for f in raw_faults]) or "None"
        checks_str = ", ".join([f"{k}={v}" for k, v in r["checks"].items()])
        ans_preview = (r["final_answer"][:60].replace("\n", " ") + "...") if r.get("final_answer") else (r.get("execution_error") or "None")
        tool_names = ", ".join([tc["tool"] for tc in r.get("actual_tool_calls", [])]) or f"{r['tool_calls']} calls"
        lines.append(
            f"| `{r['scenario_id']}` | `{r['agent_version']}` | **{r['status']}** | {r['duration_ms']} | {tok_str} | {tool_names} | `{faults_str}` | {checks_str} | *\"{ans_preview}\"* |"
        )

    lines.append("")
    lines.append("## Actual Tool Calls & Trace Details")
    lines.append("")
    for r in results:
        raw_faults = r.get("triggered_faults", [])
        faults_display = ", ".join([f"{f.get('fault_type')} on {f.get('tool_name')}" if isinstance(f, dict) else str(f) for f in raw_faults]) or "None"
        lines.append(f"### `{r['scenario_id']}` ({r['agent_version']}) — Status: **{r['status']}**")
        lines.append(f"- **Triggered Faults**: `{faults_display}`")
        lines.append(f"- **Final Answer**: *\"{r.get('final_answer') or r.get('execution_error')}\"*")
        lines.append(f"- **Deterministic Checks**:")
        for chk_name, chk_status in r["checks"].items():
            icon = "✅" if chk_status == "PASSED" else "❌"
            lines.append(f"  - {icon} **{chk_name}**: `{chk_status}`")
        if r.get("actual_tool_calls"):
            lines.append("- **Tool Calls Executed**:")
            for tc in r["actual_tool_calls"]:
                lines.append(f"  1. `{tc['tool']}` (args: `{json.dumps(tc.get('args', {}))}`) — {tc.get('duration_ms', 0)}ms")
        else:
            lines.append("- **Tool Calls Executed**: None")
        lines.append("")

    if meta.get("available_models_discovered"):
        lines.append("## Models Discovered For This Account")
        lines.append("")
        for m in meta["available_models_discovered"][:20]:
            lines.append(f"- **`{m['id']}`** ({m.get('display_name', '')}): Generation: `{m.get('supports_generation', False)}` | Tool Calling: `{m.get('supports_tool_calling', False)}`")
        lines.append("")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_smoke_test(provider_type: str = "gemini", model_name: str = None) -> dict:
    key_env = "OPENAI_API_KEY" if provider_type == "openai" else "GEMINI_API_KEY"
    api_key = os.getenv(key_env)
    if not api_key or not api_key.strip() or api_key.strip() in KNOWN_PLACEHOLDERS:
        raise RuntimeError(
            f"ERROR: Missing or placeholder environment variable '{key_env}' for live provider '{provider_type}'.\n"
            f"Silent mock fallback is strictly disabled.\n"
            f"Configure your real secret API key in Windows PowerShell using:\n"
            f"  $env:{key_env}=\"<your-actual-secret-key>\"\n"
            f"Or put it in a local .env file:\n"
            f"  {key_env}=<your-actual-secret-key>\n"
            f"Never paste your key into chat or public logs."
        )

    # Step 0: Reject placeholders immediately before any network calls
    if model_name:
        validate_model_name(model_name)

    print(f"\n=======================================================")
    print(f" Starting Live Provider Smoke Test: {provider_type.upper()}")
    print(f"=======================================================\n")

    # Step 1: Model Discovery from local credentials
    print(f"[1/3] Discovering available models for this account...")
    discovered_models = []
    selected_model = None

    try:
        discovered_models = list_available_models(api_key, provider_type=provider_type)
        print(f"   Discovered {len(discovered_models)} models from provider endpoint.")
        tool_capable = [m for m in discovered_models if m.get("supports_tool_calling")]
        print(f"   Identified {len(tool_capable)} models in tool-calling capable families.")

        # Step 2: Validate requested model or auto-select an actual returned model
        if model_name:
            validate_model_name(model_name, discovered_models=discovered_models)
            selected_model = model_name
            print(f"   Using verified user-requested model: '{selected_model}'")
        else:
            # Auto-select an actual returned model ID from discovery
            preferred_gemini = [
                "gemini-flash-lite-latest",
                "gemini-3.1-flash-lite",
                "gemini-3.5-flash-lite",
                "gemini-3.8-flash",
                "gemini-flash-latest"
            ]
            preferred_openai = ["gpt-4o-mini", "gpt-4o"]
            preferred = preferred_gemini if provider_type == "gemini" else preferred_openai

            for pref in preferred:
                if any(m["id"] == pref for m in tool_capable):
                    selected_model = pref
                    break
            if not selected_model and tool_capable:
                selected_model = tool_capable[0]["id"]
            if not selected_model and discovered_models:
                selected_model = discovered_models[0]["id"]
            print(f"   Auto-selected verified model from discovery: '{selected_model}'")

    except Exception as e:
        sanitized_err = sanitize_secret(str(e), api_key)
        if isinstance(e, ValueError):
            raise
        print(f"   Warning during model listing: {sanitized_err}")
        if model_name:
            validate_model_name(model_name)
            selected_model = model_name
        else:
            selected_model = "gemini-flash-lite-latest" if provider_type == "gemini" else "gpt-4o-mini"
        print(f"   Proceeding with model: '{selected_model}'")

    provider = resolve_provider(provider_type=provider_type, model_name=selected_model, api_key=api_key)

    # Step 2: Complete Tool-Calling Preflight Round-Trip Probe
    print(f"\n[2/3] Running complete 2-turn tool-calling preflight probe...")
    preflight_res = {}
    try:
        preflight_res = verify_tool_calling_preflight(provider)
        print(f"   Turn 1 Tool Call probe PASSED in {preflight_res.get('turn1_ms', 0)}ms.")
        print(f"   Turn 2 Final Answer probe PASSED in {preflight_res.get('turn2_ms', 0)}ms.")
        print(f"   Preflight probe PASSED in total {preflight_res['elapsed_ms']}ms.")
        print(f"   Final Answer: \"{preflight_res.get('final_answer')}\"")
    except Exception as e:
        clean_err = sanitize_secret(str(e), api_key)
        print(f"   Preflight probe FAILED: {clean_err}")
        preflight_report = {
            "metadata": {
                "title": f"AgentWindTunnel Real Provider Preflight Failed ({provider_type})",
                "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "provider_type": provider.provider_type,
                "model_name": provider.model_name,
                "is_mock": False,
                "available_models_discovered": discovered_models
            },
            "preflight": {
                "status": "PROVIDER_ERROR",
                "error": clean_err
            },
            "results": []
        }
        os.makedirs("docs/reports", exist_ok=True)
        out_file = f"docs/reports/smoke_test_{provider_type}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(preflight_report, f, indent=2)
        write_smoke_markdown_report(preflight_report, f"docs/reports/SMOKE_TEST_{provider_type.upper()}_REPORT.md")
        raise RuntimeError(f"Smoke test aborted: Preflight probe failed for model '{provider.model_name}': {clean_err}")

    # Step 3: Run the 6 Smoke Test Executions
    print(f"\n[3/3] Executing 6 smoke test scenarios (3 scenarios × 2 agent versions × 1 repetition)...")

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    runner = AgentWindTunnelRunner(db=db, provider=provider)

    smoke_report = {
        "metadata": {
            "title": f"AgentWindTunnel Real Provider Smoke Test (3x2x1) - {provider_type.upper()}",
            "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "provider_type": provider.provider_type,
            "model_name": provider.model_name,
            "is_mock": False,
            "available_models_discovered": discovered_models
        },
        "preflight": preflight_res,
        "results": []
    }

    for scen_path in SMOKE_SCENARIOS:
        with open(scen_path, "r", encoding="utf-8") as f:
            scen_data = json.load(f)

        for agent_version in ["agent_v1_baseline", "agent_v2_improved"]:
            print(f"\n-> Running {scen_data['id']} with {agent_version}...")
            res = runner.run_agent_scenario(scen_data, agent_version_id=agent_version)

            # Query actual tool calls made from trace events
            traces = db.query(TraceEvent).filter(TraceEvent.scenario_run_id == res["scenario_run_id"]).order_by(TraceEvent.seq_num).all()
            actual_tool_calls_list = []
            for tr in traces:
                if tr.tool_name:
                    actual_tool_calls_list.append({
                        "seq": tr.seq_num,
                        "tool": tr.tool_name,
                        "args": tr.tool_arguments,
                        "duration_ms": tr.duration_ms
                    })

            entry = {
                "scenario_id": scen_data["id"],
                "scenario_name": scen_data["name"],
                "category": scen_data["category"],
                "agent_version": agent_version,
                "status": res["status"],
                "turns": res["turns"],
                "tool_calls": res["tool_calls"],
                "actual_tool_calls": actual_tool_calls_list,
                "tokens": res["tokens"],
                "duration_ms": res["duration_ms"],
                "triggered_faults": res.get("triggered_faults", []),
                "execution_error": res.get("execution_error"),
                "checks": {c["check_name"]: c["status"] for c in res["check_results"]},
                "final_answer": res.get("final_answer")
            }
            smoke_report["results"].append(entry)

            err_msg = f" | Error: {res.get('execution_error')}" if res.get("execution_error") else ""
            tok_msg = f"{res['tokens']} tokens" if res["tokens"] is not None else "tokens: unknown"
            print(f"   Status: [{res['status']}] | Turns: {res['turns']} | Tool Calls: {res['tool_calls']} | {tok_msg} | Duration: {res['duration_ms']}ms{err_msg}")
            if res.get("triggered_faults"):
                print(f"   [FAULT] Triggered Faults: {res['triggered_faults']}")
            if actual_tool_calls_list:
                call_summary = ", ".join([f"{c['tool']}({list(c.get('args', {}).keys())})" for c in actual_tool_calls_list])
                print(f"   [TOOL] Calls: {call_summary}")
            if res.get("final_answer"):
                short_ans = res["final_answer"][:100].replace("\n", " ")
                print(f"   [ANSWER] Final Answer: \"{short_ans}...\"")
            chk_summary = " ".join([f"[{'PASS' if c['status'] == 'PASSED' else 'FAIL'}] {c['check_name']}={c['status']}" for c in res["check_results"]])
            print(f"   [CHECKS] Evaluator: {chk_summary}")

    db.close()

    os.makedirs("docs/reports", exist_ok=True)
    out_json = f"docs/reports/smoke_test_{provider_type}.json"
    out_md = f"docs/reports/SMOKE_TEST_{provider_type.upper()}_REPORT.md"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(smoke_report, f, indent=2)

    write_smoke_markdown_report(smoke_report, out_md)

    print(f"\n=======================================================")
    print(f" Smoke Test Run Completed Successfully!")
    print(f" Verified Model:   {provider.model_name}")
    print(f" JSON Report:      {out_json}")
    print(f" Markdown Report:  {out_md}")
    print(f" Working PowerShell Command:")
    print(f"   python -m backend.runner.smoke_test --provider {provider_type} --model {provider.model_name}")
    print(f"=======================================================\n")
    return smoke_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live Model Smoke Test")
    parser.add_argument("--provider", default="gemini", choices=["openai", "gemini"])
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    run_smoke_test(provider_type=args.provider, model_name=args.model)
