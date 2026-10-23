import datetime
import os
import json
import uuid
import threading
import time
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from backend.database.connection import engine, Base, get_db, SessionLocal
from backend.database.models import (
    Run,
    ScenarioRun,
    TraceEvent,
    CheckResult,
    Customer,
    Order,
    RefundRequest,
    QueueJob,
    utc_now
)
from backend.runner.scripted_runner import ScriptedRunner
from backend.runner.agent_runner import AgentWindTunnelRunner, DEFAULT_PROMPTS
from backend.agent.provider import (
    discover_available_gemini_models,
    validate_model_name,
    sanitize_secret
)
from backend.worker import QueueWorker

# Initialize DB tables
Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager

# Background worker thread for local all-in-one convenience
_embedded_worker: Optional[QueueWorker] = None
_embedded_worker_thread: Optional[threading.Thread] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _embedded_worker, _embedded_worker_thread
    _embedded_worker = QueueWorker(worker_id="embedded_api_worker", poll_interval_sec=1.0)
    _embedded_worker_thread = threading.Thread(target=_embedded_worker.run_forever, daemon=True)
    _embedded_worker_thread.start()
    yield
    if _embedded_worker:
        _embedded_worker.stop()


app = FastAPI(
    title="AgentWindTunnel API",
    description="Deterministic evaluation, benchmarking, and fault-injection platform for AI agents.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def serve_dashboard():
    static_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_file):
        return FileResponse(static_file)
    return HTMLResponse("<h2>AgentWindTunnel Dashboard</h2><p>Static index not found.</p>")


# -------------------------------------------------------------
# Health and Readiness Endpoints
# -------------------------------------------------------------

@app.get("/health")
@app.get("/healthz")
def health_check():
    return {
        "status": "healthy",
        "service": "AgentWindTunnel",
        "timestamp": utc_now().isoformat()
    }


@app.get("/readyz")
def readiness_check(db: Session = Depends(get_db)):
    try:
        # Check database connectivity
        db.query(Run).limit(1).all()
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": utc_now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unready: {str(e)}")


# -------------------------------------------------------------
# Agent Versions & Configuration
# -------------------------------------------------------------

@app.get("/api/agent-versions")
def list_agent_versions():
    return [
        {
            "id": "agent_v1_baseline",
            "name": "Version A (Baseline)",
            "description": "Standard basic tool-calling prompt without fault-handling guidance.",
            "prompt": DEFAULT_PROMPTS["agent_v1_baseline"]["system_prompt"]
        },
        {
            "id": "agent_v2_improved",
            "name": "Version B (Robust Compliant)",
            "description": "Fault-aware prompt with idempotency awareness and accurate state communication.",
            "prompt": DEFAULT_PROMPTS["agent_v2_improved"]["system_prompt"]
        },
        {
            "id": "scripted",
            "name": "Deterministic Scripted Runner",
            "description": "Pre-scripted programmatic tool sequence for baseline infrastructure verification.",
            "prompt": "N/A (Scripted deterministic flow)"
        }
    ]


@app.get("/api/models")
def list_available_models():
    """Discovers available models and returns verified options."""
    models = [
        {
            "id": "mock-deterministic-v1",
            "name": "mock-deterministic-v1",
            "provider": "mock",
            "description": "Deterministic local test simulator (zero cost, zero network)",
            "is_default": True
        }
    ]

    # Discover Gemini models if key is present
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        discovered = discover_available_gemini_models()
        for m in discovered:
            models.append({
                "id": m,
                "name": m,
                "provider": "gemini",
                "description": "Verified Google Gemini LLM with function calling",
                "is_default": (m == "gemini-flash-lite-latest")
            })
    else:
        # Key missing, list known options with note
        models.extend([
            {
                "id": "gemini-flash-lite-latest",
                "name": "gemini-flash-lite-latest (Key needed)",
                "provider": "gemini",
                "description": "Google Gemini 2.5 flash-lite",
                "is_default": False
            },
            {
                "id": "gemini-1.5-flash",
                "name": "gemini-1.5-flash (Key needed)",
                "provider": "gemini",
                "description": "Google Gemini 1.5 flash",
                "is_default": False
            }
        ])

    models.append({
        "id": "gpt-4o-mini",
        "name": "gpt-4o-mini",
        "provider": "openai",
        "description": "OpenAI GPT-4o mini",
        "is_default": False
    })

    return models


