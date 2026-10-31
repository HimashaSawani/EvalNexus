import uuid
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, WorkerNode, QueueJob, Run, AgentVersion, utc_now
from backend.distributed.node_manager import (
    register_worker_node,
    worker_heartbeat,
    list_worker_nodes,
    claim_job_atomically,
    release_job,
    reap_stale_workers_and_jobs
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Pre-populate base agent version
    av = AgentVersion(
        id="ag_test_dist",
        name="Distributed Test Agent",
        system_prompt="Test prompt",
        model_name="mock-model"
    )
    session.add(av)
    session.commit()

    yield session
    session.close()


def test_node_registration_and_heartbeat(db_session):
    node = register_worker_node(
        db=db_session,
        node_id="worker_alpha",
        hostname="host-101",
        ip_address="192.168.1.10",
        max_concurrency=3,
        capabilities=["mock", "workflow"]
    )
    assert node.id == "worker_alpha"
    assert node.status == "ONLINE"
    assert node.max_concurrency == 3

    # List nodes
    nodes = list_worker_nodes(db_session)
    assert len(nodes) == 1
    assert nodes[0]["id"] == "worker_alpha"
    assert nodes[0]["status"] == "ONLINE"

    # Pulse heartbeat
    hb_ok = worker_heartbeat(db_session, "worker_alpha")
    assert hb_ok is True

    # Unknown worker heartbeat returns False
    assert worker_heartbeat(db_session, "unknown_worker") is False


def test_atomic_job_claiming_and_backpressure(db_session):
    worker = register_worker_node(
        db=db_session,
        node_id="worker_bravo",
        max_concurrency=2
    )

    # Create 3 jobs in queue
    job_ids = []
    for i in range(3):
        run = Run(id=f"run_job_{i}", agent_version_id="ag_test_dist")
        db_session.add(run)
        job = QueueJob(
            id=f"job_{i}",
            run_id=run.id,
            status="QUEUED",
            agent_version_id="ag_test_dist",
            model_name="mock-model",
            scenario_ids=["scen_1"]
        )
        db_session.add(job)
        job_ids.append(f"job_{i}")
    db_session.commit()

    # Claim job 1
    c1 = claim_job_atomically(db_session, worker_id="worker_bravo", max_concurrency=2)
    assert c1 is not None
    assert c1.id == "job_0"
    assert c1.status == "RUNNING"
    assert c1.worker_id == "worker_bravo"

    # Claim job 2
    c2 = claim_job_atomically(db_session, worker_id="worker_bravo", max_concurrency=2)
    assert c2 is not None
    assert c2.id == "job_1"
    assert c2.status == "RUNNING"

    # Worker now reached max_concurrency (2). Attempting to claim job 3 should yield None (backpressure)
    c3 = claim_job_atomically(db_session, worker_id="worker_bravo", max_concurrency=2)
    assert c3 is None

    # Check worker status transitioned to BUSY
    db_session.refresh(worker)
    assert worker.status == "BUSY"
    assert worker.active_jobs_count == 2

    # Release job 1 as completed
    release_job(db_session, job_id="job_0", worker_id="worker_bravo", final_status="COMPLETED")
    db_session.refresh(worker)
    assert worker.status == "ONLINE"
    assert worker.active_jobs_count == 1
    assert worker.total_completed_jobs == 1

    # Now job 3 can be claimed
    c3 = claim_job_atomically(db_session, worker_id="worker_bravo", max_concurrency=2)
    assert c3 is not None
    assert c3.id == "job_2"


def test_crash_recovery_and_reaping(db_session):
    worker = register_worker_node(
        db=db_session,
        node_id="worker_charlie",
        max_concurrency=4
    )

    run = Run(id="run_crash_test", agent_version_id="ag_test_dist")
    db_session.add(run)
    job = QueueJob(
        id="job_crash_1",
        run_id=run.id,
        status="RUNNING",
        agent_version_id="ag_test_dist",
        model_name="mock-model",
        scenario_ids=["scen_1"],
        worker_id="worker_charlie",
        retry_count=0
    )
    db_session.add(job)
    db_session.commit()

    # Simulate worker crash: set heartbeat to 100 seconds ago
    stale_time = utc_now() - datetime.timedelta(seconds=100)
    worker.heartbeat_at = stale_time
    job.heartbeat_at = stale_time
    db_session.commit()

    # Run reaper
    stats = reap_stale_workers_and_jobs(db_session, heartbeat_timeout_sec=45, max_retries=2)
    assert stats["reaped_workers"] == 1
    assert stats["reaped_jobs"] == 1

    db_session.refresh(worker)
    assert worker.status == "OFFLINE"

    db_session.refresh(job)
    assert job.status == "QUEUED"
    assert job.worker_id is None
    assert job.retry_count == 1
    assert "Re-queued" in job.error_message

    # Simulate repeated crash until max retries exceeded
    job.status = "RUNNING"
    job.worker_id = "worker_charlie"
    job.retry_count = 2  # Already at max_retries
    job.heartbeat_at = stale_time
    db_session.commit()

    stats2 = reap_stale_workers_and_jobs(db_session, heartbeat_timeout_sec=45, max_retries=2)
    assert stats2["reaped_jobs"] == 1

    db_session.refresh(job)
    assert job.status == "FAILED"
    assert "exceeded maximum retries" in job.error_message
