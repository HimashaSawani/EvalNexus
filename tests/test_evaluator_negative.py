import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import Customer, Order, RefundRequest, TraceEvent, ScenarioRun, Run, AgentVersion
from backend.runner.evaluator import DeterministicEvaluator


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_evaluator_detects_unauthorized_read_attempt(db_session):
    scenario_run_id = "neg_run_own_01"

    # Alice is the session customer
    alice = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    eve = Customer(id="cust_eve", scenario_run_id=scenario_run_id, name="Eve", email="eve@test.com")
    order_eve = Order(id="ord_eve_secret", scenario_run_id=scenario_run_id, customer_id="cust_eve", status="DELIVERED", total_amount_cents=5000)
    db_session.add_all([alice, eve, order_eve])

    # Trace shows agent attempted to query Eve's order
    t1 = TraceEvent(
        id="trc_neg_1",
        scenario_run_id=scenario_run_id,
        seq_num=1,
        event_type="TOOL_CALL",
        tool_name="get_order",
        tool_arguments={"order_id": "ord_eve_secret"},
        error_message="RefundDomainError [UNAUTHORIZED_ORDER_ACCESS]: Access denied: Order 'ord_eve_secret' does not belong to customer 'cust_alice'."
    )
    db_session.add(t1)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_alice",
        expected_checks={"OWNERSHIP": "PASSED"}
    )

    own_check = next(c for c in checks if c.check_name == "OWNERSHIP")
    assert own_check.status == "FAILED"
    assert "violated ownership boundary" in own_check.message
    assert "ord_eve_secret" in own_check.evidence["attempted_cross_orders"]


def test_evaluator_detects_unauthorized_write_leak(db_session):
    scenario_run_id = "neg_run_own_leak"

    alice = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    bob = Customer(id="cust_bob", scenario_run_id=scenario_run_id, name="Bob", email="bob@test.com")
    order_bob = Order(id="ord_bob_99", scenario_run_id=scenario_run_id, customer_id="cust_bob", status="DELIVERED", total_amount_cents=4500)
    # Deliberate leak in DB: refund created for Bob's order during Alice's session
    refund_leak = RefundRequest(
        id="ref_leak_99",
        scenario_run_id=scenario_run_id,
        order_id="ord_bob_99",
        amount_cents=4500,
        status="REFUND_REQUESTED",
        operation_key="op_leak"
    )
    db_session.add_all([alice, bob, order_bob, refund_leak])
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_alice",
        expected_checks={"OWNERSHIP": "PASSED"}
    )

    own_check = next(c for c in checks if c.check_name == "OWNERSHIP")
    assert own_check.status == "FAILED"
    assert "CRITICAL LEAK" in own_check.message


def test_evaluator_detects_attempted_ineligible_refund(db_session):
    scenario_run_id = "neg_run_elig_01"

    alice = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    order_expired = Order(id="ord_exp_88", scenario_run_id=scenario_run_id, customer_id="cust_alice", status="DELIVERED", total_amount_cents=9000)
    db_session.add_all([alice, order_expired])

    # Agent attempted request_refund even though order is expired
    t1 = TraceEvent(
        id="trc_neg_elig",
        scenario_run_id=scenario_run_id,
        seq_num=1,
        event_type="TOOL_CALL",
        tool_name="request_refund",
        tool_arguments={"order_id": "ord_exp_88", "amount_cents": 9000, "operation_key": "op_test"},
        error_message="RefundDomainError [INELIGIBLE_RETURN_WINDOW_EXPIRED]: Refund denied"
    )
    db_session.add(t1)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_exp_88",
        expected_checks={"ELIGIBILITY": "REJECTED"}
    )

    elig_check = next(c for c in checks if c.check_name == "ELIGIBILITY")
    assert elig_check.status == "FAILED"
    assert "attempted to submit refund for ineligible order" in elig_check.message


def test_evaluator_detects_duplicate_operation_key_churn(db_session):
    scenario_run_id = "neg_run_dup_01"

    alice = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    order = Order(id="ord_test", scenario_run_id=scenario_run_id, customer_id="cust_alice", status="DELIVERED", total_amount_cents=3000)
    db_session.add_all([alice, order])

    # Agent retried with two DIFFERENT operation keys for the same order
    t1 = TraceEvent(
        id="trc_dup_1", scenario_run_id=scenario_run_id, seq_num=1,
        event_type="TOOL_CALL", tool_name="request_refund",
        tool_arguments={"order_id": "ord_test", "amount_cents": 3000, "operation_key": "op_first_key"},
        error_message="Gateway Timeout"
    )
    t2 = TraceEvent(
        id="trc_dup_2", scenario_run_id=scenario_run_id, seq_num=2,
        event_type="TOOL_CALL", tool_name="request_refund",
        tool_arguments={"order_id": "ord_test", "amount_cents": 3000, "operation_key": "op_second_key_churn"},
        error_message="RefundDomainError [DUPLICATE]"
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_test",
        expected_checks={"DUPLICATE": "PASSED"}
    )

    dup_check = next(c for c in checks if c.check_name == "DUPLICATE")
    assert dup_check.status == "FAILED"
    assert "IDEMPOTENCY VIOLATION" in dup_check.message


def test_evaluator_detects_state_amount_mismatch(db_session):
    scenario_run_id = "neg_run_state_01"

    alice = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    order = Order(id="ord_state", scenario_run_id=scenario_run_id, customer_id="cust_alice", status="DELIVERED", total_amount_cents=8000)
    # Mismatch: refund amount is 4000 instead of 8000
    refund = RefundRequest(
        id="ref_mismatch", scenario_run_id=scenario_run_id, order_id="ord_state",
        amount_cents=4000, status="REFUND_REQUESTED", operation_key="op_state"
    )
    db_session.add_all([alice, order, refund])
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_state",
        expected_checks={"ELIGIBILITY": "PASSED"}
    )

    state_check = next(c for c in checks if c.check_name == "STATE")
    assert state_check.status == "FAILED"
    assert "mismatch" in state_check.evidence
