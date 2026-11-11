import json
import uuid
import datetime
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal, Base, engine
from backend.database.models import Run, ScenarioRun, TraceEvent, CheckResult
from backend.scenarios.offline_bundle import (
    export_scenario_bundle,
    export_scenario_bundle_to_file,
    import_colab_results,
    import_colab_results_from_file,
    SCENARIO_BUNDLE_SCHEMA,
    EVALUATION_RESULT_SCHEMA
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


# -------------------------------------------------------------
# 1. Export Bundle Unit Tests
# -------------------------------------------------------------

def test_export_scenario_bundle_schema_and_contents(db_session):
    bundle = export_scenario_bundle(db=db_session)
    assert bundle["schema_version"] == SCENARIO_BUNDLE_SCHEMA
    assert "bundle_id" in bundle
    assert bundle["source_platform"] == "EvalNexus"
    assert bundle["total_scenarios"] >= 30
    assert len(bundle["tools"]) == 3

    tool_names = [t["function"]["name"] for t in bundle["tools"]]
    assert "get_order" in tool_names
    assert "check_refund_eligibility" in tool_names
    assert "request_refund" in tool_names

    # Assert zero secrets or tokens
    bundle_str = json.dumps(bundle)
    assert "api_key" not in bundle_str.lower()
    assert "bearer " not in bundle_str.lower()
    assert "auth_token" not in bundle_str.lower()
    assert "password" not in bundle_str.lower()

    # Check limits
    limits = bundle["execution_limits"]
    assert limits["max_turns"] == 6
    assert limits["max_tool_calls"] == 10
    assert limits["max_tokens_budget"] == 15000


def test_export_scenario_bundle_filtered(db_session):
    requested_ids = ["scen_norm_01_delivered_5d", "scen_norm_02_delivered_1d"]
    bundle = export_scenario_bundle(scenario_ids=requested_ids, db=db_session)
    assert bundle["total_scenarios"] == 2
    assert [s["id"] for s in bundle["scenarios"]] == requested_ids

    # Unknown scenario error
    with pytest.raises(ValueError, match="Scenarios not found"):
        export_scenario_bundle(scenario_ids=["non_existent_scen_999"], db=db_session)


def test_export_scenario_bundle_to_file(tmp_path, db_session):
    out_file = str(tmp_path / "test_bundle.json")
    res_path = export_scenario_bundle_to_file(out_file, scenario_ids=["scen_norm_01_delivered_5d"], db=db_session)
    assert res_path == out_file

    with open(out_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["schema_version"] == SCENARIO_BUNDLE_SCHEMA
    assert loaded["total_scenarios"] == 1


# -------------------------------------------------------------
# 2. Result Import Unit Tests
# -------------------------------------------------------------

def test_import_colab_results_lifecycle(db_session):
    batch_run_id = f"test_colab_run_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": EVALUATION_RESULT_SCHEMA,
        "bundle_id": "test_bundle_001",
        "batch_run_id": batch_run_id,
        "model_name": "Qwen2.5-1.5B-Instruct",
        "agent_version_id": "agent_v1_baseline",
        "results": [
            {
                "scenario_id": "scen_norm_01_delivered_5d",
                "status": "COMPLETED",
                "duration_ms": 1200,
                "prompt_tokens": 140,
                "completion_tokens": 45,
                "refunds": [
                    {
                        "order_id": "ord_norm_01",
                        "amount_cents": 7450,
                        "operation_key": f"op_{batch_run_id}"
                    }
                ],
                "traces": [
                    {"seq": 1, "event_type": "USER_MESSAGE", "duration_ms": 5},
                    {"seq": 2, "event_type": "TOOL_CALL", "tool": "get_order", "arguments": {"order_id": "ord_norm_01"}, "duration_ms": 25},
                    {"seq": 3, "event_type": "TOOL_RESULT", "tool": "get_order", "result": {"status": "DELIVERED", "total_amount_cents": 7450, "delivery_date": "2026-10-18T12:00:00"}, "duration_ms": 5},
                    {"seq": 4, "event_type": "TOOL_CALL", "tool": "check_refund_eligibility", "arguments": {"order_id": "ord_norm_01"}, "duration_ms": 20},
                    {"seq": 5, "event_type": "TOOL_RESULT", "tool": "check_refund_eligibility", "result": {"eligible": True, "max_refundable_cents": 7450}, "duration_ms": 5},
                    {"seq": 6, "event_type": "TOOL_CALL", "tool": "request_refund", "arguments": {"order_id": "ord_norm_01", "amount_cents": 7450, "operation_key": f"op_{batch_run_id}"}, "duration_ms": 30},
                    {"seq": 7, "event_type": "TOOL_RESULT", "tool": "request_refund", "result": {"status": "REFUND_REQUESTED", "operation_key": f"op_{batch_run_id}"}, "duration_ms": 5},
                    {"seq": 8, "event_type": "MODEL_CALL", "result": "Refund processed.", "duration_ms": 120}
                ]
            }
        ]
    }

    summary = import_colab_results(db_session, payload)
    assert summary["status"] == "SUCCESS"
    assert summary["run_id"] == batch_run_id
    assert summary["total_scenarios"] == 1
    assert summary["passed_scenarios"] == 1
    assert summary["failed_scenarios"] == 0

    # Query DB to verify persistence
    run = db_session.query(Run).filter(Run.id == batch_run_id).first()
    assert run is not None
    assert run.provider_type == "colab_offline"
    assert run.is_mock == 0
    assert run.status == "COMPLETED"
    assert run.passed_scenarios == 1

    # Check scenario run and check results
    scen_runs = db_session.query(ScenarioRun).filter(ScenarioRun.run_id == batch_run_id).all()
    assert len(scen_runs) == 1
    assert scen_runs[0].status == "PASSED"

    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == scen_runs[0].id).all()
    assert len(checks) >= 4
    for c in checks:
        assert c.status == "PASSED"

    # Traces
    traces = db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == scen_runs[0].id).all()
    assert len(traces) == 8


