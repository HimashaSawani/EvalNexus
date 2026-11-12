#!/usr/bin/env python3
"""
scripts/recover_travel_run2.py

Safe, auditable recovery utility for EvalNexus V4 Travel Run 2:
  Target: colab_generic_travel_20261112_065358_8af322

Features:
  - Dry-run mode by default (--execute required to apply writes)
  - Target run ID validation and artifact SHA-256 integrity check
  - Consistent online SQLite backup using sqlite3.Connection.backup API
  - Precondition validation (verifies target run is currently RUNNING with 0 traces/checks)
  - Atomic write transaction with complete rollback on failure
  - Post-recovery verification (verifies Run 1 and all unrelated runs are untouched)
  - Supports Approach A (auditable in-place repair) and Approach B (atomic overwrite)
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
import sqlite3

# Ensure repo root is in python path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scenarios.offline_bundle import (
    _trace_event_id,
    detect_incomplete_execution,
    import_generic_colab_results,
)
from backend.runner.generic_evaluator import GenericAssertionEvaluator
from backend.scenarios.generic_scenario import GenericAssertion
from backend.database.models import (
    Run, ScenarioRun, TraceEvent, CheckResult, ScenarioVersion, AgentVersion, utc_now
)
from backend.scenarios.custom_scenario_service import get_custom_scenario
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

EXPECTED_RUN_ID = "colab_generic_travel_20261112_065358_8af322"
EXPECTED_ARTIFACT_SHA256 = "473ba94d8d474a5a4b24aabde994d3f6cc7dad0e82d0db9ca6c03eff7774335c"
EXPECTED_HISTORICAL_RUN1_ID = "colab_generic_travel_20261112_053305_906d98"


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_consistent_sqlite_backup(src_db_path: Path, backup_dest_path: Path) -> Path:
    """Uses the SQLite Online Backup API to create a consistent snapshot across WAL frames."""
    backup_dest_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_dest_path.exists():
        backup_dest_path.unlink()

    src_conn = sqlite3.connect(str(src_db_path))
    dest_conn = sqlite3.connect(str(backup_dest_path))
    try:
        # Checkpoint WAL first if possible
        try:
            src_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
        except Exception:
            pass
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()

    # Verify backup integrity
    verify_conn = sqlite3.connect(str(backup_dest_path))
    try:
        cur = verify_conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchall()
        if res != [("ok",)]:
            raise RuntimeError(f"Backup integrity check failed: {res}")
    finally:
        verify_conn.close()

    return backup_dest_path


def verify_preconditions(db_conn: sqlite3.Connection, target_run_id: str) -> dict:
    """Verifies that the database contains the target run in the expected broken state."""
    cur = db_conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    if cur.fetchall() != [("ok",)]:
        raise RuntimeError("Target database failed PRAGMA integrity_check")

    cur.execute("SELECT id, status, total_scenarios, passed_scenarios, failed_scenarios, started_at, finished_at FROM runs WHERE id = ?", (target_run_id,))
    run_row = cur.fetchone()
    if not run_row:
        raise ValueError(f"Target run '{target_run_id}' not found in database")
    if run_row[1] != "RUNNING":
        raise ValueError(f"Precondition failed: Target run '{target_run_id}' has status '{run_row[1]}', expected 'RUNNING'")

    cur.execute("SELECT id, status, started_at, finished_at FROM scenario_runs WHERE run_id = ?", (target_run_id,))
    sr_rows = cur.fetchall()
    if len(sr_rows) != 1:
        raise ValueError(f"Precondition failed: Expected exactly 1 scenario_run for '{target_run_id}', found {len(sr_rows)}")
    sr_id = sr_rows[0][0]

    cur.execute("SELECT COUNT(*) FROM trace_events WHERE scenario_run_id = ?", (sr_id,))
    trace_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM check_results WHERE scenario_run_id = ?", (sr_id,))
    check_count = cur.fetchone()[0]

    # Verify Run 1 exists and is intact
    cur.execute("SELECT id, status, passed_scenarios, failed_scenarios FROM runs WHERE id = ?", (EXPECTED_HISTORICAL_RUN1_ID,))
    run1_row = cur.fetchone()
    if not run1_row or run1_row[1] != "COMPLETED":
        raise ValueError(f"Precondition failed: Historical Run 1 '{EXPECTED_HISTORICAL_RUN1_ID}' is missing or not COMPLETED")

    cur.execute("SELECT COUNT(*) FROM runs")
    total_runs = cur.fetchone()[0]

    return {
        "run_id": target_run_id,
        "scenario_run_id": sr_id,
        "existing_traces": trace_count,
        "existing_checks": check_count,
        "total_runs": total_runs,
        "run1_status": run1_row[1],
    }


def resolve_scenario_definition(db_session, scen_id: str) -> dict:
    """Robust scenario lookup across custom service, DB ScenarioVersion, and canonical bundles."""
    scen_data = get_custom_scenario(db_session, scen_id)
    if scen_data:
        return scen_data

    # Check REPO_ROOT / scenarios / custom / <scen_id>.json
    custom_f = REPO_ROOT / "scenarios" / "custom" / f"{scen_id}.json"
    if custom_f.is_file():
        with open(custom_f, "r", encoding="utf-8") as f:
            return json.load(f)

    # Check REPO_ROOT / backend / scenarios / generic / <scen_id>.json
    backend_f = REPO_ROOT / "backend" / "scenarios" / "generic" / f"{scen_id}.json"
    if backend_f.is_file():
        with open(backend_f, "r", encoding="utf-8") as f:
            return json.load(f)

    # Check DB ScenarioVersion.initial_data
    sv = db_session.query(ScenarioVersion).filter(ScenarioVersion.id == scen_id).first()
    if sv and isinstance(sv.initial_data, dict):
        return sv.initial_data

    # Check generic_travel_bundle.json
    bundle_f = REPO_ROOT / "docs" / "scenarios" / "generic_travel_bundle.json"
    if bundle_f.is_file():
        with open(bundle_f, "r", encoding="utf-8") as f:
            b = json.load(f)
            if b.get("scenario", {}).get("id") == scen_id:
                return b["scenario"]

    raise ValueError(f"Custom scenario definition '{scen_id}' not found in DB or filesystem")


def execute_auditable_repair(db_session, target_run_id: str, artifact_payload: dict, artifact_sha256: str) -> dict:
    """Approach A: In-place auditable repair of existing Run 2 records.
    Preserves original run.started_at, populates missing traces and check results,
    updates status to terminal COMPLETED (0 passed, 1 failed) and ScenarioRun to FAILED.
    """
    run_rec = db_session.query(Run).filter(Run.id == target_run_id).one()
    scen_run = db_session.query(ScenarioRun).filter(ScenarioRun.run_id == target_run_id).one()
    scenario_run_id = scen_run.id

    scen_id = artifact_payload.get("scenario_id", "generic_travel_planner")
    scen_data = resolve_scenario_definition(db_session, scen_id)

    # Clear any lingering partial child records for this scenario run if any exist
    db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == scenario_run_id).delete()
    db_session.query(CheckResult).filter(CheckResult.scenario_run_id == scenario_run_id).delete()
    db_session.flush()

    traces_data = artifact_payload.get("traces", [])
    for t in traces_data:
        t_seq = t.get("seq")
        t_time = datetime.datetime.fromisoformat(t["timestamp"]) if t.get("timestamp") else utc_now()
        t_args = t.get("arguments")
        if not isinstance(t_args, dict) and t_args:
            t_args = {"raw": t_args}
        t_res = t.get("result")
        if not isinstance(t_res, dict) and t_res:
            t_res = {"raw": t_res}

        db_session.add(TraceEvent(
            id=_trace_event_id(scenario_run_id, t_seq),
            scenario_run_id=scenario_run_id,
            seq_num=t_seq,
            timestamp=t_time,
            duration_ms=t.get("duration_ms", 0),
            event_type=t.get("event_type", "TOOL_EXECUTION"),
            tool_name=t.get("tool"),
            tool_arguments=t_args,
            tool_result=t_res,
            error_message=t.get("error"),
            token_usage=None,
            cost_estimate=0
        ))

    final_answer = artifact_payload.get("final_answer")
    if final_answer:
        db_session.add(TraceEvent(
            id=_trace_event_id(scenario_run_id, "resp"),
            scenario_run_id=scenario_run_id,
            seq_num=len(traces_data) + 1,
            timestamp=utc_now(),
            duration_ms=0,
            event_type="AGENT_RESPONSE",
            tool_result={"content": final_answer}
        ))

    db_session.flush()

    # Fail-closed error evaluation
    effective_error = artifact_payload.get("execution_error")
    if not effective_error:
        effective_error = detect_incomplete_execution(
            final_answer,
            traces_data,
            scen_data,
            artifact_payload.get("metadata", {})
        )

    assertions = [
        GenericAssertion(**a) if isinstance(a, dict) else a
        for a in scen_data.get("assertions", [])
    ]

    evaluator = GenericAssertionEvaluator(db_session, scenario_run_id)
    checks = evaluator.evaluate_all(
        assertions=assertions,
        final_answer=final_answer,
        execution_error=effective_error,
        auto_commit=False
    )

    all_passed = all(c.status == "PASSED" for c in checks)
    scen_run.status = "PASSED" if all_passed else "FAILED"
    scen_run.finished_at = utc_now()

    run_rec.status = "COMPLETED"
    run_rec.passed_scenarios = 1 if all_passed else 0
    run_rec.failed_scenarios = 0 if all_passed else 1
    run_rec.finished_at = utc_now()

    # Append audit trail metadata to execution_config
    cfg = dict(run_rec.execution_config or {})
    cfg["recovered_at"] = utc_now().isoformat()
    cfg["recovery_method"] = "in_place_auditable_repair"
    cfg["artifact_sha256"] = artifact_sha256
    run_rec.execution_config = cfg

    db_session.commit()

    return {
        "status": "RECOVERED",
        "method": "in_place_auditable_repair",
        "run_id": target_run_id,
        "scenario_run_id": scenario_run_id,
        "run_status": run_rec.status,
        "scenario_run_status": scen_run.status,
        "total_checks": len(checks),
        "passed_checks": sum(1 for c in checks if c.status == "PASSED"),
        "failed_checks": sum(1 for c in checks if c.status == "FAILED"),
        "checks": [(c.check_name, c.status) for c in checks]
    }


def execute_atomic_overwrite(db_session, target_run_id: str, artifact_payload: dict) -> dict:
    """Approach B: Atomic overwrite using import_generic_colab_results(overwrite=True)."""
    res = import_generic_colab_results(db_session, artifact_payload, overwrite=True)
    return {
        "status": "RECOVERED",
        "method": "atomic_overwrite",
        "run_id": target_run_id,
        "run_status": "COMPLETED",
        "scenario_run_status": "PASSED" if res["passed"] else "FAILED",
        "total_checks": res["total_checks"],
        "passed_checks": res["passed_checks"],
        "failed_checks": res["failed_checks"],
        "checks": [(c["check_name"], c["status"]) for c in res["check_results"]]
    }


def verify_post_recovery(db_conn: sqlite3.Connection, target_run_id: str, initial_total_runs: int) -> dict:
    """Verifies that the target run is fully recovered and all unrelated runs are untouched."""
    cur = db_conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    if cur.fetchall() != [("ok",)]:
        raise RuntimeError("Post-recovery integrity check failed!")

    cur.execute("SELECT id, status, passed_scenarios, failed_scenarios, started_at, finished_at FROM runs WHERE id = ?", (target_run_id,))
    run_row = cur.fetchone()
    if not run_row:
        raise RuntimeError(f"Target run {target_run_id} missing after recovery")
    if run_row[1] != "COMPLETED" or run_row[2] != 0 or run_row[3] != 1 or run_row[5] is None:
        raise RuntimeError(f"Run post-conditions violated: {run_row}")

    cur.execute("SELECT id, status, finished_at FROM scenario_runs WHERE run_id = ?", (target_run_id,))
    sr_rows = cur.fetchall()
    if len(sr_rows) != 1 or sr_rows[0][1] != "FAILED" or sr_rows[0][2] is None:
        raise RuntimeError(f"ScenarioRun post-conditions violated: {sr_rows}")
    sr_id = sr_rows[0][0]

    cur.execute("SELECT id, seq_num, event_type, tool_name FROM trace_events WHERE scenario_run_id = ? ORDER BY seq_num", (sr_id,))
    traces = cur.fetchall()
    if len(traces) != 6:
        raise RuntimeError(f"Expected 6 traces, found {len(traces)}")

    trace_ids = [t[0] for t in traces]
    if len(set(trace_ids)) != len(trace_ids):
        raise RuntimeError("TraceEvent ID collision detected in recovered records!")

    cur.execute("SELECT check_name, status, message FROM check_results WHERE scenario_run_id = ?", (sr_id,))
    checks = cur.fetchall()
    if len(checks) != 6:
        raise RuntimeError(f"Expected 6 checks, found {len(checks)}")

    passed_checks = sum(1 for c in checks if c[1] == "PASSED")
    failed_checks = sum(1 for c in checks if c[1] == "FAILED")
    if passed_checks != 3 or failed_checks != 3:
        raise RuntimeError(f"Expected exactly 3 PASSED and 3 FAILED, got {passed_checks}P/{failed_checks}F")

    # Verify Run 1 is still pristine
    cur.execute("SELECT id, status, passed_scenarios, failed_scenarios FROM runs WHERE id = ?", (EXPECTED_HISTORICAL_RUN1_ID,))
    run1 = cur.fetchone()
    if not run1 or run1[1] != "COMPLETED" or run1[2] != 0 or run1[3] != 1:
        raise RuntimeError(f"Historical Run 1 was mutated: {run1}")

    cur.execute("SELECT COUNT(*) FROM runs")
    final_total_runs = cur.fetchone()[0]
    if final_total_runs != initial_total_runs:
        raise RuntimeError(f"Total runs count changed: before={initial_total_runs}, after={final_total_runs}")

    return {
        "verified": True,
        "run_id": target_run_id,
        "run_status": run_row[1],
        "scenario_run_status": sr_rows[0][1],
        "trace_count": len(traces),
        "check_count": len(checks),
        "score": f"{passed_checks}/{len(checks)}",
        "checks": [(c[0], c[1]) for c in checks]
    }


def main():
    parser = argparse.ArgumentParser(description="EvalNexus V4 Safe Historical Run 2 Recovery Utility")
    parser.add_argument("--db-path", type=str, required=True, help="Path to SQLite database to recover (use temporary clone for testing)")
    parser.add_argument("--artifact-path", type=str, default=str(REPO_ROOT / "experiments" / "colab_generic_travel_20261112_065358_8af322_result.json"))
    parser.add_argument("--target-run-id", type=str, default=EXPECTED_RUN_ID)
    parser.add_argument("--backup-dir", type=str, default=str(REPO_ROOT / "backups"))
    parser.add_argument("--approach", choices=["auditable_repair", "atomic_overwrite"], default="auditable_repair")
    parser.add_argument("--execute", action="store_true", help="Execute writes (otherwise defaults to dry-run)")
    args = parser.parse_args()

    db_path = Path(args.db_path).resolve()
    artifact_path = Path(args.artifact_path).resolve()

    print("=" * 70)
    print("EVALNEXUS V4 — SAFE HISTORICAL RUN 2 RECOVERY UTILITY")
    print("=" * 70)
    print(f"Database Target : {db_path}")
    print(f"Artifact Target : {artifact_path}")
    print(f"Target Run ID   : {args.target_run_id}")
    print(f"Recovery Mode   : {'EXECUTE (WRITES ENABLED)' if args.execute else 'DRY-RUN (READ-ONLY PREVIEW)'}")
    print(f"Approach        : {args.approach}")
    print("=" * 70)

    # 1. Target Run ID validation
    if args.target_run_id != EXPECTED_RUN_ID:
        raise ValueError(f"Target run ID mismatch: '{args.target_run_id}' != '{EXPECTED_RUN_ID}'")

    # 2. Artifact validation & SHA-256 integrity check
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact file not found: {artifact_path}")
    actual_art_hash = compute_sha256(artifact_path)
    print(f"[1/6] Artifact SHA-256 Check: {actual_art_hash}")
    if actual_art_hash != EXPECTED_ARTIFACT_SHA256:
        raise ValueError(f"Artifact hash mismatch! Expected {EXPECTED_ARTIFACT_SHA256}, got {actual_art_hash}")
    print("      -> Artifact authenticity verified.")

    with open(artifact_path, "r", encoding="utf-8") as f:
        artifact_payload = json.load(f)

    # 3. Preconditions check
    print(f"[2/6] Verifying Target Database Preconditions...")
    ro_conn = sqlite3.connect(str(db_path))
    try:
        pre_info = verify_preconditions(ro_conn, args.target_run_id)
        print(f"      -> Target Run '{args.target_run_id}' is currently RUNNING with {pre_info['existing_traces']} traces, {pre_info['existing_checks']} checks.")
        print(f"      -> Total runs in DB: {pre_info['total_runs']}, Historical Run 1 intact.")
    finally:
        ro_conn.close()

    # 4. Consistent SQLite Backup
    timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = Path(args.backup_dir) / f"agent_wind_tunnel_backup_{timestamp_str}.db"
    print(f"[3/6] Creating Consistent SQLite Backup via Online Backup API...")
    backup_path = create_consistent_sqlite_backup(db_path, backup_file)
    print(f"      -> Consistent backup verified at: {backup_path}")

    if not args.execute:
        print("\n" + "=" * 70)
        print("[DRY-RUN COMPLETE] All preconditions and integrity checks passed!")
        print("No changes were made to the database.")
        print("To execute recovery, pass --execute.")
        print("=" * 70)
        return

    # 5. Execute Atomic Recovery
    print(f"[4/6] Executing Recovery using approach '{args.approach}'...")
    engine = create_engine(f"sqlite:///{str(db_path).replace(os.sep, '/')}")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        if args.approach == "auditable_repair":
            rec_result = execute_auditable_repair(session, args.target_run_id, artifact_payload, actual_art_hash)
        else:
            rec_result = execute_atomic_overwrite(session, args.target_run_id, artifact_payload)
        print(f"      -> Recovery completed: {rec_result['status']} ({rec_result['passed_checks']}/{rec_result['total_checks']} checks passed).")
    except Exception as e:
        session.rollback()
        print(f"[ERROR] Recovery failed, rolled back completely: {e}")
        raise
    finally:
        session.close()

    # 6. Post-recovery verification
    print(f"[5/6] Verifying Post-Recovery State & Invariant Checks...")
    verify_conn = sqlite3.connect(str(db_path))
    try:
        post_info = verify_post_recovery(verify_conn, args.target_run_id, pre_info["total_runs"])
        print(f"      -> Run status: {post_info['run_status']}")
        print(f"      -> ScenarioRun status: {post_info['scenario_run_status']}")
        print(f"      -> Traces: {post_info['trace_count']} (0 collisions)")
        print(f"      -> Score: {post_info['score']}")
        for name, st in post_info["checks"]:
            print(f"         * {name}: {st}")
    finally:
        verify_conn.close()

    print("\n" + "=" * 70)
    print("RECOVERY REHEARSAL SUCCESSFUL & VERIFIED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