@app.get("/api/settings")
def get_system_settings(db: Session = Depends(get_db)):
    """
    Returns sanitized configuration status, secret readiness, and execution limits.
    CRITICAL: Never exposes secret keys!
    """
    gemini_configured = bool(os.environ.get("GEMINI_API_KEY"))
    openai_configured = bool(os.environ.get("OPENAI_API_KEY"))

    # Worker queue status
    queue_depth = db.query(QueueJob).filter(QueueJob.status == "QUEUED").count()
    running_jobs = db.query(QueueJob).filter(QueueJob.status == "RUNNING").count()
    last_job = db.query(QueueJob).order_by(QueueJob.created_at.desc()).first()

    return {
        "credentials": {
            "GEMINI_API_KEY": {
                "configured": gemini_configured,
                "status": "Configured (Verified)" if gemini_configured else "Not configured",
                "source": ".env / environment" if gemini_configured else "Missing"
            },
            "OPENAI_API_KEY": {
                "configured": openai_configured,
                "status": "Configured" if openai_configured else "Not configured",
                "source": ".env / environment" if openai_configured else "Missing"
            }
        },
        "execution_limits": {
            "max_turns": 6,
            "max_tool_calls": 10,
            "max_tokens_budget": 15000,
            "scenario_timeout_sec": 30.0,
            "tool_timeout_sec": 5.0
        },
        "worker_status": {
            "queue_depth": queue_depth,
            "running_jobs": running_jobs,
            "last_heartbeat": last_job.heartbeat_at.isoformat() if (last_job and last_job.heartbeat_at) else None
        }
    }


# -------------------------------------------------------------
# Scenarios Catalog
# -------------------------------------------------------------

