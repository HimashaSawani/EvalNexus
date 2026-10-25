import os
import uuid
import datetime
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.database.connection import Base
from backend.database.models import (
    Run, QueueJob, ScenarioRun, Customer, Order, RefundRequest,
    TraceEvent, CheckResult, utc_now
)
from backend.worker import QueueWorker
from backend.runner.evaluator import DeterministicEvaluator
from backend.domain.refund_service import RefundService, RefundDomainError
from backend.agent.agent_loop import CancellationToken


@pytest.fixture
def isolated_db_path(tmp_path):
    db_file = tmp_path / f"test_ops_{uuid.uuid4().hex[:8]}.db"
    url = f"sqlite:///{db_file}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    
    # Configure WAL and busy_timeout
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=5000"))
        conn.commit()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield engine, session, db_file

    session.close()
    engine.dispose()
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass


def test_fresh_database_creation_and_constraints(isolated_db_path):
    """Test 4: Verify fresh database creation, table schemas, and unique constraints."""
    engine, session, db_file = isolated_db_path

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    expected_tables = {
        "runs", "queue_jobs", "scenario_runs", "customers",
        "orders", "refund_requests", "trace_events", "check_results"
    }
    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"

    # Check WAL mode
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert res.lower() == "wal"

        timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        assert timeout == 5000

    # Check unique constraints on refund_requests
    unique_constraints = inspector.get_unique_constraints("refund_requests")
    uc_names = {uc["name"] for uc in unique_constraints if uc["name"]}
    assert "uq_order_scenario_refund" in uc_names
    assert "uq_opkey_scenario_refund" in uc_names


def test_worker_abandoned_job_reaping_and_interrupted_scenarios(isolated_db_path):
    """Test 2: Verify abandoned job detection, marking active scenario attempts as INTERRUPTED."""
    engine, session, _ = isolated_db_path
    worker = QueueWorker(worker_id="reaper_test_worker")

    run_id = f"run_test_{uuid.uuid4().hex[:6]}"
    scen_run_id = f"scen_test_{uuid.uuid4().hex[:6]}"
    job_id = f"job_test_{uuid.uuid4().hex[:6]}"

    run = Run(id=run_id, agent_version_id="agent_v2_improved", status="RUNNING", total_scenarios=1)
    job = QueueJob(
        id=job_id,
        run_id=run_id,
        status="RUNNING",
        agent_version_id="agent_v2_improved",
        provider_type="mock",
        model_name="mock-deterministic-v1",
        scenario_ids=["eligible_refund_scenario.json"],
        is_paid=0,
        heartbeat_at=utc_now() - datetime.timedelta(seconds=60)
    )
    scen_run = ScenarioRun(
        id=scen_run_id,
        run_id=run_id,
        scenario_version_id="scen_normal_eligible_01",
        status="RUNNING"
    )
    session.add(run)
    session.add(job)
    session.add(scen_run)
    session.commit()

    # Reap with cutoff 30s
    reaped = worker.reap_abandoned_jobs(session, heartbeat_cutoff_sec=30.0)
    assert reaped == 1

    session.refresh(job)
    session.refresh(run)
    session.refresh(scen_run)

    assert job.status == "FAILED"
    assert run.status == "FAILED"
    assert "Abandoned job reaped" in job.error_message
    assert scen_run.status == "INTERRUPTED"
    assert scen_run.finished_at is not None


def test_paid_gemini_job_abandonment_never_auto_reruns(isolated_db_path):
    """Test 2: CRITICAL - Paid Gemini/OpenAI executions must never automatically replay when abandoned."""
    engine, session, _ = isolated_db_path
    worker = QueueWorker(worker_id="paid_reaper_worker")

    run_id = f"run_paid_{uuid.uuid4().hex[:6]}"
    job_id = f"job_paid_{uuid.uuid4().hex[:6]}"

    run = Run(id=run_id, agent_version_id="agent_v2_improved", status="RUNNING", total_scenarios=1, is_mock=0)
    job = QueueJob(
        id=job_id,
        run_id=run_id,
        status="RUNNING",
        agent_version_id="agent_v2_improved",
        provider_type="gemini",
        model_name="gemini-1.5-flash",
        scenario_ids=["eligible_refund_scenario.json"],
        is_paid=1,
        heartbeat_at=utc_now() - datetime.timedelta(seconds=60)
    )
    session.add(run)
    session.add(job)
    session.commit()

    reaped = worker.reap_abandoned_jobs(session, heartbeat_cutoff_sec=30.0)
    assert reaped == 1

    session.refresh(job)
    session.refresh(run)
    assert job.status == "FAILED"
    assert run.status == "FAILED"
    assert "Automatic retry disabled to prevent duplicate billing" in job.error_message


