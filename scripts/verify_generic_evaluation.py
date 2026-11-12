import sys
import os
import json
import httpx

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.database.connection import SessionLocal
from backend.database.models import Run, ScenarioRun, CheckResult, CustomScenario, CustomAgent
from backend.scenarios.generic_scenario import (
    GenericScenarioPayload,
    GenericAssertion,
    is_generic_scenario
)
from backend.scenarios.custom_scenario_service import (
    list_custom_scenarios,
    get_custom_scenario
)
from backend.runner.generic_runner import GenericAgentRunner
from backend.runner.generic_evaluator import GenericAssertionEvaluator


def main():
    print("=" * 70)
    print("EvalNexus V4: Generic AI Agent Evaluation Framework Verification")
    print("=" * 70)
    
    db = SessionLocal()
    try:
        # Step 1: Verify Historical Records are Untouched
        print("\n[Step 1] Verifying Historical Qwen Colab Evidence & Database Integrity...")
        colab_run = db.query(Run).filter(Run.id.like("%colab_single_%")).first()
        if colab_run:
            print(f"  ✓ Preserved historical Colab run: {colab_run.id}")
            print(f"    - Provider: {colab_run.provider_type}, Model: {colab_run.model_name}, Status: {colab_run.status}")
        else:
            print("  ! Note: No historical colab_single run in current DB.")

        # Step 2: Verify Generic Scenario Discovery & Loading
        print("\n[Step 2] Verifying Generic Scenario Service...")
        custom_scenarios = list_custom_scenarios(db)
        generic_scenarios = [s for s in custom_scenarios if s.get("evaluation_mode") == "GENERIC"]
        print(f"  ✓ Loaded {len(custom_scenarios)} total custom scenarios.")
        print(f"  ✓ Detected {len(generic_scenarios)} generic scenarios:")
        for gs in generic_scenarios:
            print(f"    - {gs['id']} [{gs.get('category')}]: {gs.get('name')}")

        assert len(generic_scenarios) >= 3, "Expected at least 3 generic scenarios"

        # Step 3: Test Generic Mock Agent Execution
        print("\n[Step 3] Evaluating Generic Mock Agent...")
        
        # 3a: Positive Sentiment
        pos_data = get_custom_scenario(db, "generic_sentiment_positive")
        assert is_generic_scenario(pos_data), "generic_sentiment_positive must be generic"
        runner_mock = GenericAgentRunner(db, provider_type="mock", model_name="mock-generic-v1")
        res_pos = runner_mock.run_generic_scenario(pos_data)
        print(f"  ✓ Positive Sentiment Scenario Status: {res_pos['status']}")
        for cr in res_pos["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED", f"Check {cr['check_name']} failed: {cr['message']}"

        # 3b: Negative Sentiment
        neg_data = get_custom_scenario(db, "generic_sentiment_negative")
        res_neg = runner_mock.run_generic_scenario(neg_data)
        print(f"  ✓ Negative Sentiment Scenario Status: {res_neg['status']}")
        for cr in res_neg["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED", f"Check {cr['check_name']} failed: {cr['message']}"

        # 3c: Travel Planner
        travel_data = get_custom_scenario(db, "generic_travel_planner")
        res_travel = runner_mock.run_generic_scenario(travel_data)
        print(f"  ✓ Travel Planner Scenario Status: {res_travel['status']}")
        print(f"    - Tool calls: {res_travel['tool_calls']}, Turns: {res_travel['turns']}")
        for cr in res_travel["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED", f"Check {cr['check_name']} failed: {cr['message']}"

        # Step 4: Test Custom HTTP Reference Agents (via live synthetic agent server)
        print("\n[Step 4] Evaluating Cross-Domain Custom HTTP Reference Agents...")
        agent_url_base = "http://127.0.0.1:8009"
        bearer_token = "test-secret-token-12345"

        # 4a: Sentiment Classifier Reference Agent
        runner_http_sentiment = GenericAgentRunner(
            db,
            provider_type="custom_http",
            model_name="reference-sentiment-agent",
            endpoint_url=f"{agent_url_base}/sentiment",
            auth_header_name="Authorization",
            auth_token=f"Bearer {bearer_token}"
        )
        res_http_pos = runner_http_sentiment.run_generic_scenario(pos_data)
        print(f"  ✓ HTTP Sentiment Agent (Positive) Status: {res_http_pos['status']}")
        for cr in res_http_pos["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED"

        res_http_neg = runner_http_sentiment.run_generic_scenario(neg_data)
        print(f"  ✓ HTTP Sentiment Agent (Negative) Status: {res_http_neg['status']}")
        for cr in res_http_neg["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED"

        # 4b: Travel Planner Reference Agent
        runner_http_travel = GenericAgentRunner(
            db,
            provider_type="custom_http",
            model_name="reference-travel-agent",
            endpoint_url=f"{agent_url_base}/travel",
            auth_header_name="Authorization",
            auth_token=f"Bearer {bearer_token}"
        )
        res_http_travel = runner_http_travel.run_generic_scenario(travel_data)
        print(f"  ✓ HTTP Travel Agent Status: {res_http_travel['status']}")
        print(f"    - Tool calls: {res_http_travel['tool_calls']}, Turns: {res_http_travel['turns']}")
        for cr in res_http_travel["check_results"]:
            print(f"    - [{cr['status']}] {cr['check_name']}: {cr['message']}")
            assert cr["status"] == "PASSED"

        # Step 5: Verify Fail-Closed Assertion Defenses
        print("\n[Step 5] Testing Fail-Closed Assertions & Failure Detection...")

        # 5a: Malformed Output Detection (schema failure)
        malformed_scenario = json.loads(json.dumps(pos_data))
        malformed_scenario["id"] = "test_malformed_sentiment"
        malformed_scenario["customer_messages"] = ["Analyze feedback with malformed_output flag please"]
        res_malformed = runner_http_sentiment.run_generic_scenario(malformed_scenario)
        print(f"  ✓ Malformed Output Run Status: {res_malformed['status']} (expected FAILED)")
        schema_chk = next(c for c in res_malformed["check_results"] if "schema" in c["check_name"].lower())
        print(f"    - [{schema_chk['status']}] {schema_chk['check_name']}: {schema_chk['message']}")
        assert schema_chk["status"] == "FAILED"

        # 5b: Prohibited Tool Call Detection
        prohibited_scenario = json.loads(json.dumps(travel_data))
        prohibited_scenario["id"] = "test_prohibited_travel"
        prohibited_scenario["customer_messages"] = ["Plan Kyoto trip and call_prohibited action"]
        res_prohibited = runner_http_travel.run_generic_scenario(prohibited_scenario)
        print(f"  ✓ Prohibited Tool Run Status: {res_prohibited['status']} (expected FAILED)")
        tool_chk = next(c for c in res_prohibited["check_results"] if "prohibited" in c["check_name"].lower() or "unauthorized" in c["check_name"].lower())
        print(f"    - [{tool_chk['status']}] {tool_chk['check_name']}: {tool_chk['message']}")
        assert tool_chk["status"] == "FAILED"

        # 5c: Timeout Detection
        runner_timeout = GenericAgentRunner(
            db,
            provider_type="custom_http",
            model_name="timeout-agent",
            endpoint_url=f"{agent_url_base}/timeout",
            auth_header_name="Authorization",
            auth_token=f"Bearer {bearer_token}"
        )
        timeout_scenario = json.loads(json.dumps(pos_data))
        timeout_scenario["id"] = "test_timeout_scenario"
        timeout_scenario["execution_limits"]["scenario_timeout_sec"] = 2.0
        res_timeout = runner_timeout.run_generic_scenario(timeout_scenario)
        print(f"  ✓ Timeout Run Status: {res_timeout['status']} (expected FAILED)")
        print(f"    - Execution error: {res_timeout.get('execution_error')}")
        assert res_timeout["status"] == "FAILED" or res_timeout["status"] == "PROVIDER_ERROR"

        print("\n" + "=" * 70)
        print("ALL GENERIC EVALUATION CAPABILITIES VERIFIED SUCCESSFULLY!")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    main()