def test_import_colab_results_duplicate_prevention(db_session):
    batch_run_id = f"test_colab_dup_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": EVALUATION_RESULT_SCHEMA,
        "bundle_id": "test_bundle_002",
        "batch_run_id": batch_run_id,
        "model_name": "Qwen2.5-1.5B-Instruct",
        "results": [
            {
                "scenario_id": "scen_norm_01_delivered_5d",
                "status": "COMPLETED",
                "duration_ms": 500,
                "traces": []
            }
        ]
    }

    # First import: Success
    res1 = import_colab_results(db_session, payload)
    assert res1["status"] == "SUCCESS"

    # Duplicate import without overwrite: Fails
    with pytest.raises(ValueError, match="Duplicate import detected"):
        import_colab_results(db_session, payload, overwrite=False)

    # Duplicate import with overwrite=True: Succeeds
    res2 = import_colab_results(db_session, payload, overwrite=True)
    assert res2["status"] == "SUCCESS"


def test_import_colab_results_validation(db_session):
    # Invalid schema version
    with pytest.raises(Exception):
        import_colab_results(db_session, {
            "schema_version": "invalid_schema",
            "bundle_id": "b1",
            "batch_run_id": "r1",
            "model_name": "m1",
            "results": []
        })

    # Unknown scenario ID
    with pytest.raises(ValueError, match="Unknown scenario ID"):
        import_colab_results(db_session, {
            "schema_version": EVALUATION_RESULT_SCHEMA,
            "bundle_id": "b1",
            "batch_run_id": f"r_{uuid.uuid4().hex[:6]}",
            "model_name": "m1",
            "results": [{"scenario_id": "non_existent_scen_xyz", "traces": []}]
        })


# -------------------------------------------------------------
# 3. FastAPI API Endpoints Integration Tests
# -------------------------------------------------------------

def test_api_scenarios_bundle_export_get(client):
    res = client.get("/api/scenarios/bundle/export")
    assert res.status_code == 200
    data = res.json()
    assert data["schema_version"] == SCENARIO_BUNDLE_SCHEMA
    assert data["total_scenarios"] >= 30


def test_api_scenarios_bundle_export_post(client):
    req_body = {
        "scenario_ids": ["scen_norm_01_delivered_5d"],
        "agent_version_id": "agent_v1_baseline"
    }
    res = client.post("/api/scenarios/bundle/export", json=req_body)
    assert res.status_code == 200
    data = res.json()
    assert data["total_scenarios"] == 1
    assert data["scenarios"][0]["id"] == "scen_norm_01_delivered_5d"


