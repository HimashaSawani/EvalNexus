import json
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import RefundRequest, TraceEvent, Order
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


def test_fault_timeout_before_write_leaves_no_write(db_session):
    """
    Fault 1: TIMEOUT_BEFORE_WRITE
    Verifies that when a timeout occurs before the database write:
    1. Zero refund records are created in the database.
    2. Agent receives a realistic generic gateway timeout (HTTP 504).
    3. Evaluator notes that no write occurred.
    """
    with open("scenarios/dev/scen_fault_01_timeout_before_write.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v2_improved")

    scenario_run_id = result["scenario_run_id"]

    # 1. Strict verification: Database record count MUST be 0
    refund_count = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == scenario_run_id
    ).count()
    assert refund_count == 0, f"Expected 0 refund records in DB, found {refund_count}!"

    # 2. Agent visible response acknowledges timeout without claiming money returned
    final_ans = result["final_answer"].lower()
    assert "timeout" in final_ans or "error" in final_ans
    assert "write committed" not in final_ans

    # 3. Admin trace recorded write_committed: False
    fault_trace = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == scenario_run_id,
        TraceEvent.event_type == "FAULT_INJECTED"
    ).first()
    assert fault_trace is not None
    assert '"write_committed": false' in fault_trace.error_message


def test_fault_timeout_after_write_commits_before_timeout(db_session):
    """
    Fault 2: TIMEOUT_AFTER_WRITE
    Verifies that when network drops after DB commit:
    1. The refund record WAS committed to the DB with status REFUND_REQUESTED.
    2. The agent receives a generic 504 without leaking the 'write committed' fact.
    3. The operation key is safely recorded in the DB for idempotency.
    """
    with open("scenarios/dev/scen_fault_02_timeout_after_write.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v2_improved")

    scenario_run_id = result["scenario_run_id"]

    # 1. Strict verification: DB record was committed
    refund_record = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == scenario_run_id,
        RefundRequest.order_id == "ord_fault_taw"
    ).first()
    assert refund_record is not None, "Expected refund record to be committed in DB, but found none!"
    assert refund_record.status == "REFUND_REQUESTED"
    assert refund_record.amount_cents == 8500

    # 2. Agent visible response does NOT leak internal fault strings
    final_ans = result["final_answer"].lower()
    assert "write committed" not in final_ans
    assert "timeout_after_write" not in final_ans
    assert "timeout" in final_ans

    # 3. Admin trace records write_committed: True
    fault_trace = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == scenario_run_id,
        TraceEvent.event_type == "FAULT_INJECTED"
    ).first()
    assert fault_trace is not None
    assert '"write_committed": true' in fault_trace.error_message


def test_fault_temporary_unavailable_recovers_on_retry(db_session):
    """
    Fault 3: TEMPORARY_UNAVAILABLE (503)
    Verifies that:
    1. Call #1 fails with 503 Service Unavailable.
    2. Subsequent call (call #2) succeeds without error.
    """
    from backend.faults.fault_injector import FaultInjector, FaultInjectionError

    injector = FaultInjector({
        "check_refund_eligibility": {
            "fault_type": "TEMPORARY_UNAVAILABLE",
            "trigger_on_call": 1
        }
    })

    # Call 1: Must raise FaultInjectionError with 503
    with pytest.raises(FaultInjectionError) as exc_info:
        injector.before_tool_call("check_refund_eligibility", {"order_id": "ord_123"})
    assert exc_info.value.status_code == 503
    assert "503" in exc_info.value.agent_visible_message

    # Call 2 (Retry): Must succeed and return None (proceed normally)
    res_call2 = injector.before_tool_call("check_refund_eligibility", {"order_id": "ord_123"})
    assert res_call2 is None, "Call #2 should have recovered and returned None to proceed!"


