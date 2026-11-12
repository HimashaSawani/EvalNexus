import pytest
import json
from backend.database.models import TraceEvent, ScenarioRun, CheckResult
from backend.runner.generic_evaluator import GenericAssertionEvaluator
from backend.scenarios.generic_scenario import GenericAssertion
from backend.runner.generic_runner import GenericAgentRunner


def test_evaluator_assertion_json_schema(db_session):
    scen_run_id = "test_run_schema_eval"
    evaluator = GenericAssertionEvaluator(db_session, scen_run_id)

    schema = {
        "type": "object",
        "required": ["sentiment", "score"],
        "properties": {
            "sentiment": {"type": "string"},
            "score": {"type": "number"}
        }
    }
    assertion = GenericAssertion(
        type="json_schema",
        name="Schema Check",
        schema_def=schema
    )

    # Valid JSON
    results = evaluator.evaluate_all([assertion], final_answer='{"sentiment": "POSITIVE", "score": 0.95}')
    assert len(results) == 1
    assert results[0].status == "PASSED"

    # Invalid Schema (missing required field)
    results_fail = evaluator.evaluate_all([assertion], final_answer='{"sentiment": "POSITIVE"}')
    assert results_fail[0].status == "FAILED"
    assert "score" in results_fail[0].message

    # Invalid Non-JSON Output
    results_unparseable = evaluator.evaluate_all([assertion], final_answer='Not a json string at all')
    assert results_unparseable[0].status == "FAILED"


def test_evaluator_assertion_json_path_equals(db_session):
    scen_run_id = "test_run_path_eval"
    evaluator = GenericAssertionEvaluator(db_session, scen_run_id)

    assertion = GenericAssertion(
        type="json_path_equals",
        name="Path Check",
        path="itinerary.status",
        expected="PLANNED"
    )

    # Matching
    payload = json.dumps({"itinerary": {"status": "PLANNED"}})
    res = evaluator.evaluate_all([assertion], final_answer=payload)
    assert res[0].status == "PASSED"

    # Mismatch
    payload_mismatch = json.dumps({"itinerary": {"status": "CANCELLED"}})
    res_mismatch = evaluator.evaluate_all([assertion], final_answer=payload_mismatch)
    assert res_mismatch[0].status == "FAILED"

    # Missing Path
    payload_missing = json.dumps({"other": 123})
    res_missing = evaluator.evaluate_all([assertion], final_answer=payload_missing)
    assert res_missing[0].status == "FAILED"


def test_evaluator_tool_called_and_not_called(db_session):
    scen_run_id = "test_run_tool_eval"

    # Seed TraceEvents
    t1 = TraceEvent(
        id=f"trc_{scen_run_id}_1",
        scenario_run_id=scen_run_id,
        seq_num=1,
        event_type="TOOL_EXECUTION",
        tool_name="check_weather",
        tool_arguments={"city": "Tokyo"}
    )
    db_session.add(t1)
    db_session.commit()

    evaluator = GenericAssertionEvaluator(db_session, scen_run_id)

    # Tool called (should pass)
    a_called = GenericAssertion(type="tool_called", tool="check_weather")
    res_called = evaluator.evaluate_all([a_called])
    assert res_called[0].status == "PASSED"

    # Tool called with argument match (should pass)
    a_args_match = GenericAssertion(
        type="tool_called",
        tool="check_weather",
        argument_matches={"city": "Tokyo"}
    )
    res_args_match = evaluator.evaluate_all([a_args_match])
    assert res_args_match[0].status == "PASSED"

    # Tool called with mismatched argument (should fail)
    a_args_mismatch = GenericAssertion(
        type="tool_called",
        tool="check_weather",
        argument_matches={"city": "Paris"}
    )
    res_args_mismatch = evaluator.evaluate_all([a_args_mismatch])
    assert res_args_mismatch[0].status == "FAILED"

    # Tool not called on tool that was called (should fail)
    a_prohibited_fail = GenericAssertion(type="tool_not_called", tool="check_weather")
    res_proh_fail = evaluator.evaluate_all([a_prohibited_fail])
    assert res_proh_fail[0].status == "FAILED"

    # Tool not called on tool that was NOT called (should pass)
    a_prohibited_pass = GenericAssertion(type="tool_not_called", tool="unauthorized_action")
    res_proh_pass = evaluator.evaluate_all([a_prohibited_pass])
    assert res_proh_pass[0].status == "PASSED"


def test_generic_agent_runner_end_to_end_mock(db_session):
    runner = GenericAgentRunner(db_session, provider_type="mock", model_name="mock-generic-v1")
    
    scenario = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "test_e2e_mock_sentiment",
        "name": "E2E Sentiment Mock Test",
        "domain": "sentiment",
        "evaluation_mode": "GENERIC",
        "input": {"text": "I absolutely love this product!"},
        "assertions": [
            {
                "type": "json_schema",
                "schema_def": {
                    "type": "object",
                    "required": ["sentiment", "score"],
                    "properties": {
                        "sentiment": {"type": "string"},
                        "score": {"type": "number"}
                    }
                }
            },
            {
                "type": "json_path_equals",
                "path": "sentiment",
                "expected": "POSITIVE"
            },
            {
                "type": "execution_completed"
            }
        ]
    }

    result = runner.run_generic_scenario(scenario)
    assert result["status"] == "PASSED"
    assert len(result["check_results"]) == 3
    assert all(c["status"] == "PASSED" for c in result["check_results"])
    assert result["turns"] >= 1
    assert result["trace_events_count"] >= 1

