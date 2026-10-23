import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import Run, QueueJob, utc_now
from backend.worker import QueueWorker


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


def test_claim_next_job_atomic(db_session):
    """Verifies atomic job claiming by a worker."""
    worker = QueueWorker(worker_id="test_worker_1")

    # Insert a QUEUED job
    run = Run(
        id="run_q1",
        agent_version_id="agent_v2_improved",
        provider_type="mock",
        model_name="mock-v1",
        status="QUEUED",
        total_scenarios=1
    )
    job = QueueJob(
        id="job_q1",
        run_id="run_q1",
        status="QUEUED",
        agent_version_id="agent_v2_improved",
        provider_type="mock",
        model_name="mock-v1",
        scenario_ids=["eligible_refund_scenario.json"],
        is_paid=0
    )
    db_session.add(run)
    db_session.add(job)
    db_session.commit()

    # Claim job
    claimed = worker.claim_next_job(db_session)
    assert claimed is not None
    assert claimed.id == "job_q1"
    assert claimed.status == "RUNNING"
    assert claimed.worker_id == "test_worker_1"
    assert claimed.heartbeat_at is not None

    # Next attempt by another worker should find nothing
    worker2 = QueueWorker(worker_id="test_worker_2")
    claimed2 = worker2.claim_next_job(db_session)
    assert claimed2 is None


def test_reap_abandoned_mock_job(db_session):
    """Verifies that abandoned mock jobs without heartbeat are reaped safely."""
    worker = QueueWorker(worker_id="test_worker_reaper")

    run = Run(id="run_mock_abandoned", agent_version_id="v1", status="RUNNING", total_scenarios=1)
    job = QueueJob(
        id="job_mock_abandoned",
        run_id="run_mock_abandoned",
        status="RUNNING",
        agent_version_id="v1",
        provider_type="mock",
        model_name="mock-v1",
        scenario_ids=["eligible_refund_scenario.json"],
        is_paid=0,
        heartbeat_at=utc_now()
    )
    db_session.add(run)
    db_session.add(job)
    db_session.commit()

    # With cutoff 0s, it's considered abandoned
    reaped = worker.reap_abandoned_jobs(db_session, heartbeat_cutoff_sec=-1.0)
    assert reaped == 1

    db_session.refresh(job)
    db_session.refresh(run)
    assert job.status == "FAILED"
    assert run.status == "FAILED"
    assert "Abandoned job reaped" in job.error_message


def test_reap_abandoned_paid_job_never_auto_reruns(db_session):
    """CRITICAL: Paid executions must never automatically rerun when abandoned."""
    worker = QueueWorker(worker_id="test_worker_reaper")

    run = Run(id="run_paid_abandoned", agent_version_id="v1", status="RUNNING", total_scenarios=1)
    job = QueueJob(
        id="job_paid_abandoned",
        run_id="run_paid_abandoned",
        status="RUNNING",
        agent_version_id="v1",
        provider_type="gemini",
        model_name="gemini-flash-lite-latest",
        scenario_ids=["eligible_refund_scenario.json"],
        is_paid=1,  # Paid execution!
        heartbeat_at=utc_now()
    )
    db_session.add(run)
    db_session.add(job)
    db_session.commit()

    reaped = worker.reap_abandoned_jobs(db_session, heartbeat_cutoff_sec=-1.0)
    assert reaped == 1

    db_session.refresh(job)
    db_session.refresh(run)
    assert job.status == "FAILED"
    assert run.status == "FAILED"
    assert "Automatic retry disabled to prevent duplicate billing" in job.error_message


def test_job_cancellation_honored(db_session):
    """Verifies that a cancelled job immediately ceases processing remaining scenarios."""
    run = Run(id="run_cancel_test", agent_version_id="v1", status="CANCELLED", total_scenarios=3)
    job = QueueJob(
        id="job_cancel_test",
        run_id="run_cancel_test",
        status="CANCELLED",
        agent_version_id="v1",
        provider_type="mock",
        model_name="mock-v1",
        scenario_ids=["scen_1", "scen_2", "scen_3"],
        is_paid=0
    )
    db_session.add(run)
    db_session.add(job)
    db_session.commit()

    worker = QueueWorker(worker_id="test_cancel_worker")
    # execute_job should immediately notice CANCELLED status
    worker.execute_job("job_cancel_test")

    db_session.refresh(job)
    db_session.refresh(run)
    assert job.status == "CANCELLED"
    assert run.status == "CANCELLED"