def test_api_runs_import_colab(client):
    batch_run_id = f"api_colab_run_{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": EVALUATION_RESULT_SCHEMA,
        "bundle_id": "bundle_api_test",
        "batch_run_id": batch_run_id,
        "model_name": "Qwen2.5-1.5B-Instruct",
        "agent_version_id": "agent_v1_baseline",
        "results": [
            {
                "scenario_id": "scen_norm_01_delivered_5d",
                "status": "COMPLETED",
                "duration_ms": 950,
                "prompt_tokens": 110,
                "completion_tokens": 35,
                "refunds": [
                    {
                        "order_id": "ord_norm_01",
                        "amount_cents": 7450,
                        "operation_key": f"op_{batch_run_id}"
                    }
                ],
                "traces": [
                    {"seq": 1, "event_type": "USER_MESSAGE", "duration_ms": 5},
                    {"seq": 2, "event_type": "TOOL_CALL", "tool": "get_order", "arguments": {"order_id": "ord_norm_01"}, "duration_ms": 20},
                    {"seq": 3, "event_type": "TOOL_RESULT", "tool": "get_order", "result": {"status": "DELIVERED", "total_amount_cents": 7450, "delivery_date": "2026-10-18T12:00:00"}, "duration_ms": 5},
                    {"seq": 4, "event_type": "TOOL_CALL", "tool": "check_refund_eligibility", "arguments": {"order_id": "ord_norm_01"}, "duration_ms": 20},
                    {"seq": 5, "event_type": "TOOL_RESULT", "tool": "check_refund_eligibility", "result": {"eligible": True, "max_refundable_cents": 7450}, "duration_ms": 5},
                    {"seq": 6, "event_type": "TOOL_CALL", "tool": "request_refund", "arguments": {"order_id": "ord_norm_01", "amount_cents": 7450, "operation_key": f"op_{batch_run_id}"}, "duration_ms": 30},
                    {"seq": 7, "event_type": "TOOL_RESULT", "tool": "request_refund", "result": {"status": "REFUND_REQUESTED", "operation_key": f"op_{batch_run_id}"}, "duration_ms": 5},
                    {"seq": 8, "event_type": "MODEL_CALL", "result": "Done", "duration_ms": 50}
                ]
            }
        ]
    }

    # 1. Post import
    res = client.post("/api/runs/import-colab", json=payload)
    assert res.status_code == 200, f"Import failed: {res.text}"
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["run_id"] == batch_run_id
    assert data["passed_scenarios"] == 1

    # 2. Check Run appears in GET /api/runs (Dashboard view)
    list_res = client.get("/api/runs")
    assert list_res.status_code == 200
    runs = list_res.json()
    assert isinstance(runs, list)
    matching_run = next((r for r in runs if r["id"] == batch_run_id), None)
    assert matching_run is not None
    assert matching_run["provider_type"] == "colab_offline"
    assert matching_run["status"] == "COMPLETED"

    # 3. Check Run Details in GET /api/runs/{run_id}
    detail_res = client.get(f"/api/runs/{batch_run_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["run_id"] == batch_run_id
    assert detail["passed_scenarios"] == 1
    assert len(detail["scenario_runs"]) == 1
    sr = detail["scenario_runs"][0]
    assert sr["status"] == "PASSED"
    assert sr["refund_created"] is True
    assert len(sr["checks"]) >= 4
    assert len(sr["traces"]) == 8

    # 4. Check Markdown Export in GET /api/runs/{run_id}/export
    exp_res = client.get(f"/api/runs/{batch_run_id}/export?format=markdown")
    assert exp_res.status_code == 200
    assert "EvalNexus Run Report" in exp_res.text
    assert batch_run_id in exp_res.text

    # 5. Duplicate import via API returns 409
    dup_res = client.post("/api/runs/import-colab", json=payload)
    assert dup_res.status_code == 409

    # 6. Malformed payload returns 422
    bad_res = client.post("/api/runs/import-colab", json={"invalid": True})
    assert bad_res.status_code == 422
