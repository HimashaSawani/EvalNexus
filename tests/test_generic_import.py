import pytest
import json
import uuid
import datetime

from backend.database.models import Run, ScenarioRun, TraceEvent, CheckResult, EvaluationRevision
from backend.scenarios.offline_bundle import (
    import_colab_results,
    import_generic_colab_results,
    GENERIC_RESULT_SCHEMA
)


def test_generic_colab_sentiment_import(db_session):
    test_run_id = f"test_colab_import_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": GENERIC_RESULT_SCHEMA,
        "run_id": test_run_id,
        "scenario_id": "generic_sentiment_positive",
        "domain": "sentiment",
        "model_name": "Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)",
        "provider_type": "colab_offline",
        "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "final_answer": json.dumps({
            "sentiment": "POSITIVE",
            "score": 0.95,
            "confidence": 0.98,
            "summary": "The delivery was lightning fast and the quality exceeded all my expectations! Highly recommended."
        }, indent=2),
        "duration_ms": 3318,
        "status": "COMPLETED",
        "traces": [],
        "check_results": [
            {"check_name": "Fabricated Check", "status": "PASSED"}
        ]
    }

    # 1. First import
    res = import_colab_results(db_session, payload)
    assert res["status"] == "SUCCESS"
    assert res["run_id"] == test_run_id
    assert res["evaluation_mode"] == "GENERIC"
    assert res["passed"] is True
    assert res["passed_checks"] == 3
    assert res["total_checks"] == 3

    # Verify DB records
    run_rec = db_session.query(Run).filter(Run.id == test_run_id).first()
    assert run_rec is not None
    assert run_rec.status == "COMPLETED"
    assert run_rec.passed_scenarios == 1

    scen_run = db_session.query(ScenarioRun).filter(ScenarioRun.run_id == test_run_id).first()
    assert scen_run is not None
    assert scen_run.status == "PASSED"

    # Verify AGENT_RESPONSE trace event
    traces = db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == scen_run.id).all()
    assert len(traces) == 1
    assert traces[0].event_type == "AGENT_RESPONSE"

    # 2. Duplicate detection without overwrite
    with pytest.raises(ValueError, match="Duplicate import detected"):
        import_colab_results(db_session, payload, overwrite=False)

    # 3. Overwrite allowed
    res_overwrite = import_colab_results(db_session, payload, overwrite=True)
    assert res_overwrite["status"] == "SUCCESS"


def test_independent_server_side_evaluation_rejects_client_truth(db_session):
    """Verifies that client check_results are ignored and server independently evaluates assertions."""
    test_run_id = f"test_untrusted_client_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": GENERIC_RESULT_SCHEMA,
        "run_id": test_run_id,
        "scenario_id": "generic_sentiment_positive",
        "domain": "sentiment",
        "model_name": "Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)",
        "provider_type": "colab_offline",
        # Intentionally invalid final answer that violates both schema and path assertions
        "final_answer": "Plain unparseable string with no JSON",
        "duration_ms": 1200,
        "status": "PASSED",
        # Fabricated client assertions claiming 100% success
        "check_results": [
            {"check_name": "Fake Check 1", "status": "PASSED"},
            {"check_name": "Fake Check 2", "status": "PASSED"}
        ]
    }

    res = import_colab_results(db_session, payload)
    assert res["passed"] is False  # Server MUST fail the run!
    assert res["failed_checks"] >= 1

    run_rec = db_session.query(Run).filter(Run.id == test_run_id).first()
    assert run_rec.passed_scenarios == 0
    assert run_rec.failed_scenarios == 1


def test_generic_colab_travel_import_with_traces(db_session):
    test_run_id = f"test_colab_travel_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": GENERIC_RESULT_SCHEMA,
        "run_id": test_run_id,
        "scenario_id": "generic_travel_planner",
        "domain": "travel",
        "model_name": "Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)",
        "provider_type": "colab_offline",
        "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "final_answer": json.dumps({
            "destination": "Kyoto",
            "days": 3,
            "status": "PLANNED",
            "itinerary": {
                "days": [
                    {"day": 1, "activity": "Historic Shrines", "weather": "Sunny"},
                    {"day": 2, "activity": "Zen Gardens", "weather": "Sunny"},
                    {"day": 3, "activity": "Traditional Markets", "weather": "Sunny"}
                ]
            }
        }, indent=2),
        "duration_ms": 4200,
        "status": "COMPLETED",
        "traces": [
            {
                "seq": 1,
                "event_type": "TOOL_EXECUTION",
                "tool": "check_weather",
                "arguments": {"city": "Kyoto"},
                "result": {"temperature_c": 22, "condition": "Sunny"},
                "duration_ms": 15
            },
            {
                "seq": 2,
                "event_type": "TOOL_EXECUTION",
                "tool": "lookup_poi",
                "arguments": {"city": "Kyoto", "category": "historic"},
                "result": {"pois": [{"name": "Kyoto Historic Shrine"}]},
                "duration_ms": 15
            }
        ]
    }

    res = import_colab_results(db_session, payload)
    assert res["status"] == "SUCCESS"
    assert res["passed"] is True
    assert res["passed_checks"] == 6  # All 6 assertions in generic_travel_planner
    assert res["total_checks"] == 6

    # Verify traces were seeded
    scen_run = db_session.query(ScenarioRun).filter(ScenarioRun.run_id == test_run_id).first()
    db_traces = db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == scen_run.id).all()
    assert len(db_traces) == 3  # 2 tool traces + 1 AGENT_RESPONSE
    tool_names = [t.tool_name for t in db_traces if t.tool_name]
    assert "check_weather" in tool_names
    assert "lookup_poi" in tool_names

