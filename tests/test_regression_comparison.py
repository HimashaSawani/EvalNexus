import json
import uuid
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import (
    Run,
    ScenarioRun,
    TraceEvent,
    CheckResult,
    AgentVersion,
    ScenarioVersion,
    utc_now
)
from backend.runner.regression_comparator import RegressionComparator, calculate_percentile


@pytest.fixture
def client():
    return TestClient(app)


def test_percentile_calculation():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    p50 = calculate_percentile(vals, 50)
    assert p50 == 30.0
    p90 = calculate_percentile(vals, 90)
    assert p90 == 46.0


def test_regression_comparison_engine(client):
    db = SessionLocal()
    try:
        # Create test agent versions if not exists
        for ag_id in ["reg_agent_v1", "reg_agent_v2"]:
            if not db.query(AgentVersion).filter(AgentVersion.id == ag_id).first():
                db.add(AgentVersion(
                    id=ag_id,
                    name=ag_id,
                    system_prompt="Test prompt"
                ))

        # Create test scenario versions
        for s_idx in range(1, 4):
            sid = f"reg_scen_{s_idx}"
            if not db.query(ScenarioVersion).filter(ScenarioVersion.id == sid).first():
                db.add(ScenarioVersion(
                    id=sid,
                    name=sid,
                    category="NORMAL",
                    fixed_clock=utc_now(),
                    initial_data={"customer": {"id": "c1"}, "orders": []},
                    customer_messages=["Hello"],
                    expected_checks={"ownership": "PASS"}
                ))
        db.commit()

        # Run 1: Baseline
        run_1_id = f"run_base_{uuid.uuid4().hex[:6]}"
        run_1 = Run(
            id=run_1_id,
            agent_version_id="reg_agent_v1",
            provider_type="mock",
            model_name="mock-model",
            is_mock=1,
            status="COMPLETED",
            total_scenarios=3,
            passed_scenarios=2,
            failed_scenarios=1
        )
        db.add(run_1)

        # Run 2: Candidate
        run_2_id = f"run_cand_{uuid.uuid4().hex[:6]}"
        run_2 = Run(
            id=run_2_id,
            agent_version_id="reg_agent_v2",
            provider_type="mock",
            model_name="mock-model",
            is_mock=1,
            status="COMPLETED",
            total_scenarios=3,
            passed_scenarios=2,
            failed_scenarios=1
        )
        db.add(run_2)
        db.commit()

        # Scenario 1: Baseline PASSED, Candidate FAILED -> REGRESSION
        sr1_a = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_1_id, scenario_version_id="reg_scen_1", status="PASSED", duration_ms=100)
        sr1_b = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_2_id, scenario_version_id="reg_scen_1", status="FAILED", duration_ms=150)

        # Scenario 2: Baseline FAILED, Candidate PASSED -> IMPROVEMENT
        sr2_a = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_1_id, scenario_version_id="reg_scen_2", status="FAILED", duration_ms=200)
        sr2_b = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_2_id, scenario_version_id="reg_scen_2", status="PASSED", duration_ms=180)

        # Scenario 3: Baseline PASSED, Candidate PASSED -> PARITY
        sr3_a = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_1_id, scenario_version_id="reg_scen_3", status="PASSED", duration_ms=120)
        sr3_b = ScenarioRun(id=f"sr_{uuid.uuid4().hex[:6]}", run_id=run_2_id, scenario_version_id="reg_scen_3", status="PASSED", duration_ms=110)

        db.add_all([sr1_a, sr1_b, sr2_a, sr2_b, sr3_a, sr3_b])
        db.commit()

        # Add traces for tool call behavioral comparison
        t1 = TraceEvent(id=f"tr_{uuid.uuid4().hex[:6]}", scenario_run_id=sr1_a.id, seq_num=1, event_type="TOOL_CALL", tool_name="get_order", token_usage={"total": 100}, cost_estimate=500)
        t2 = TraceEvent(id=f"tr_{uuid.uuid4().hex[:6]}", scenario_run_id=sr1_b.id, seq_num=1, event_type="TOOL_CALL", tool_name="check_refund_eligibility", token_usage={"total": 120}, cost_estimate=600)
        db.add_all([t1, t2])
        db.commit()

        # Test Comparator class directly
        comparator = RegressionComparator(db)
        comparison = comparator.compare(run_1_id, run_2_id)

        assert comparison["verdict"] == "REGRESSION_DETECTED"
        assert comparison["summary"]["regressions"] == 1
        assert comparison["summary"]["improvements"] == 1
        assert comparison["summary"]["parity"] == 1
        assert "INSUFFICIENT_SAMPLE_SIZE" in comparison["statistical_confidence"]
        assert "cost_disclaimer" in comparison
        assert comparison["token_and_cost"]["tokens_delta"] == 20

        # Test API endpoint POST /api/regression/compare
        resp = client.post("/api/regression/compare", json={
            "baseline_run_id": run_1_id,
            "candidate_run_id": run_2_id
        })
        assert resp.status_code == 200
        api_data = resp.json()
        assert api_data["verdict"] == "REGRESSION_DETECTED"
        assert len(api_data["scenarios"]) == 3

        # Test API endpoint GET /api/regression/report/{b}/{c}
        resp = client.get(f"/api/regression/report/{run_1_id}/{run_2_id}")
        assert resp.status_code == 200
        report = resp.json()
        assert report["verdict"] == "REGRESSION_DETECTED"
        assert "attachment" in resp.headers.get("Content-Disposition", "")

    finally:
        db.close()
