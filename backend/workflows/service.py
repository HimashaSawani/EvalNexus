import uuid
import time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database.models import Workflow, WorkflowRun, WorkflowStepRun, utc_now
from backend.workflows.models import WorkflowDefinition, WorkflowRunResult
from backend.workflows.runner import MultiAgentWorkflowRunner


def create_or_update_workflow(db: Session, workflow_dict: Dict[str, Any]) -> Workflow:
    """Validates and persists a Multi-Agent Workflow definition."""
    # Validate via Pydantic model
    validated_def = WorkflowDefinition(**workflow_dict)
    
    wf_id = validated_def.workflow_id
    existing = db.query(Workflow).filter(Workflow.id == wf_id).first()
    
    if existing:
        existing.name = validated_def.name
        existing.description = validated_def.description
        existing.version = validated_def.version
        existing.definition_json = validated_def.model_dump()
        existing.updated_at = utc_now()
        db.commit()
        db.refresh(existing)
        return existing
    else:
        new_wf = Workflow(
            id=wf_id,
            name=validated_def.name,
            description=validated_def.description,
            version=validated_def.version,
            definition_json=validated_def.model_dump(),
            is_active=1
        )
        db.add(new_wf)
        db.commit()
        db.refresh(new_wf)
        return new_wf


def list_workflows(db: Session) -> List[Dict[str, Any]]:
    """Returns all registered workflows."""
    records = db.query(Workflow).filter(Workflow.is_active == 1).order_by(desc(Workflow.updated_at)).all()
    results = []
    for r in records:
        data = dict(r.definition_json)
        data["workflow_id"] = r.id
        data["created_at"] = r.created_at.isoformat() if r.created_at else None
        data["updated_at"] = r.updated_at.isoformat() if r.updated_at else None
        results.append(data)
    return results


def get_workflow(db: Session, workflow_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a single workflow definition by ID."""
    r = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not r:
        return None
    data = dict(r.definition_json)
    data["workflow_id"] = r.id
    data["created_at"] = r.created_at.isoformat() if r.created_at else None
    data["updated_at"] = r.updated_at.isoformat() if r.updated_at else None
    return data


def delete_workflow(db: Session, workflow_id: str) -> bool:
    """Soft or hard deletes a workflow."""
    r = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not r:
        return False
    db.delete(r)
    db.commit()
    return True


def execute_workflow(
    db: Session,
    workflow_id: str,
    initial_inputs: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Executes a stored workflow definition, recording the run and step traces in the database.
    """
    wf_record = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf_record:
        raise ValueError(f"Workflow '{workflow_id}' not found.")

    wf_def = WorkflowDefinition(**wf_record.definition_json)
    runner = MultiAgentWorkflowRunner(wf_def)
    result: WorkflowRunResult = runner.run_workflow(initial_inputs=initial_inputs)

    # Persist run
    db_run = WorkflowRun(
        id=result.workflow_run_id,
        workflow_id=wf_record.id,
        status=result.status,
        duration_ms=result.duration_ms,
        total_tokens=result.total_tokens,
        total_cost_usd=result.total_cost_usd,
        final_output=result.final_output,
        workflow_state=result.workflow_state,
        checks=result.checks,
        error_message=result.error_message,
        finished_at=utc_now()
    )
    db.add(db_run)

    # Persist steps
    for step in result.step_results:
        db_step = WorkflowStepRun(
            id=f"steprun_{uuid.uuid4().hex[:10]}",
            workflow_run_id=result.workflow_run_id,
            step_id=step.step_id,
            agent_id=step.agent_id,
            status=step.status,
            input_text=step.input_text,
            output_text=step.output_text,
            tool_calls=step.tool_calls,
            duration_ms=step.duration_ms,
            tokens_used=step.tokens_used,
            estimated_cost_usd=step.estimated_cost_usd,
            error_message=step.error_message,
            checks=step.evaluator_checks
        )
        db.add(db_step)

    db.commit()
    return result.model_dump()


def get_workflow_run(db: Session, run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves full run details including step execution history."""
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        return None
    
    steps = db.query(WorkflowStepRun).filter(WorkflowStepRun.workflow_run_id == run_id).order_by(WorkflowStepRun.created_at).all()
    step_list = []
    for s in steps:
        step_list.append({
            "id": s.id,
            "step_id": s.step_id,
            "agent_id": s.agent_id,
            "status": s.status,
            "input_text": s.input_text,
            "output_text": s.output_text,
            "tool_calls": s.tool_calls or [],
            "duration_ms": s.duration_ms,
            "tokens_used": s.tokens_used,
            "estimated_cost_usd": s.estimated_cost_usd,
            "error_message": s.error_message,
            "checks": s.checks or [],
            "created_at": s.created_at.isoformat() if s.created_at else None
        })

    return {
        "workflow_run_id": run.id,
        "workflow_id": run.workflow_id,
        "status": run.status,
        "duration_ms": run.duration_ms,
        "total_tokens": run.total_tokens,
        "total_cost_usd": run.total_cost_usd,
        "final_output": run.final_output,
        "workflow_state": run.workflow_state or {},
        "checks": run.checks or [],
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "step_results": step_list
    }


def list_workflow_runs(db: Session, workflow_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Lists recent workflow executions."""
    query = db.query(WorkflowRun)
    if workflow_id:
        query = query.filter(WorkflowRun.workflow_id == workflow_id)
    runs = query.order_by(desc(WorkflowRun.created_at)).limit(limit).all()
    return [
        {
            "workflow_run_id": r.id,
            "workflow_id": r.workflow_id,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "total_tokens": r.total_tokens,
            "total_cost_usd": r.total_cost_usd,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None
        }
        for r in runs
    ]
