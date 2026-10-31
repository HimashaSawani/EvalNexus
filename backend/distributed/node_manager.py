import os
import socket
import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_, and_

from backend.database.models import WorkerNode, QueueJob, utc_now


def register_worker_node(
    db: Session,
    node_id: Optional[str] = None,
    hostname: Optional[str] = None,
    ip_address: Optional[str] = None,
    max_concurrency: int = 4,
    capabilities: Optional[List[str]] = None
) -> WorkerNode:
    """Registers a worker node or refreshes an existing node's registration."""
    if not node_id:
        node_id = f"worker_{socket.gethostname()}_{os.getpid()}"
    if not hostname:
        hostname = socket.gethostname()
    if not ip_address:
        ip_address = "127.0.0.1"
    if capabilities is None:
        capabilities = ["mock", "custom_http", "scripted", "workflow"]

    node = db.query(WorkerNode).filter(WorkerNode.id == node_id).first()
    now = utc_now()

    if node:
        node.hostname = hostname
        node.ip_address = ip_address
        node.status = "ONLINE"
        node.max_concurrency = max_concurrency
        node.capabilities = capabilities
        node.heartbeat_at = now
        node.updated_at = now
    else:
        node = WorkerNode(
            id=node_id,
            hostname=hostname,
            ip_address=ip_address,
            status="ONLINE",
            active_jobs_count=0,
            max_concurrency=max_concurrency,
            capabilities=capabilities,
            heartbeat_at=now,
            created_at=now,
            updated_at=now
        )
        db.add(node)

    db.commit()
    db.refresh(node)
    return node


def worker_heartbeat(db: Session, node_id: str) -> bool:
    """Records a pulse heartbeat for the specified worker node."""
    node = db.query(WorkerNode).filter(WorkerNode.id == node_id).first()
    if not node:
        return False
    node.heartbeat_at = utc_now()
    if node.status == "OFFLINE":
        node.status = "ONLINE"
    db.commit()
    return True


def list_worker_nodes(db: Session) -> List[Dict[str, Any]]:
    """Returns cluster state of all registered worker nodes."""
    nodes = db.query(WorkerNode).order_by(desc(WorkerNode.heartbeat_at)).all()
    results = []
    now = utc_now()
    for n in nodes:
        # If heartbeat > 60s old and status was ONLINE/BUSY, treat as OFFLINE
        hb_age_sec = (now - n.heartbeat_at.replace(tzinfo=datetime.timezone.utc)).total_seconds() if n.heartbeat_at else 9999
        effective_status = n.status
        if hb_age_sec > 60 and n.status in ("ONLINE", "BUSY"):
            effective_status = "OFFLINE"

        results.append({
            "id": n.id,
            "hostname": n.hostname,
            "ip_address": n.ip_address,
            "status": effective_status,
            "active_jobs_count": n.active_jobs_count,
            "max_concurrency": n.max_concurrency,
            "capabilities": n.capabilities or [],
            "total_completed_jobs": n.total_completed_jobs,
            "total_failed_jobs": n.total_failed_jobs,
            "heartbeat_age_sec": int(hb_age_sec),
            "heartbeat_at": n.heartbeat_at.isoformat() if n.heartbeat_at else None
        })
    return results


def claim_job_atomically(
    db: Session,
    worker_id: str,
    max_concurrency: int = 4
) -> Optional[QueueJob]:
    """
    Atomically claims the highest priority pending job from the persistent queue,
    enforcing node capacity limits and backpressure.
    """
    # 1. Verify worker capacity
    node = db.query(WorkerNode).filter(WorkerNode.id == worker_id).first()
    if node:
        if node.status == "DRAINING":
            return None
        if node.active_jobs_count >= node.max_concurrency:
            node.status = "BUSY"
            db.commit()
            return None

    # 2. Query oldest QUEUED job
    # Use row-level locking when available (with_for_update)
    try:
        job = (
            db.query(QueueJob)
            .filter(QueueJob.status == "QUEUED")
            .order_by(QueueJob.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
    except Exception:
        # Fallback for SQLite which doesn't support skip_locked
        job = (
            db.query(QueueJob)
            .filter(QueueJob.status == "QUEUED")
            .order_by(QueueJob.created_at)
            .first()
        )

    if not job:
        return None

    now = utc_now()
    job.status = "RUNNING"
    job.worker_id = worker_id
    job.started_at = now
    job.heartbeat_at = now

    if node:
        node.active_jobs_count += 1
        node.heartbeat_at = now
        if node.active_jobs_count >= node.max_concurrency:
            node.status = "BUSY"

    db.commit()
    db.refresh(job)
    return job


def release_job(
    db: Session,
    job_id: str,
    worker_id: str,
    final_status: str = "COMPLETED",
    error_message: Optional[str] = None
) -> None:
    """Updates job completion and adjusts worker capacity counters."""
    job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
    now = utc_now()
    if job:
        job.status = final_status
        job.finished_at = now
        if error_message:
            job.error_message = error_message

    node = db.query(WorkerNode).filter(WorkerNode.id == worker_id).first()
    if node:
        node.active_jobs_count = max(0, node.active_jobs_count - 1)
        node.heartbeat_at = now
        if final_status == "COMPLETED":
            node.total_completed_jobs += 1
        else:
            node.total_failed_jobs += 1

        if node.status == "BUSY" and node.active_jobs_count < node.max_concurrency:
            node.status = "ONLINE"

    db.commit()


def reap_stale_workers_and_jobs(
    db: Session,
    heartbeat_timeout_sec: int = 45,
    max_retries: int = 3
) -> Dict[str, int]:
    """
    Detects crashed nodes and orphaned jobs, safely re-queuing retryable tasks
    or transitioning them to FAILED with audit trails.
    """
    now = utc_now()
    threshold = now - datetime.timedelta(seconds=heartbeat_timeout_sec)

    # 1. Identify dead nodes
    stale_nodes = (
        db.query(WorkerNode)
        .filter(WorkerNode.status.in_(["ONLINE", "BUSY"]))
        .filter(WorkerNode.heartbeat_at < threshold)
        .all()
    )

    reaped_workers = 0
    reaped_jobs = 0

    dead_node_ids = set()
    for n in stale_nodes:
        n.status = "OFFLINE"
        dead_node_ids.add(n.id)
        reaped_workers += 1

    # 2. Identify orphaned running jobs assigned to dead nodes or with expired leases
    orphaned_jobs = (
        db.query(QueueJob)
        .filter(QueueJob.status == "RUNNING")
        .filter(
            or_(
                QueueJob.worker_id.in_(dead_node_ids) if dead_node_ids else False,
                QueueJob.heartbeat_at < threshold
            )
        )
        .all()
    )

    for job in orphaned_jobs:
        if job.retry_count < max_retries:
            job.status = "QUEUED"
            job.retry_count += 1
            job.worker_id = None
            job.error_message = f"Re-queued after lease timeout on worker '{job.worker_id}' (attempt {job.retry_count}/{max_retries})"
        else:
            job.status = "FAILED"
            job.finished_at = now
            job.error_message = f"Job aborted: exceeded maximum retries ({max_retries}) due to worker node failure."
        reaped_jobs += 1

    db.commit()
    return {"reaped_workers": reaped_workers, "reaped_jobs": reaped_jobs}