def test_honest_indeterminate_evaluation_on_unresolved_writes(isolated_db_path):
    """Test 3: Verify honest INDETERMINATE results where background write task timed out and outcome is uncertain."""
    engine, session, _ = isolated_db_path

    run_id = f"run_indet_{uuid.uuid4().hex[:6]}"
    scen_run_id = f"scen_indet_{uuid.uuid4().hex[:6]}"
    order_id = "ord_test_9999"

    run = Run(id=run_id, agent_version_id="v1", status="RUNNING", total_scenarios=1)
    scen_run = ScenarioRun(id=scen_run_id, run_id=run_id, scenario_version_id="scen_01", status="RUNNING")
    customer = Customer(id="cust_1", scenario_run_id=scen_run_id, name="Test Cust", email="t@example.com")
    order = Order(
        id=order_id,
        scenario_run_id=scen_run_id,
        customer_id="cust_1",
        status="DELIVERED",
        total_amount_cents=5000,
        currency="USD",
        delivery_date=utc_now() - datetime.timedelta(days=2)
    )
    session.add_all([run, scen_run, customer, order])
    session.commit()

    # Simulate an unresolved write task (tool timed out and thread is still in-flight)
    unresolved_tasks = [
        {
            "tool_name": "request_refund",
            "is_write": True,
            "status": "STILL_UNRESOLVED"
        }
    ]

    evaluator = DeterministicEvaluator(session, scen_run_id)
    checks = evaluator.evaluate(
        customer_id="cust_1",
        order_id=order_id,
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED"},
        execution_error="Tool Call Timeout",
        unresolved_tasks=unresolved_tasks
    )

    state_check = next((c for c in checks if c.check_name == "STATE"), None)
    assert state_check is not None
    assert state_check.status == "INDETERMINATE"
    assert "State check indeterminate" in state_check.message
    assert state_check.evidence["unresolved_writes"][0]["tool_name"] == "request_refund"


def test_cancellation_token_blocks_late_write_and_rolls_back(isolated_db_path):
    """Test 3: Verify CancellationToken actively blocks writes and ensures session rollback."""
    engine, session, _ = isolated_db_path

    scen_run_id = f"scen_cancel_{uuid.uuid4().hex[:6]}"
    order_id = "ord_cancel_123"

    now = utc_now()
    order = Order(
        id=order_id,
        scenario_run_id=scen_run_id,
        customer_id="cust_1",
        status="DELIVERED",
        total_amount_cents=3000,
        currency="USD",
        delivery_date=now - datetime.timedelta(days=2)
    )
    session.add(order)
    session.commit()

    token = CancellationToken()
    service = RefundService(session, scenario_run_id=scen_run_id, fixed_clock=now, cancel_token=token)

    # Cancel token before write attempt
    token.cancel()

    with pytest.raises(Exception) as exc_info:
        service.request_refund(
            session_customer_id="cust_1",
            order_id=order_id,
            amount_cents=3000,
            operation_key="op_test_cancel"
        )
    assert "Late write blocked" in str(exc_info.value) or "timed out" in str(exc_info.value)

    # Confirm no record was committed to DB
    refunds = session.query(RefundRequest).filter(RefundRequest.scenario_run_id == scen_run_id).all()
    assert len(refunds) == 0


def test_idempotency_payload_mismatch_rejected(isolated_db_path):
    """Test 3: Verify that reusing operation_key with differing payload raises 409 conflict."""
    engine, session, _ = isolated_db_path

    scen_run_id = f"scen_idem_{uuid.uuid4().hex[:6]}"
    order_id = "ord_idem_100"
    now = utc_now()

    order = Order(
        id=order_id,
        scenario_run_id=scen_run_id,
        customer_id="cust_1",
        status="DELIVERED",
        total_amount_cents=5000,
        currency="USD",
        delivery_date=now - datetime.timedelta(days=2)
    )
    session.add(order)
    session.commit()

    service = RefundService(session, scenario_run_id=scen_run_id, fixed_clock=now)

    # First refund succeeds
    res1 = service.request_refund(
        session_customer_id="cust_1",
        order_id=order_id,
        amount_cents=5000,
        operation_key="op_idem_test_key"
    )
    assert res1["status"] == "SUCCESS"
    assert res1["idempotent_replay"] is False

    # Second refund with identical key & payload returns idempotent replay
    res2 = service.request_refund(
        session_customer_id="cust_1",
        order_id=order_id,
        amount_cents=5000,
        operation_key="op_idem_test_key"
    )
    assert res2["status"] == "SUCCESS"
    assert res2["idempotent_replay"] is True

    # Third refund with same key but DIFFERENT amount is rejected with 409
    with pytest.raises(RefundDomainError) as exc_info:
        service.request_refund(
            session_customer_id="cust_1",
            order_id=order_id,
            amount_cents=2500,  # Different amount!
            operation_key="op_idem_test_key"
        )
    assert exc_info.value.code == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    assert exc_info.value.status_code == 409
