import datetime
import os
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database.connection import engine, Base, get_db
from backend.database.models import Run, ScenarioRun, TraceEvent, CheckResult, Customer, Order, RefundRequest
from backend.runner.scripted_runner import ScriptedRunner
from backend.runner.agent_runner import AgentWindTunnelRunner, DEFAULT_PROMPTS

# Initialize DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AgentWindTunnel API",
    description="Deterministic evaluation, benchmarking, and fault-injection platform for AI agents.",
    version="1.0.0"
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


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AgentWindTunnel",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


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


@app.get("/api/scenarios")
def list_scenarios():
    scenarios_dir = "scenarios"
    scenarios = []
    if os.path.exists(scenarios_dir):
        for fname in os.listdir(scenarios_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(scenarios_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    scenarios.append(json.load(f))
    return scenarios


@app.post("/api/runs/execute")
def execute_benchmark_run(payload: Dict[str, Any], db: Session = Depends(get_db)):
    """
    Executes a scenario via autonomous Agent Loop (Version A/B) or Scripted Runner.
    Supports provider_type ('mock', 'openai', 'gemini') and model_name.
    """
    scenario_file = payload.get("scenario_file", "eligible_refund_scenario.json")
    agent_version_id = payload.get("agent_version_id", "agent_v1_baseline")
    provider_type = payload.get("provider_type", "mock")
    model_name = payload.get("model_name")

    fpath = os.path.join("scenarios", scenario_file)
    if not os.path.exists(fpath):
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
        fpath = os.path.join("scenarios", payload["scenario_file"])
        if not os.path.exists(fpath):
            raise HTTPException(status_code=404, detail="Scenario file not found")
        with open(fpath, "r", encoding="utf-8") as f:
            scenario_data = json.load(f)
    elif "initial_data" in payload:
        scenario_data = payload
    else:
        raise HTTPException(status_code=400, detail="Must provide 'scenario_file' or inline scenario data.")

    runner = ScriptedRunner(db)
    return runner.run_scenario(scenario_data)


@app.get("/api/runs/{run_id}")
def get_run_details(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    scen_runs = db.query(ScenarioRun).filter(ScenarioRun.run_id == run_id).all()
    detailed_runs = []
    for sr in scen_runs:
        traces = db.query(TraceEvent).filter(TraceEvent.scenario_run_id == sr.id).order_by(TraceEvent.seq_num).all()
        checks = db.query(CheckResult).filter(CheckResult.scenario_run_id == sr.id).all()
        refunds = db.query(RefundRequest).filter(RefundRequest.scenario_run_id == sr.id).all()

        detailed_runs.append({
            "scenario_run_id": sr.id,
            "scenario_version_id": sr.scenario_version_id,
            "status": sr.status,
            "duration_ms": sr.duration_ms,
            "checks": [{"name": c.check_name, "status": c.status, "message": c.message, "evidence": c.evidence} for c in checks],
            "refund_created": len(refunds) > 0,
            "traces": [
                {
                    "seq": t.seq_num,
                    "event_type": t.event_type,
                    "tool": t.tool_name,
                    "duration_ms": t.duration_ms,
                    "error": t.error_message
                } for t in traces
            ]
        })

    return {
        "run_id": run.id,
        "status": run.status,
        "agent_version_id": run.agent_version_id,
        "provider_type": run.provider_type,
        "model_name": run.model_name,
        "is_mock": bool(run.is_mock),
        "execution_config": run.execution_config,
        "passed_scenarios": run.passed_scenarios,
        "failed_scenarios": run.failed_scenarios,
        "scenario_runs": detailed_runs
    }
