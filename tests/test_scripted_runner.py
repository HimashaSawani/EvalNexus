import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent, CheckResult, ScenarioRun
from backend.runner.scripted_runner import ScriptedRunner


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_eligible_refund_scripted_scenario(db_session):
    with open("scenarios/eligible_refund_scenario.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = ScriptedRunner(db_session)
    result = runner.run_scenario(scenario_data)

    # Verify overall scenario result
    assert result["status"] == "PASSED"
    assert result["trace_events_count"] >= 4  # USER_MESSAGE, get_order, check_refund, request_refund

    # Verify check results
    check_dict = {chk["check_name"]: chk["status"] for chk in result["check_results"]}
    assert check_dict["OWNERSHIP"] == "PASSED"
    assert check_dict["ELIGIBILITY"] == "PASSED"
    assert check_dict["DUPLICATE"] == "PASSED"
    assert check_dict["STATE"] == "PASSED"
    assert check_dict["COMPLETION"] == "PASSED"

    # Verify database persistence
    scenario_run_id = result["scenario_run_id"]
    refund_record = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == scenario_run_id,
        RefundRequest.order_id == "ord_deliv_8891"
    ).first()

    assert refund_record is not None
    assert refund_record.amount_cents == 7450
    assert refund_record.status == "REFUND_REQUESTED"

    # Verify sequential traces logged
    traces = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == scenario_run_id
    ).order_by(TraceEvent.seq_num).all()

    assert len(traces) >= 4
    event_types = [t.event_type for t in traces]
    assert "USER_MESSAGE" in event_types
    assert "TOOL_CALL" in event_types


def test_ineligible_refund_scripted_scenario(db_session):
    with open("scenarios/ineligible_expired_scenario.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = ScriptedRunner(db_session)
    result = runner.run_scenario(scenario_data)

    assert result["status"] == "PASSED"  # The test passed because it correctly rejected the expired refund

    # Verify that NO refund record was created
    scenario_run_id = result["scenario_run_id"]
    refund_record = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == scenario_run_id
    ).first()

    assert refund_record is None
