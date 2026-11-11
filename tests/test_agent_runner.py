import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent, CheckResult, Run
from backend.runner.agent_runner import AgentWindTunnelRunner


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
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


def test_tool_timeout_interrupts_waiting(db_session):
    import time
    from backend.agent.agent_loop import AgentLoop
    from backend.runner.trace_logger import TraceLogger
    from backend.agent.provider import MockToolCallingProvider

    trace_logger = TraceLogger(db_session, "test_timeout_run")
    provider = MockToolCallingProvider()

    # Mock service where get_order hangs/sleeps
    class HangingService:
        def get_order(self, session_customer_id, order_id):
            time.sleep(0.3)
            return {"status": "SUCCESS"}

    loop = AgentLoop(
        service=HangingService(),
        trace_logger=trace_logger,
        provider=provider,
        tool_timeout_sec=0.1  # Set short 100ms timeout
    )

    t0 = time.time()
    tool_res, err = loop._execute_tool_with_timeout(
        customer_id="c1",
        tool_name="get_order",
        arguments={"order_id": "ord_hang"}
    )
    elapsed = time.time() - t0

    # Must interrupt waiting around 0.1s, well before 0.3s sleep finishes
    assert tool_res is None
    assert "Gateway Timeout" in err
    assert "timed out after 0.1s" in err
    assert elapsed < 0.25


def test_provider_error_marks_checks_not_evaluated(db_session):
    """
    Verifies Requirement 4 & 5:
    When a provider setup/network failure occurs (e.g. 404 Model Not Found or 401 Auth error):
    1. Scenario run status is classified as PROVIDER_ERROR.
    2. All checks are marked NOT_EVALUATED (not failed).
    3. Elapsed duration is measured (>0ms).
    4. Tokens is preserved as None (unknown).
    """
    from backend.agent.provider import BaseLLMProvider

    class FailingProvider(BaseLLMProvider):
        provider_type = "gemini"
        model_name = "gemini-nonexistent"

        def generate(self, messages, tools, temperature=0.0):
            raise RuntimeError("Error code: 404 - [{'error': {'code': 404, 'message': 'models/gemini-nonexistent is not found'}}]")

    with open("scenarios/dev/scen_norm_01_delivered_5d.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db=db_session, provider=FailingProvider())
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v1_baseline")

    assert result["status"] == "PROVIDER_ERROR"
    assert result["duration_ms"] >= 0
    assert result["tokens"] is None  # Preserved as unknown
    assert result["turns"] == 0

    # All checks must be NOT_EVALUATED
    for cr in result["check_results"]:
        assert cr["status"] == "NOT_EVALUATED"
        assert "Provider setup failure" in cr["message"]


def test_disallowed_tool_failure_is_not_marked_passed(db_session):
    from backend.agent.provider import BaseLLMProvider, LLMResponse

    class DisallowedToolProvider(BaseLLMProvider):
        provider_type = "mock"
        model_name = "mock-policy-violation"

        def generate(self, messages, tools, temperature=0.0):
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_refund",
                    "type": "function",
                    "function": {
                        "name": "request_refund",
                        "arguments": '{"order_id":"ord_deliv_8891","amount_cents":7450,"operation_key":"op_1"}'
                    }
                }],
                prompt_tokens=10,
                completion_tokens=5
            )

    scenario_path = "scenarios/eligible_refund_scenario.json"
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    run_id = "run_policy_allowlist"
    db_session.add(Run(
        id=run_id,
        agent_version_id="agent_v2_improved",
        execution_config={
            "max_turns": 3,
            "max_tool_calls": 2,
            "max_tokens_budget": 1500,
            "scenario_timeout_sec": 30.0,
            "allowed_tools": ["get_order", "check_refund_eligibility"]
        },
        status="RUNNING",
        total_scenarios=1
    ))
    db_session.commit()

    runner = AgentWindTunnelRunner(db_session, provider=DisallowedToolProvider())
    result = runner.run_agent_scenario(
        scenario_data,
        agent_version_id="agent_v2_improved",
        run_id=run_id
    )

    assert result["status"] == "FAILED"
    assert result["check_results"][-1]["check_name"] == "COMPLETION"
    assert result["check_results"][-1]["status"] == "FAILED"
    assert db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == result["scenario_run_id"]
    ).count() == 0
    trace_types = [t.event_type for t in db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == result["scenario_run_id"]
    ).order_by(TraceEvent.seq_num).all()]
    assert trace_types == ["USER_MESSAGE", "MODEL_CALL"]