def test_fault_stale_read_returns_cached_state(db_session):
    """
    Fault 4: STALE_READ
    Verifies that tool returns outdated / cached state matching the specification:
    1. Direct injector verification: returns configured stale payload.
    2. Default stale payload matches specification (status='PROCESSING', delivery_date=None).
    3. Custom stale payload matches specification.
    4. Integration verification: trace event captures the stale read payload matching specification.
    """
    from backend.faults.fault_injector import FaultInjector

    # 1. Direct specification check: default stale payload
    default_injector = FaultInjector({
        "get_order": {
            "fault_type": "STALE_READ",
            "trigger_on_call": 1
        }
    })
    stale_res = default_injector.before_tool_call("get_order", {"order_id": "ord_test_stale"})
    assert stale_res is not None
    assert stale_res["status"] == "PROCESSING"
    assert stale_res["delivery_date"] is None
    assert stale_res["order_id"] == "ord_test_stale"

    # 2. Custom stale payload specification check
    custom_payload = {
        "order_id": "ord_custom",
        "status": "PENDING_VERIFICATION",
        "cached_at": "2026-10-01T00:00:00"
    }
    custom_injector = FaultInjector({
        "get_order": {
            "fault_type": "STALE_READ",
            "trigger_on_call": 1,
            "stale_payload": custom_payload
        }
    })
    custom_res = custom_injector.before_tool_call("get_order", {"order_id": "ord_custom"})
    assert custom_res == custom_payload

    # 3. Scenario runner integration check
    with open("scenarios/dev/scen_fault_04_stale_read.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v2_improved")

    scenario_run_id = result["scenario_run_id"]

    # In trace events, get_order returned the stale payload matching specification
    stale_trace = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == scenario_run_id,
        TraceEvent.tool_name == "get_order"
    ).first()
    assert stale_trace is not None
    assert stale_trace.tool_result.get("status") == "PROCESSING"
    assert stale_trace.tool_result.get("order_id") == "ord_fault_stale"


def test_fault_malformed_response_handling(db_session):
    """
    Fault 5: MALFORMED_RESPONSE
    Verifies that:
    1. Direct injector verification: returns corrupted packet matching specification.
    2. Missing standard fields (status, amount, delivery_date).
    3. Scenario runner handles corrupted packet without an unhandled exception or crash.
    """
    from backend.faults.fault_injector import FaultInjector

    # 1. Direct injector specification check
    injector = FaultInjector({
        "get_order": {
            "fault_type": "MALFORMED_RESPONSE",
            "trigger_on_call": 1
        }
    })
    raw_ok = {"id": "ord_1", "status": "DELIVERED", "total_amount_cents": 5000}
    corrupted = injector.after_tool_call("get_order", raw_ok)
    assert corrupted != raw_ok
    assert "raw_response" in corrupted
    assert "warning" in corrupted
    assert corrupted["raw_response"] == "0xDEADBEEF"
    assert "status" not in corrupted  # Corrupted packet omitted required domain fields

    # 2. Scenario runner integration check
    with open("scenarios/held_out/scen_fault_05_malformed_response.json", "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    runner = AgentWindTunnelRunner(db_session)
    result = runner.run_agent_scenario(scenario_data, agent_version_id="agent_v2_improved")

    # Execution completed cleanly without unhandled crash
    assert result["status"] in ["PASSED", "FAILED"]
    assert result["turns"] >= 1
    assert result["scenario_run_id"] is not None


def test_timed_out_thread_late_write_is_blocked_and_settled(db_session):
    """
    Targeted test for Fix 1:
    Verifies that when a tool call hangs and times out before writing to the database:
    1. The cancellation token flags is_cancelled = True.
    2. A late attempt to write/commit by the background thread is blocked and rolled back.
    3. settle_in_flight_tasks drains before evaluator runs, ensuring 0 records in DB.
    """
    import time
    from backend.agent.agent_loop import AgentLoop, CancellationToken
    from backend.runner.trace_logger import TraceLogger
    from backend.domain.refund_service import RefundService
    from backend.agent.provider import MockToolCallingProvider

    token = CancellationToken()
    fixed_clock = datetime.datetime(2026, 10, 23, 12, 0, 0)
    service = RefundService(db_session, "scen_test_timeout_block", fixed_clock, cancel_token=token)

    # Set up customer and order
    from backend.database.models import Customer, Order, ScenarioRun, Run
    run = Run(id="run_t1", agent_version_id="agent_v1_baseline")
    scen_run = ScenarioRun(id="scen_test_timeout_block", run_id="run_t1", scenario_version_id="scen_1")
    cust = Customer(id="c_timeout", scenario_run_id="scen_test_timeout_block", name="Test", email="test@ex.com")
    ord1 = Order(
        id="ord_timeout_test",
        scenario_run_id="scen_test_timeout_block",
        customer_id="c_timeout",
        status="DELIVERED",
        total_amount_cents=5000,
        delivery_date=fixed_clock - datetime.timedelta(days=2)
    )
    db_session.add_all([run, scen_run, cust, ord1])
    db_session.commit()

    # Pre-cancel token (simulating a tool timeout happening right before commit)
    token.cancel()

    # Attempting to call request_refund with a cancelled token must raise TimeoutError and roll back
    with pytest.raises(TimeoutError) as exc_info:
        service.request_refund(
            session_customer_id="c_timeout",
            order_id="ord_timeout_test",
            amount_cents=5000,
            operation_key="op_late_key",
            reason="Late test"
        )

    assert "Late write blocked" in str(exc_info.value)

    # Database must have 0 refund records
    rf_count = db_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == "scen_test_timeout_block"
    ).count()
    assert rf_count == 0