def _load_all_scenarios() -> List[Dict[str, Any]]:
    scenarios = []
    seen_ids = set()

    search_dirs = ["scenarios", os.path.join("scenarios", "dev")]
    for sdir in search_dirs:
        if os.path.exists(sdir):
            for fname in os.listdir(sdir):
                if fname.endswith(".json"):
                    fpath = os.path.join(sdir, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            sid = data.get("id", fname.replace(".json", ""))
                            if sid not in seen_ids:
                                seen_ids.add(sid)
                                data["file_ref"] = fname
                                data["is_dev_suite"] = ("dev" in sdir or "scen_" in fname)
                                scenarios.append(data)
                    except Exception:
                        pass
    return scenarios


@app.get("/api/scenarios")
def list_scenarios():
    return _load_all_scenarios()


# -------------------------------------------------------------
# Overview Metrics (Live Real Database Aggregation)
# -------------------------------------------------------------

@app.get("/api/overview/metrics")
def get_overview_metrics(db: Session = Depends(get_db)):
    """
    Computes real metrics from the database without any hardcoded numbers.
    Distinguishes mock runs vs real provider runs.
    Separates behavioral check success from execution completion.
    """
    runs = db.query(Run).all()
    total_runs = len(runs)

    mock_runs_count = sum(1 for r in runs if r.is_mock)
    real_runs_count = total_runs - mock_runs_count

    completed_runs = sum(1 for r in runs if r.status == "COMPLETED")
    completion_rate = (completed_runs / total_runs * 100.0) if total_runs > 0 else 0.0

    # Aggregate scenario runs
    scenario_runs = db.query(ScenarioRun).all()
    total_scenario_runs = len(scenario_runs)

    passed_scenarios = sum(1 for sr in scenario_runs if sr.status == "PASSED")
    failed_scenarios = sum(1 for sr in scenario_runs if sr.status == "FAILED")
    provider_errors = sum(1 for sr in scenario_runs if sr.status == "PROVIDER_ERROR")

    # Overall scenario pass rate (excluding provider setup errors from behavioral denominator)
    behavioral_evaluated = passed_scenarios + failed_scenarios
    behavioral_pass_rate = (passed_scenarios / behavioral_evaluated * 100.0) if behavioral_evaluated > 0 else 0.0

    # Aggregate check results
    checks = db.query(CheckResult).all()
    total_checks = len(checks)
    checks_passed = sum(1 for c in checks if c.status == "PASSED")
    checks_failed = sum(1 for c in checks if c.status == "FAILED")

    # Recent runs (last 10)
    recent = db.query(Run).order_by(desc(Run.created_at)).limit(10).all()
    recent_list = []
    for r in recent:
        recent_list.append({
            "id": r.id,
            "agent_version_id": r.agent_version_id,
            "provider_type": r.provider_type,
            "model_name": r.model_name,
            "is_mock": bool(r.is_mock),
            "status": r.status,
            "total_scenarios": r.total_scenarios or 0,
            "passed_scenarios": r.passed_scenarios or 0,
            "failed_scenarios": r.failed_scenarios or 0,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None
        })

    return {
        "total_runs": total_runs,
        "mock_runs": mock_runs_count,
        "real_runs": real_runs_count,
        "completed_runs": completed_runs,
        "completion_rate": round(completion_rate, 1),
        "total_scenario_runs": total_scenario_runs,
        "passed_scenarios": passed_scenarios,
        "failed_scenarios": failed_scenarios,
        "provider_errors": provider_errors,
        "behavioral_pass_rate": round(behavioral_pass_rate, 1),
        "total_checks": total_checks,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "recent_runs": recent_list
    }


# -------------------------------------------------------------
# Run Queueing & History
# -------------------------------------------------------------

@app.get("/api/runs")
def list_runs(
    provider_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(Run)
    if provider_type and provider_type != "all":
        if provider_type == "mock":
            query = query.filter(Run.is_mock == 1)
        else:
            query = query.filter(Run.provider_type == provider_type, Run.is_mock == 0)

    if status and status != "all":
        query = query.filter(Run.status == status)

    runs = query.order_by(desc(Run.created_at)).limit(limit).all()

    result = []
    for r in runs:
        duration_ms = 0
        if r.started_at and r.finished_at:
            duration_ms = int((r.finished_at - r.started_at).total_seconds() * 1000)

        result.append({
            "id": r.id,
            "agent_version_id": r.agent_version_id,
            "provider_type": r.provider_type,
            "model_name": r.model_name,
            "is_mock": bool(r.is_mock),
            "status": r.status,
            "total_scenarios": r.total_scenarios or 0,
            "passed_scenarios": r.passed_scenarios or 0,
            "failed_scenarios": r.failed_scenarios or 0,
            "duration_ms": duration_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None
        })
    return result


@app.post("/api/runs/execute")
def execute_benchmark_run(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Synchronous execution of a scenario (compatible with test suite & direct API clients).
    """
    scenario_file = payload.get("scenario_file", "eligible_refund_scenario.json")
    agent_version_id = payload.get("agent_version_id", "agent_v1_baseline")
    provider_type = payload.get("provider_type", "mock")
    model_name = payload.get("model_name")

    candidates = [
        scenario_file,
        os.path.join("scenarios", scenario_file),
        os.path.join("scenarios", "dev", scenario_file),
    ]
    fpath = next((c for c in candidates if os.path.isfile(c)), None)
    if not fpath:
        raise HTTPException(status_code=404, detail=f"Scenario file '{scenario_file}' not found.")

    with open(fpath, "r", encoding="utf-8") as f:
        scenario_data = json.load(f)

    if agent_version_id == "scripted":
        runner = ScriptedRunner(db)
        return runner.run_scenario(scenario_data)
    else:
        try:
            runner = AgentWindTunnelRunner(db, provider_type=provider_type, model_name=model_name)
            return runner.run_agent_scenario(scenario_data, agent_version_id=agent_version_id)
        except RuntimeError as re:
            raise HTTPException(status_code=400, detail=str(re))


@app.post("/api/runs/scripted")
def run_scripted_scenario(payload: Dict[str, Any], db: Session = Depends(get_db)):
    if "scenario_file" in payload:
        s_file = payload["scenario_file"]
        candidates = [s_file, os.path.join("scenarios", s_file), os.path.join("scenarios", "dev", s_file)]
        fpath = next((c for c in candidates if os.path.isfile(c)), None)
        if not fpath:
            raise HTTPException(status_code=404, detail=f"Scenario file '{s_file}' not found.")
        with open(fpath, "r", encoding="utf-8") as f:
            scenario_data = json.load(f)
    elif "initial_data" in payload:
        scenario_data = payload
    else:
        raise HTTPException(status_code=400, detail="Must provide 'scenario_file' or inline scenario data.")

    runner = ScriptedRunner(db)
    return runner.run_scenario(scenario_data)


@app.post("/api/runs/queue")
def queue_run(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Submits a benchmark run to the persistent queue.
    Supports single scenario or full development suite.
    """
    agent_version_id = payload.get("agent_version_id", "agent_v2_improved")
    provider_type = payload.get("provider_type", "mock")
    model_name = payload.get("model_name") or ("mock-deterministic-v1" if provider_type == "mock" else "gemini-flash-lite-latest")
    suite_or_scenarios = payload.get("scenarios") or payload.get("scenario_file") or "dev_suite"

    # Validate model
    if provider_type != "mock":
        validate_model_name(model_name)

    # Resolve scenario list
    scenario_files: List[str] = []
    if suite_or_scenarios == "dev_suite":
        # Load 20 development scenarios
        dev_dir = os.path.join("scenarios", "dev")
        if os.path.exists(dev_dir):
            for fn in sorted(os.listdir(dev_dir)):
                if fn.endswith(".json"):
                    scenario_files.append(os.path.join("dev", fn))
        else:
            # Fallback to dev scenarios in scenarios/
            for fn in sorted(os.listdir("scenarios")):
                if fn.startswith("scen_") and fn.endswith(".json"):
                    scenario_files.append(fn)
    elif suite_or_scenarios == "smoke_suite":
        scenario_files = [
            "eligible_refund_scenario.json",
            "ineligible_expired_scenario.json",
            "fault_temporary_unavailable.json"
        ]
    elif isinstance(suite_or_scenarios, list):
        scenario_files = suite_or_scenarios
    else:
        scenario_files = [str(suite_or_scenarios)]

    if not scenario_files:
        raise HTTPException(status_code=400, detail="No valid scenarios selected.")

    run_id = f"run_{uuid.uuid4().hex[:10]}"
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    is_paid = 1 if provider_type != "mock" else 0

    execution_config = payload.get("execution_config") or {
        "max_turns": 6,
        "max_tool_calls": 10,
        "max_tokens_budget": 15000,
        "scenario_timeout_sec": 30.0,
        "tool_timeout_sec": 5.0
    }

    now = utc_now()
    run = Run(
        id=run_id,
        agent_version_id=agent_version_id,
        provider_type=provider_type,
        model_name=model_name,
        is_mock=1 if provider_type == "mock" else 0,
        execution_config=execution_config,
        status="QUEUED",
        total_scenarios=len(scenario_files),
        passed_scenarios=0,
        failed_scenarios=0,
        created_at=now
    )
    db.add(run)

    job = QueueJob(
        id=job_id,
        run_id=run_id,
        status="QUEUED",
        agent_version_id=agent_version_id,
        provider_type=provider_type,
        model_name=model_name,
        scenario_ids=scenario_files,
        execution_config=execution_config,
        is_paid=is_paid,
        created_at=now
    )
    db.add(job)
    db.commit()

    return {
        "run_id": run_id,
        "job_id": job_id,
        "status": "QUEUED",
        "total_scenarios": len(scenario_files),
        "agent_version_id": agent_version_id,
        "provider_type": provider_type,
        "model_name": model_name
    }


@app.get("/api/runs/{run_id}")
def get_run_details(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    scen_runs = db.query(ScenarioRun).filter(ScenarioRun.run_id == run_id).all()
    detailed_runs = []

    for sr in scen_runs:
        traces = db.query(TraceEvent).filter(
            TraceEvent.scenario_run_id == sr.id
        ).order_by(TraceEvent.seq_num).all()

        checks = db.query(CheckResult).filter(
            CheckResult.scenario_run_id == sr.id
        ).all()

        refunds = db.query(RefundRequest).filter(
            RefundRequest.scenario_run_id == sr.id
        ).all()

        cust = db.query(Customer).filter(Customer.scenario_run_id == sr.id).first()
        orders = db.query(Order).filter(Order.scenario_run_id == sr.id).all()

        # Distinguish refund requested vs completed
        refund_status = None
        refund_amount = 0
        if refunds:
            refund_status = refunds[0].status
            refund_amount = refunds[0].amount_cents

        detailed_runs.append({
            "scenario_run_id": sr.id,
            "scenario_version_id": sr.scenario_version_id,
            "status": sr.status,
            "duration_ms": sr.duration_ms,
            "started_at": sr.started_at.isoformat() if sr.started_at else None,
            "finished_at": sr.finished_at.isoformat() if sr.finished_at else None,
            "refund_created": len(refunds) > 0,
            "refund_status": refund_status,
            "refund_amount_cents": refund_amount,
            "checks": [
                {
                    "check_name": c.check_name,
                    "status": c.status,
                    "message": c.message,
                    "evidence": c.evidence
                } for c in checks
            ],
            "database_state": {
                "customer": {"id": cust.id, "name": cust.name, "email": cust.email} if cust else None,
                "orders": [
                    {
                        "id": o.id,
                        "status": o.status,
                        "amount_cents": o.total_amount_cents,
                        "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None
                    } for o in orders
                ],
                "refunds": [
                    {
                        "id": r.id,
                        "order_id": r.order_id,
                        "amount_cents": r.amount_cents,
                        "status": r.status,
                        "operation_key": r.operation_key
                    } for r in refunds
                ]
            },
            "traces": [
                {
                    "seq": t.seq_num,
                    "event_type": t.event_type,
                    "tool": t.tool_name,
                    "arguments": t.tool_arguments,
                    "result": t.tool_result,
                    "error": t.error_message,
                    "duration_ms": t.duration_ms,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None
                } for t in traces
            ]
        })

    duration_ms = 0
    if run.started_at and run.finished_at:
        duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

    return {
        "run_id": run.id,
        "status": run.status,
        "agent_version_id": run.agent_version_id,
        "provider_type": run.provider_type,
        "model_name": run.model_name,
        "is_mock": bool(run.is_mock),
        "execution_config": run.execution_config,
        "total_scenarios": run.total_scenarios or len(detailed_runs),
        "passed_scenarios": run.passed_scenarios or 0,
        "failed_scenarios": run.failed_scenarios or 0,
        "duration_ms": duration_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "scenario_runs": detailed_runs
    }


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    """Cancels a queued or currently executing run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    job = db.query(QueueJob).filter(QueueJob.run_id == run_id).first()
    now = utc_now()

    run.status = "CANCELLED"
    run.finished_at = now
    if job:
        job.status = "CANCELLED"
        job.finished_at = now

    db.commit()
    return {"message": f"Run {run_id} marked CANCELLED."}


# -------------------------------------------------------------
# Comparisons Endpoint
# -------------------------------------------------------------

@app.get("/api/comparisons")
def compare_runs(
    run_a: str = Query(..., description="First Run ID (Baseline)"),
    run_b: str = Query(..., description="Second Run ID (Target)"),
    db: Session = Depends(get_db)
):
    """
    Compares two runs side-by-side with strict compatibility checks.
    Evaluates configuration match, scenario overlap, and behavioral deltas.
    """
    record_a = db.query(Run).filter(Run.id == run_a).first()
    record_b = db.query(Run).filter(Run.id == run_b).first()

    if not record_a or not record_b:
        raise HTTPException(status_code=404, detail="One or both runs not found.")

    # Check compatibility
    config_diffs = []
    if record_a.provider_type != record_b.provider_type:
        config_diffs.append(f"Provider mismatch: '{record_a.provider_type}' vs '{record_b.provider_type}'")
    if record_a.model_name != record_b.model_name:
        config_diffs.append(f"Model mismatch: '{record_a.model_name}' vs '{record_b.model_name}'")
    if record_a.is_mock != record_b.is_mock:
        config_diffs.append("Engine mismatch: One run is Mock Simulator, the other is Live Provider")

    is_compatible = (len(config_diffs) == 0)

    # Compare scenario results
    scens_a = {sr.scenario_version_id: sr for sr in record_a.scenario_runs}
    scens_b = {sr.scenario_version_id: sr for sr in record_b.scenario_runs}

    all_scenario_ids = sorted(list(set(scens_a.keys()).union(set(scens_b.keys()))))
    comparison_table = []

    for sid in all_scenario_ids:
        s_a = scens_a.get(sid)
        s_b = scens_b.get(sid)

        checks_a = {c.check_name: c.status for c in (s_a.check_results if s_a else [])}
        checks_b = {c.check_name: c.status for c in (s_b.check_results if s_b else [])}

        comparison_table.append({
            "scenario_id": sid,
            "run_a_status": s_a.status if s_a else "NOT_RUN",
            "run_b_status": s_b.status if s_b else "NOT_RUN",
            "duration_a_ms": s_a.duration_ms if s_a else None,
            "duration_b_ms": s_b.duration_ms if s_b else None,
            "checks_a": checks_a,
            "checks_b": checks_b
        })

    rate_a = (record_a.passed_scenarios / record_a.total_scenarios * 100.0) if record_a.total_scenarios else 0.0
    rate_b = (record_b.passed_scenarios / record_b.total_scenarios * 100.0) if record_b.total_scenarios else 0.0

    return {
        "is_compatible": is_compatible,
        "config_diffs": config_diffs,
        "run_a": {
            "id": record_a.id,
            "agent_version": record_a.agent_version_id,
            "provider_type": record_a.provider_type,
            "model_name": record_a.model_name,
            "is_mock": bool(record_a.is_mock),
            "status": record_a.status,
            "pass_rate": round(rate_a, 1),
            "total_scenarios": record_a.total_scenarios,
            "passed_scenarios": record_a.passed_scenarios
        },
        "run_b": {
            "id": record_b.id,
            "agent_version": record_b.agent_version_id,
            "provider_type": record_b.provider_type,
            "model_name": record_b.model_name,
            "is_mock": bool(record_b.is_mock),
            "status": record_b.status,
            "pass_rate": round(rate_b, 1),
            "total_scenarios": record_b.total_scenarios,
            "passed_scenarios": record_b.passed_scenarios
        },
        "scenarios": comparison_table
    }


# -------------------------------------------------------------
# Export Run Endpoint (JSON and Readable Report)
# -------------------------------------------------------------

@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, format: str = "json", db: Session = Depends(get_db)):
    """Exports run results as clean JSON or formatted Markdown report without secrets."""
    details = get_run_details(run_id, db)

    if format == "json":
        json_data = json.dumps(details, indent=2)
        return Response(
            content=json_data,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=agent_wind_tunnel_run_{run_id}.json"}
        )

    # Markdown format
    engine_label = "MOCK SIMULATOR" if details.get("is_mock") else f"LIVE PROVIDER ({details.get('provider_type').upper()})"
    md = f"""# AgentWindTunnel Run Report
**Run ID:** `{details['run_id']}`  
**Agent Version:** `{details['agent_version_id']}`  
**Engine Mode:** `{engine_label}`  
**Model Name:** `{details['model_name']}`  
**Overall Status:** `{details['status']}`  
**Passed Scenarios:** `{details['passed_scenarios']} / {details['total_scenarios']}`  
**Duration:** `{details['duration_ms']} ms`  
**Generated At:** `{utc_now().isoformat()}`

---

## Scenario Execution Details

"""
    for sr in details.get("scenario_runs", []):
        md += f"### Scenario: `{sr['scenario_version_id']}`\n"
        md += f"- **Status:** `{sr['status']}`\n"
        md += f"- **Duration:** `{sr['duration_ms']} ms`\n"
        md += f"- **Refund Created:** `{'Yes (' + str(sr.get('refund_status')) + ')' if sr.get('refund_created') else 'No'}`\n\n"

        md += "#### Evaluator Checks:\n"
        for chk in sr.get("checks", []):
            mark = "PASS" if chk["status"] == "PASSED" else "FAIL"
            md += f"- **[{mark}] {chk['check_name']}**: {chk['message']}\n"

        md += "\n#### Trace Events:\n"
        for tr in sr.get("traces", []):
            tool_part = f" Tool: `{tr['tool']}`" if tr.get("tool") else ""
            err_part = f" Error: `{tr['error']}`" if tr.get("error") else ""
            md += f"1. `[{tr['event_type']}]`{tool_part}{err_part} ({tr.get('duration_ms', 0)}ms)\n"

        md += "\n---\n\n"

    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=agent_wind_tunnel_report_{run_id}.md"}
    )
