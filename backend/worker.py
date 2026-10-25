import os
import sys
import time
import json
import uuid
import datetime
import threading
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from backend.database.connection import SessionLocal, engine, Base
from backend.database.models import QueueJob, Run, ScenarioRun, utc_now
from backend.runner.agent_runner import AgentWindTunnelRunner
from backend.runner.scripted_runner import ScriptedRunner
from backend.agent.provider import sanitize_secret


def get_scenario_data(scenario_ref: str) -> Optional[Dict[str, Any]]:
    """Loads scenario JSON by filename, relative path, or scenario id."""
    candidates = [
        scenario_ref,
        os.path.join("scenarios", scenario_ref),
        os.path.join("scenarios", "dev", scenario_ref),
        os.path.join("scenarios", f"{scenario_ref}.json"),
        os.path.join("scenarios", "dev", f"{scenario_ref}.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


class QueueWorker:
    """
    Step 10: Persistent Background Queue Worker
    - Atomic job claiming with database-backed queue
    - Queued / Running / Completed / Failed / Cancelled lifecycle
    - Periodic heartbeats and abandoned-job recovery
    - Safe cancellation between scenarios
    - Paid execution isolation and idempotent protections
    """

    def __init__(self, worker_id: Optional[str] = None, poll_interval_sec: float = 1.0):
        self.worker_id = worker_id or f"worker_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self.poll_interval_sec = poll_interval_sec
        self._stop_event = threading.Event()
        # Ensure tables exist
        Base.metadata.create_all(bind=engine)

    def stop(self):
        """Signals worker to stop gracefully."""
        self._stop_event.set()

    def claim_next_job(self, db: Session) -> Optional[QueueJob]:
        """
        Atomically claims the oldest QUEUED job.
        Uses optimistic status matching to prevent race conditions across multiple workers.
        """
        candidate = db.query(QueueJob).filter(
            QueueJob.status == "QUEUED"
        ).order_by(QueueJob.created_at.asc()).first()

        if not candidate:
            return None

        # Atomic status update
        now = utc_now()
        updated_rows = db.query(QueueJob).filter(
            QueueJob.id == candidate.id,
            QueueJob.status == "QUEUED"
        ).update({
            QueueJob.status: "RUNNING",
            QueueJob.worker_id: self.worker_id,
            QueueJob.started_at: now,
            QueueJob.heartbeat_at: now
        })

        if updated_rows == 0:
            # Another worker claimed it first
            db.rollback()
            return None

        # Update associated Run record
        run = db.query(Run).filter(Run.id == candidate.run_id).first()
        if run:
            run.status = "RUNNING"
            run.started_at = now

        db.commit()
        db.refresh(candidate)
        return candidate

    def reap_abandoned_jobs(self, db: Session, heartbeat_cutoff_sec: float = 30.0) -> int:
        """
        Identifies orphaned or crashed jobs whose heartbeat expired.
        Protects paid execution from duplicate charges.
        """
        cutoff = utc_now() - datetime.timedelta(seconds=heartbeat_cutoff_sec)
        stale_jobs = db.query(QueueJob).filter(
            QueueJob.status == "RUNNING",
            QueueJob.heartbeat_at < cutoff
        ).all()

        reaped_count = 0
        for job in stale_jobs:
            now = utc_now()
            run = db.query(Run).filter(Run.id == job.run_id).first()

            if job.is_paid:
                # CRITICAL: Never automatically rerun paid execution without preserving original attempt
                job.status = "FAILED"
                job.finished_at = now
                job.error_message = (
                    "Abandoned paid execution detected after worker disconnection. "
                    "Automatic retry disabled to prevent duplicate billing and external side effects."
                )
                if run:
                    run.status = "FAILED"
                    run.finished_at = now
            else:
                job.status = "FAILED"
                job.finished_at = now
                job.error_message = (
                    f"Abandoned job reaped (no heartbeat for >{heartbeat_cutoff_sec}s). "
                    "Worker process terminated unexpectedly."
                )
                if run:
                    run.status = "FAILED"
                    run.finished_at = now

            # Interrupted scenario state is unknown; keep evidence without inventing checks.
            db.query(ScenarioRun).filter(
                ScenarioRun.run_id == job.run_id, ScenarioRun.status == "RUNNING"
            ).update({ScenarioRun.status: "INTERRUPTED", ScenarioRun.finished_at: now})
            reaped_count += 1

        if reaped_count > 0:
            db.commit()
        return reaped_count

    def _start_heartbeat(self, job_id: str, stop_flag: threading.Event):
        """Periodically refreshes heartbeat_at for active job in separate DB session."""
        while not stop_flag.is_set():
            time.sleep(3.0)
            if stop_flag.is_set():
                break
            try:
                hb_db = SessionLocal()
                try:
                    hb_db.query(QueueJob).filter(QueueJob.id == job_id).update({
                        QueueJob.heartbeat_at: utc_now()
                    })
                    hb_db.commit()
                finally:
                    hb_db.close()
            except Exception:
                pass

    def execute_job(self, job_id: str):
        """Executes a claimed QueueJob scenario by scenario with full isolation."""
        db = SessionLocal()
        try:
            job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
            if not job:
                return

            run = db.query(Run).filter(Run.id == job.run_id).first()
            scenario_ids: List[str] = job.scenario_ids or []
            total_scenarios = len(scenario_ids)

            if run:
                run.total_scenarios = total_scenarios
                db.commit()

            # Start background heartbeat
            hb_stop = threading.Event()
            hb_thread = threading.Thread(
                target=self._start_heartbeat,
                args=(job_id, hb_stop),
                daemon=True
            )
            hb_thread.start()

            passed_count = 0
            failed_count = 0
            infrastructure_error = False
            is_cancelled = False

            try:
                for idx, scen_ref in enumerate(scenario_ids):
                    # Check cancellation before each scenario
                    db.refresh(job)
                    if job.status == "CANCELLED" or (run and run.status == "CANCELLED"):
                        is_cancelled = True
                        break

                    scenario_data = get_scenario_data(scen_ref)
                    if not scenario_data:
                        infrastructure_error = True
                        job.error_message = "Selected scenario could not be loaded."
                        failed_count += 1
                        if run:
                            run.failed_scenarios = failed_count
                            db.commit()
                        continue

                    # Execute scenario in isolated session
                    scen_db = SessionLocal()
                    try:
                        agent_type = job.agent_version_id
                        if agent_type == "scripted":
                            runner = ScriptedRunner(scen_db)
                            res = runner.run_scenario(scenario_data, agent_version_id=agent_type, run_id=job.run_id)
                        else:
                            runner = AgentWindTunnelRunner(
                                scen_db,
                                provider_type=job.provider_type,
                                model_name=job.model_name
                            )
                            res = runner.run_agent_scenario(
                                scenario_data,
                                agent_version_id=agent_type,
                                run_id=job.run_id
                            )

                        if res.get("status") == "PROVIDER_ERROR":
                            infrastructure_error = True
                            job.error_message = "Provider execution failed; inspect scenario checks and trace."
                        if res.get("status") == "PASSED":
                            passed_count += 1
                        else:
                            failed_count += 1

                    except Exception as e:
                        infrastructure_error = True
                        job.error_message = sanitize_secret(str(e))
                        print(f"Scenario infrastructure error: {job.error_message}", flush=True)
                        failed_count += 1
                    finally:
                        scen_db.close()

                    # Update run progress after each scenario
                    db.refresh(run)
                    if run:
                        run.passed_scenarios = passed_count
                        run.failed_scenarios = failed_count
                        db.commit()

            finally:
                # Stop heartbeat
                hb_stop.set()
                hb_thread.join(timeout=2.0)

            # Finalize Job and Run
            now = utc_now()
            db.refresh(job)
            db.refresh(run)

            if is_cancelled or job.status == "CANCELLED" or (run and run.status == "CANCELLED"):
                job.status = "CANCELLED"
                if run:
                    run.status = "CANCELLED"
            elif infrastructure_error:
                job.status = "FAILED"
                if run:
                    run.status = "FAILED"
            elif failed_count == 0 and passed_count > 0:
                job.status = "COMPLETED"
                if run:
                    run.status = "COMPLETED"
            else:
                job.status = "COMPLETED" if (passed_count + failed_count) == total_scenarios else "FAILED"
                if run:
                    run.status = "COMPLETED" if (passed_count + failed_count) == total_scenarios else "FAILED"

            job.finished_at = now
            if run:
                run.finished_at = now
                run.passed_scenarios = passed_count
                run.failed_scenarios = failed_count

            db.commit()

        except Exception as e:
            db.rollback()
            try:
                now = utc_now()
                job = db.query(QueueJob).filter(QueueJob.id == job_id).first()
                run = db.query(Run).filter(Run.id == job.run_id).first() if job else None
                if job:
                    job.status = "FAILED"
                    job.error_message = str(e)
                    job.finished_at = now
                if run:
                    run.status = "FAILED"
                    run.finished_at = now
                db.commit()
            except Exception:
                pass
        finally:
            db.close()

    def process_one(self) -> bool:
        """Processes a single queued job if available. Returns True if a job was processed."""
        db = SessionLocal()
        try:
            # First, clean up abandoned jobs
            self.reap_abandoned_jobs(db)

            # Claim next
            job = self.claim_next_job(db)
            if not job:
                return False

            job_id = job.id
        finally:
            db.close()

        print(f"[{self.worker_id}] Executing job {job_id}...")
        self.execute_job(job_id)
        print(f"[{self.worker_id}] Job {job_id} finished.")
        return True

    def run_forever(self):
        """Continuous execution loop."""
        print(f"⚡ [AgentWindTunnel] Queue Worker '{self.worker_id}' started.")
        try:
            while not self._stop_event.is_set():
                processed = self.process_one()
                if not processed:
                    time.sleep(self.poll_interval_sec)
        except (KeyboardInterrupt, SystemExit):
            print(f"[{self.worker_id}] Worker interrupted, stopping...")
        finally:
            print(f"[{self.worker_id}] Worker stopped.")


if __name__ == "__main__":
    worker = QueueWorker()
    worker.run_forever()
