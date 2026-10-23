import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import Customer, Order, RefundRequest
from backend.domain.refund_service import RefundService, RefundDomainError


@pytest.fixture
def db_session():
    # In-memory SQLite for rapid, isolated testing
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def fixed_clock():
    return datetime.datetime(2026, 10, 23, 12, 0, 0)


@pytest.fixture
def setup_data(db_session, fixed_clock):
    scenario_run_id = "test_run_001"

    # Customer 1 (Alice)
    alice = Customer(
        id="cust_alice",
        scenario_run_id=scenario_run_id,
        name="Alice",
        email="alice@test.com"
    )
    # Customer 2 (Eve)
    eve = Customer(
        id="cust_eve",
        scenario_run_id=scenario_run_id,
        name="Eve",
        email="eve@test.com"
    )
    db_session.add_all([alice, eve])

    # Order 1: Delivered 4 days ago (Eligible)
    order_eligible = Order(
        id="ord_eligible",
        scenario_run_id=scenario_run_id,
        customer_id="cust_alice",
        status="DELIVERED",
        total_amount_cents=5000,
        currency="USD",
        delivery_date=fixed_clock - datetime.timedelta(days=4)
    )
    # Order 2: Delivered 20 days ago (Expired)
    order_expired = Order(
        id="ord_expired",
        scenario_run_id=scenario_run_id,
        customer_id="cust_alice",
        status="DELIVERED",
        total_amount_cents=3000,
        currency="USD",
        delivery_date=fixed_clock - datetime.timedelta(days=20)
    )
    # Order 3: Cancelled (Eligible)
    order_cancelled = Order(
        id="ord_cancelled",
        scenario_run_id=scenario_run_id,
        customer_id="cust_alice",
        status="CANCELLED",
        total_amount_cents=2500,
        currency="USD",
        delivery_date=None
    )
    # Order 4: Eve's order
    order_eve = Order(
        id="ord_eve",
        scenario_run_id=scenario_run_id,
        customer_id="cust_eve",
        status="DELIVERED",
        total_amount_cents=9900,
        currency="USD",
        delivery_date=fixed_clock - datetime.timedelta(days=2)
    )

    db_session.add_all([order_eligible, order_expired, order_cancelled, order_eve])
    db_session.commit()

    return {
        "scenario_run_id": scenario_run_id,
        "alice_id": "cust_alice",
        "eve_id": "cust_eve"
    }


def test_ownership_enforcement(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)

    # Alice querying her own order succeeds
    order = service.get_order("cust_alice", "ord_eligible")
    assert order["order_id"] == "ord_eligible"

    # Alice trying to access Eve's order raises 403 UNAUTHORIZED_ORDER_ACCESS
    with pytest.raises(RefundDomainError) as exc_info:
        service.get_order("cust_alice", "ord_eve")
    assert exc_info.value.code == "UNAUTHORIZED_ORDER_ACCESS"
    assert exc_info.value.status_code == 403


def test_eligibility_delivered_within_14_days(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)
    res = service.check_refund_eligibility("cust_alice", "ord_eligible")
    assert res["eligible"] is True
    assert res["reason_code"] == "DELIVERED_WITHIN_WINDOW"
    assert res["max_refundable_cents"] == 5000


def test_eligibility_delivered_expired(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)
    res = service.check_refund_eligibility("cust_alice", "ord_expired")
    assert res["eligible"] is False
    assert res["reason_code"] == "RETURN_WINDOW_EXPIRED"
    assert res["max_refundable_cents"] == 0


def test_eligibility_cancelled_order(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)
    res = service.check_refund_eligibility("cust_alice", "ord_cancelled")
    assert res["eligible"] is True
    assert res["reason_code"] == "CANCELLED_ORDER_ELIGIBLE"
    assert res["max_refundable_cents"] == 2500


def test_request_refund_success_and_idempotency(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)

    # First request
    res1 = service.request_refund(
        session_customer_id="cust_alice",
        order_id="ord_eligible",
        amount_cents=5000,
        operation_key="op_test_123"
    )
    assert res1["status"] == "SUCCESS"
    assert res1["amount_cents"] == 5000
    assert res1["refund_status"] == "REFUND_REQUESTED"
    assert res1["idempotent_replay"] is False

    # Second request with identical operation_key -> Idempotent replay, same result
    res2 = service.request_refund(
        session_customer_id="cust_alice",
        order_id="ord_eligible",
        amount_cents=5000,
        operation_key="op_test_123"
    )
    assert res2["status"] == "SUCCESS"
    assert res2["idempotent_replay"] is True

    # Exactly 1 record in database
    refunds = db_session.query(RefundRequest).filter(
        RefundRequest.order_id == "ord_eligible",
        RefundRequest.scenario_run_id == setup_data["scenario_run_id"]
    ).all()
    assert len(refunds) == 1


def test_duplicate_refund_with_different_opkey_rejected(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)

    # First request
    service.request_refund(
        session_customer_id="cust_alice",
        order_id="ord_eligible",
        amount_cents=5000,
        operation_key="op_first"
    )

    # Second request with DIFFERENT operation_key -> Rejected as duplicate
    with pytest.raises(RefundDomainError) as exc_info:
        service.request_refund(
            session_customer_id="cust_alice",
            order_id="ord_eligible",
            amount_cents=5000,
            operation_key="op_second"
        )
    assert "INELIGIBLE_ALREADY_REFUNDED" in exc_info.value.code or "DUPLICATE" in exc_info.value.code


def test_operation_key_payload_conflict_rejected(db_session, setup_data, fixed_clock):
    service = RefundService(db_session, setup_data["scenario_run_id"], fixed_clock)

    # First request: $50 on ord_eligible
    service.request_refund(
        session_customer_id="cust_alice",
        order_id="ord_eligible",
        amount_cents=5000,
        operation_key="op_shared_key"
    )

    # Second request: Reuse same op_shared_key on ord_cancelled ($25) -> Must be rejected with 409
    with pytest.raises(RefundDomainError) as exc_info:
        service.request_refund(
            session_customer_id="cust_alice",
            order_id="ord_cancelled",
            amount_cents=2500,
            operation_key="op_shared_key"
        )
    assert exc_info.value.code == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    assert exc_info.value.status_code == 409

