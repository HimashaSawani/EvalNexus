import os
import time
import uuid
import threading
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import QueueJob, Run, RefundRequest, utc_now
from backend.worker import QueueWorker
from backend.domain.refund_service import RefundService, RefundDomainError
from backend.agent.agent_loop import CancellationToken


@pytest.fixture
def isolated_db_setup():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield Session, session
    session.close()


def test_concurrent_worker_claiming_no_race(isolated_db_setup):
    """
    Spawns multiple worker threads racing to claim a single queued job.
    Each worker uses its own DB session (as in real multi-process/multi-worker execution).
    Exactly one worker must succeed; all others must receive None without crashing.
    """
    SessionMaker, main_session = isolated_db_setup
    now = utc_now()
    run = Run(
        id="run_race_01",
        agent_version_id="agent_v2_improved",
        provider_type="mock",
        model_name="mock-deterministic-v1",
        is_mock=1,
        status="QUEUED",
        created_at=now
    )
    job = QueueJob(
        id="job_race_01",
        run_id="run_race_01",
        agent_version_id="agent_v2_improved",
        provider_type="mock",
        model_name="mock-deterministic-v1",
        scenario_ids=["eligible_refund_scenario.json"],
        status="QUEUED",
        created_at=now
    )
    main_session.add(run)
    main_session.add(job)
    main_session.commit()

    workers = [QueueWorker(worker_id=f"worker_race_{i}") for i in range(5)]
    claimed = []
    lock = threading.Lock()

    def claim_job(w: QueueWorker):
        worker_session = SessionMaker()
        try:
            c = w.claim_next_job(worker_session)
            if c:
                with lock:
                    claimed.append((w.worker_id, c.id))
        finally:
            worker_session.close()

    threads = [threading.Thread(target=claim_job, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 1 worker must have claimed the job
    assert len(claimed) == 1
    main_session.refresh(job)
    assert job.status == "RUNNING"
    assert job.worker_id == claimed[0][0]


def test_cancellation_token_blocks_late_writes(isolated_db_setup):
    """
    Verifies that a cancelled token causes request_refund to rollback immediately
    and throw TimeoutError without creating any database records.
    """
    import datetime
    SessionMaker, main_session = isolated_db_setup
    clock = datetime.datetime.fromisoformat("2026-10-23T12:00:00")
    cancel_token = CancellationToken()

    # Pre-cancel token (simulating timeout in background thread)
    cancel_token.cancel()

    from backend.database.models import Customer, Order
    cust = Customer(id="cust_cancel_01", scenario_run_id="scen_cancel_01", name="Test", email="test@test.com")
    ord1 = Order(
        id="ord_cancel_01",
        scenario_run_id="scen_cancel_01",
        customer_id="cust_cancel_01",
        status="DELIVERED",
        total_amount_cents=5000,
        delivery_date=clock - datetime.timedelta(days=2)
    )
    main_session.add(cust)
    main_session.add(ord1)
    main_session.commit()

    service = RefundService(
        db=main_session,
        scenario_run_id="scen_cancel_01",
        fixed_clock=clock,
        cancel_token=cancel_token
    )

    with pytest.raises(TimeoutError) as excinfo:
        service.request_refund(
            session_customer_id="cust_cancel_01",
            order_id="ord_cancel_01",
            amount_cents=5000,
            operation_key="opk_cancel_test"
        )

    assert "Late write blocked" in str(excinfo.value)

    # Ensure zero refunds created
    refunds = main_session.query(RefundRequest).filter(
        RefundRequest.scenario_run_id == "scen_cancel_01"
    ).all()
    assert len(refunds) == 0


def test_paid_abandoned_job_never_replayed(isolated_db_setup):
    """
    Verifies that a paid job that lost heartbeat is marked FAILED and NEVER reset to QUEUED.
    """
    import datetime
    SessionMaker, main_session = isolated_db_setup
    now = utc_now()
    stale_time = now - datetime.timedelta(seconds=60)

    job = QueueJob(
        id="job_paid_stale_01",
        run_id="run_paid_stale_01",
        agent_version_id="agent_v2_improved",
        provider_type="gemini",
        model_name="gemini-flash-lite-latest",
        scenario_ids=["eligible_refund_scenario.json"],
        status="RUNNING",
        is_paid=1,
        heartbeat_at=stale_time,
        created_at=stale_time
    )
    run = Run(
        id="run_paid_stale_01",
        agent_version_id="agent_v2_improved",
        provider_type="gemini",
        model_name="gemini-flash-lite-latest",
        is_mock=0,
        status="RUNNING",
        created_at=stale_time
    )
    main_session.add(run)
    main_session.add(job)
    main_session.commit()

    worker = QueueWorker(worker_id="worker_reaper")
    reaped = worker.reap_abandoned_jobs(main_session, heartbeat_cutoff_sec=30.0)

    assert reaped == 1
    main_session.refresh(job)
    main_session.refresh(run)

    assert job.status == "FAILED"
    assert run.status == "FAILED"
    assert "Automatic retry disabled" in job.error_message
