import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent, CheckResult
from backend.runner.agent_runner import AgentWindTunnelRunner


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_agent_runner_eligible_flow(db_session):
    with open("scenarios/eligible_refund_scenario.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v1_baseline")

    assert result["status"] == "PASSED"
    assert result["tool_calls"] == 3  # get_order, check_refund_eligibility, request_refund
    assert "REFUND_REQUESTED" in result["final_answer"]

    # Evaluator checks
    checks = {c["check_name"]: c["status"] for c in result["check_results"]}
    assert checks["OWNERSHIP"] == "PASSED"
    assert checks["ELIGIBILITY"] == "PASSED"
    assert checks["DUPLICATE"] == "PASSED"
    assert checks["STATE"] == "PASSED"
    assert checks["COMPLETION"] == "PASSED"

    # Database state verification
    refund = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == result["scenario_run_id"],
        RefundRequest.order_id == "ord_deliv_8891"
    ).first()
    assert refund is not None
    assert refund.amount_cents == 7450


def test_agent_runner_ineligible_expired_flow(db_session):
    with open("scenarios/ineligible_expired_scenario.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v1_baseline")

    assert result["status"] == "PASSED"
    assert result["tool_calls"] == 2  # get_order, check_refund_eligibility (did not call request_refund)
    assert "not eligible" in result["final_answer"].lower()

    # Zero refund records
    refunds = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == result["scenario_run_id"]
    ).all()
    assert len(refunds) == 0


def test_fault_timeout_after_write(db_session):
    with open("scenarios/fault_timeout_after_write.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v2_improved")

    # DB record was committed despite timeout
    refund = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == result["scenario_run_id"],
        RefundRequest.order_id == "ord_deliv_timeout_9901"
    ).first()
    assert refund is not None

    # Trace events show FAULT_INJECTED
    traces = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == result["scenario_run_id"]
    ).all()
    event_types = [t.event_type for t in traces]
    assert "FAULT_INJECTED" in event_types

    # Information Leakage Audit:
    # Ensure the final answer does NOT leak internal fault strings like "TIMEOUT_AFTER_WRITE" or "write committed"
    assert "write committed" not in result["final_answer"].lower()
    assert "timeout_after_write" not in result["final_answer"].lower()

    # Honest user message acknowledging the timeout and explaining idempotency key
    assert "timeout" in result["final_answer"].lower()
    assert "duplicate" in result["final_answer"].lower()


def test_missing_credentials_fails_clearly():
    from backend.agent.provider import resolve_provider
    import os

    # Ensure no key
    old_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(RuntimeError) as exc_info:
            resolve_provider(provider_type="openai")
        assert "no valid API key was found" in str(exc_info.value)
        assert "strictly refuses to silently substitute a mock" in str(exc_info.value)
    finally:
        if old_key:
            os.environ["OPENAI_API_KEY"] = old_key

