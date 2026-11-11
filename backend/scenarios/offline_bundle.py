import json
import uuid
import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database.models import (
    Run, ScenarioRun, TraceEvent, CheckResult, Customer, Order, RefundRequest,
    AgentVersion, ScenarioVersion, CustomScenario, utc_now
)
from backend.scenarios.generate_suite import SCENARIOS
from backend.agent.tools_schema import TOOLS_SPEC
from backend.runner.evaluator import DeterministicEvaluator, EvaluationMode
from backend.runner.agent_runner import DEFAULT_PROMPTS


SCENARIO_BUNDLE_SCHEMA = "evalnexus-scenario-bundle/v1"
EVALUATION_RESULT_SCHEMA = "evalnexus-evaluation-result/v1"
READ_ONLY_TOOLS = ["get_order", "check_refund_eligibility"]


# -------------------------------------------------------------
# Pydantic Schemas for Validation
# -------------------------------------------------------------

class ScenarioBundleExportRequest(BaseModel):
    scenario_ids: Optional[List[str]] = None
    agent_version_id: str = Field(default="agent_v1_baseline", max_length=64)
    execution_limits: Optional[Dict[str, Any]] = None
    allowed_tools: Optional[List[str]] = None
    read_only: bool = False


class ColabTraceEvent(BaseModel):
    seq: int
    event_type: str
    tool: Optional[str] = None
    arguments: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: Optional[str] = None


class ColabRefundRecord(BaseModel):
    order_id: str
    amount_cents: int
    operation_key: str
    status: str = "REFUND_REQUESTED"
    reason: Optional[str] = None


class ColabBatchScenarioResult(BaseModel):
    scenario_id: str
    status: str = "COMPLETED"
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    refunds: List[ColabRefundRecord] = Field(default_factory=list)
    traces: List[ColabTraceEvent] = Field(default_factory=list)
    execution_error: Optional[str] = None


class ColabBatchResultImportPayload(BaseModel):
    schema_version: str
    bundle_id: str
    batch_run_id: str
    model_name: str
    agent_version_id: str = "agent_v1_baseline"
    executed_at: Optional[str] = None
    results: List[ColabBatchScenarioResult]
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("schema_version")
    def validate_schema(cls, v: str) -> str:
        if v != EVALUATION_RESULT_SCHEMA:
            raise ValueError(f"Invalid schema_version '{v}'. Expected '{EVALUATION_RESULT_SCHEMA}'.")
        return v

    @field_validator("batch_run_id")
    def validate_run_id(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 3 or len(v) > 64:
            raise ValueError("batch_run_id must be between 3 and 64 characters.")
        return v


# -------------------------------------------------------------
# Export Implementation
# -------------------------------------------------------------

def export_scenario_bundle(
    scenario_ids: Optional[List[str]] = None,
    agent_version_id: str = "agent_v1_baseline",
    execution_limits: Optional[Dict[str, Any]] = None,
    allowed_tools: Optional[List[str]] = None,
    read_only: bool = False,
    bundle_id: Optional[str] = None,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Produces a portable, self-contained JSON scenario bundle for Colab evaluation.
    Contains zero secrets, zero private credentials, and purely synthetic fixtures.
    """
    limits = {
        "max_turns": 4 if read_only else 6,
        "max_tool_calls": 4 if read_only else 10,
        "max_tokens_budget": 5000 if read_only else 15000,
        "scenario_timeout_sec": 30.0
    }
    if execution_limits:
        limits.update(execution_limits)

    agent_info = DEFAULT_PROMPTS.get(agent_version_id, DEFAULT_PROMPTS["agent_v1_baseline"])

    # Filter tool definitions if read_only or explicit allowed_tools specified
    if read_only:
        target_tool_names = set(allowed_tools or READ_ONLY_TOOLS)
    elif allowed_tools:
        target_tool_names = set(allowed_tools)
    else:
        target_tool_names = None

    if target_tool_names is not None:
        filtered_tools = [t for t in TOOLS_SPEC if t["function"]["name"] in target_tool_names]
    else:
        filtered_tools = list(TOOLS_SPEC)

    # Lookup requested scenarios from standard suite
    scenario_lookup = {s["id"]: s for s in SCENARIOS}

    # Also lookup in custom scenarios table if DB session provided
    if db:
        custom_scens = db.query(CustomScenario).all()
        for cs in custom_scens:
            scenario_lookup[cs.id] = cs.scenario_data

    if scenario_ids:
        missing = [sid for sid in scenario_ids if sid not in scenario_lookup]
        if missing:
            raise ValueError(f"Scenarios not found: {missing}")
        selected_scenarios = [scenario_lookup[sid] for sid in scenario_ids]
    else:
        # Default: export all benchmark scenarios
        selected_scenarios = list(SCENARIOS)

    # Sanitize scenario data: ensure no secrets or sensitive data
    sanitized_scenarios = []
    for s in selected_scenarios:
        clean_s = {
            "id": s["id"],
            "name": s["name"],
            "category": s.get("category", "NORMAL"),
            "description": s.get("description", ""),
            "fixed_clock": s["fixed_clock"],
            "initial_data": s["initial_data"],
            "customer_messages": s["customer_messages"],
            "fault_configs": s.get("fault_configs", {}),
            "expected_checks": s.get("expected_checks", {})
        }
        if "target_order_id" in s:
            clean_s["target_order_id"] = s["target_order_id"]
        sanitized_scenarios.append(clean_s)

    bid = bundle_id or f"bundle_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    bundle = {
        "schema_version": SCENARIO_BUNDLE_SCHEMA,
        "bundle_id": bid,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_platform": "EvalNexus",
        "agent_metadata": {
            "agent_version_id": agent_version_id,
            "name": agent_info["name"],
            "system_prompt": agent_info["system_prompt"],
            "tool_schema_version": "v1"
        },
        "tools": filtered_tools,
        "read_only": read_only or (target_tool_names == set(READ_ONLY_TOOLS)),
        "execution_limits": limits,
        "total_scenarios": len(sanitized_scenarios),
        "scenarios": sanitized_scenarios
    }
    return bundle


def export_scenario_bundle_to_file(
    file_path: str,
    scenario_ids: Optional[List[str]] = None,
    agent_version_id: str = "agent_v1_baseline",
    execution_limits: Optional[Dict[str, Any]] = None,
    allowed_tools: Optional[List[str]] = None,
    read_only: bool = False,
    db: Optional[Session] = None
) -> str:
    """Exports scenario bundle directly to a local JSON file."""
    bundle = export_scenario_bundle(
        scenario_ids=scenario_ids,
        agent_version_id=agent_version_id,
        execution_limits=execution_limits,
        allowed_tools=allowed_tools,
        read_only=read_only,
        db=db
    )
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    return file_path


# -------------------------------------------------------------
# Import Implementation
# -------------------------------------------------------------

def import_colab_results(
    db: Session,
    payload: Dict[str, Any],
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    Securely imports and validates an offline Colab evaluation result artifact.
    Persists Run, ScenarioRun, TraceEvents, and executes server-side DeterministicEvaluator.
    Prevents duplicate imports, preserves history, and labels origin clearly.
    """
    # 1. Pydantic validation
    validated = ColabBatchResultImportPayload(**payload)
    batch_run_id = validated.batch_run_id

    # 2. Duplicate detection
    existing_run = db.query(Run).filter(Run.id == batch_run_id).first()
    if existing_run:
        if not overwrite:
            raise ValueError(
                f"Duplicate import detected: Run '{batch_run_id}' has already been imported into EvalNexus. "
                "Specify overwrite=True if you wish to re-evaluate this run."
            )
        # Delete existing run and its children if overwrite permitted
        old_scen_runs = db.query(ScenarioRun).filter(ScenarioRun.run_id == batch_run_id).all()
        for osr in old_scen_runs:
            db.query(Customer).filter(Customer.scenario_run_id == osr.id).delete()
            db.query(Order).filter(Order.scenario_run_id == osr.id).delete()
            db.query(RefundRequest).filter(RefundRequest.scenario_run_id == osr.id).delete()
            db.query(TraceEvent).filter(TraceEvent.scenario_run_id == osr.id).delete()
            db.query(CheckResult).filter(CheckResult.scenario_run_id == osr.id).delete()
        db.query(ScenarioRun).filter(ScenarioRun.run_id == batch_run_id).delete()
        db.delete(existing_run)
        db.commit()

    # 3. Build scenario lookup table
    scenario_lookup = {s["id"]: s for s in SCENARIOS}
    custom_scens = db.query(CustomScenario).all()
    for cs in custom_scens:
        scenario_lookup[cs.id] = cs.scenario_data

    # Validate that all scenario IDs are known
    for r in validated.results:
        if r.scenario_id not in scenario_lookup:
            raise ValueError(f"Unknown scenario ID '{r.scenario_id}' in imported results.")

    # 4. Ensure AgentVersion exists
    agent_ver = db.query(AgentVersion).filter(AgentVersion.id == validated.agent_version_id).first()
    if not agent_ver:
        p_info = DEFAULT_PROMPTS.get(validated.agent_version_id, DEFAULT_PROMPTS["agent_v1_baseline"])
        agent_ver = AgentVersion(
            id=validated.agent_version_id,
            name=p_info["name"],
            system_prompt=p_info["system_prompt"],
            model_name=validated.model_name,
            tool_schema_version="v1"
        )
        db.add(agent_ver)
        db.commit()

    # 5. Create Run Record
    total_scenarios = len(validated.results)
    run_record = Run(
        id=batch_run_id,
        agent_version_id=validated.agent_version_id,
        provider_type="colab_offline",
        model_name=f"{validated.model_name} (Colab Offline)",
        is_mock=0,
        execution_config={
            "source": "google_colab_offline",
            "bundle_id": validated.bundle_id,
            "imported_at": utc_now().isoformat(),
            "client_executed_at": validated.executed_at,
            "metadata": validated.metadata or {}
        },
        status="RUNNING",
        total_scenarios=total_scenarios,
        started_at=utc_now()
    )
    db.add(run_record)
    db.commit()

    passed_count = 0
    failed_count = 0
    total_duration_ms = 0

    # 6. Import each ScenarioRun
    for res in validated.results:
        scen_id = res.scenario_id
        scen_data = scenario_lookup[scen_id]
        fixed_clock = datetime.datetime.fromisoformat(scen_data["fixed_clock"])

        # Ensure ScenarioVersion exists
        scen_ver = db.query(ScenarioVersion).filter(ScenarioVersion.id == scen_id).first()
        if not scen_ver:
            scen_ver = ScenarioVersion(
                id=scen_id,
                name=scen_data["name"],
                category=scen_data.get("category", "NORMAL"),
                description=scen_data.get("description", ""),
                fixed_clock=fixed_clock,
                initial_data=scen_data["initial_data"],
                customer_messages=scen_data["customer_messages"],
                fault_configs=scen_data.get("fault_configs", {}),
                expected_checks=scen_data.get("expected_checks", {})
            )
            db.add(scen_ver)
            db.commit()

        scenario_run_id = f"scen_run_{batch_run_id}_{scen_id}"
        scenario_run = ScenarioRun(
            id=scenario_run_id,
            run_id=batch_run_id,
            scenario_version_id=scen_id,
            status="RUNNING",
            started_at=utc_now(),
            duration_ms=res.duration_ms
        )
        db.add(scenario_run)
        db.commit()

        total_duration_ms += res.duration_ms

        # Seed Customer
        cust_info = scen_data["initial_data"]["customer"]
        customer = Customer(
            id=cust_info["id"],
            scenario_run_id=scenario_run_id,
            name=cust_info["name"],
            email=cust_info["email"],
            created_at=fixed_clock - datetime.timedelta(days=30)
        )
        db.add(customer)

        # Seed Orders
        for ord_info in scen_data["initial_data"].get("orders", []):
            deliv_date = None
            if ord_info.get("delivery_date"):
                deliv_date = datetime.datetime.fromisoformat(ord_info["delivery_date"])

            order = Order(
                id=ord_info["id"],
                scenario_run_id=scenario_run_id,
                customer_id=ord_info.get("customer_id", customer.id),
                status=ord_info["status"],
                total_amount_cents=ord_info["total_amount_cents"],
                currency=ord_info.get("currency", "USD"),
                delivery_date=deliv_date,
                created_at=fixed_clock - datetime.timedelta(days=10)
            )
            db.add(order)

        # Seed Refunds if created during execution
        for ref_item in res.refunds:
            ref = RefundRequest(
                id=f"ref_{scenario_run_id}_{ref_item.order_id}",
                scenario_run_id=scenario_run_id,
                order_id=ref_item.order_id,
                amount_cents=ref_item.amount_cents,
                status=ref_item.status,
                operation_key=ref_item.operation_key,
                reason=ref_item.reason or "Customer refund via Colab execution",
                created_at=utc_now()
            )
            db.add(ref)

        # Seed TraceEvents
        for t in res.traces:
            t_time = datetime.datetime.fromisoformat(t.timestamp) if t.timestamp else utc_now()
            
            t_args = t.arguments
            if isinstance(t_args, str):
                try:
                    t_args = json.loads(t_args)
                except Exception:
                    pass

            t_res = t.result
            if isinstance(t_res, str):
                try:
                    t_res = json.loads(t_res)
                except Exception:
                    pass

            db.add(TraceEvent(
                id=f"tr_{scenario_run_id}_{t.seq}",
                scenario_run_id=scenario_run_id,
                seq_num=t.seq,
                timestamp=t_time,
                duration_ms=t.duration_ms,
                event_type=t.event_type,
                tool_name=t.tool,
                tool_arguments=t_args,
                tool_result=t_res,
                error_message=t.error,
                token_usage={"prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens},
                cost_estimate=0
            ))

        db.commit()

        # Run DeterministicEvaluator with explicit evaluation mode detection
        is_read_only = bool(
            (validated.metadata and (
                validated.metadata.get("read_only") is True or
                validated.metadata.get("scenario_mode") in ["single_scenario_read_only", "read_only", "read_only_inquiry"]
            )) or
            scen_data.get("initial_data", {}).get("read_only") is True or
            scen_data.get("category") in ["READ_ONLY", "INQUIRY"]
        )
        eval_mode = EvaluationMode.READ_ONLY_INQUIRY.value if is_read_only else EvaluationMode.FULL_MUTATION.value

        evaluator = DeterministicEvaluator(db, scenario_run_id, evaluation_mode=eval_mode)
        target_order_id = scen_data.get("target_order_id", scen_data["initial_data"]["orders"][0]["id"])
        check_results = evaluator.evaluate(
            customer_id=customer.id,
            order_id=target_order_id,
            expected_checks=scen_data.get("expected_checks", {}),
            execution_error=res.execution_error,
            evaluation_mode=eval_mode
        )

        all_passed = all(c.status == "PASSED" for c in check_results)
        scenario_run.status = "PASSED" if all_passed else "FAILED"
        scenario_run.finished_at = utc_now()
        if all_passed:
            passed_count += 1
        else:
            failed_count += 1

    # 7. Finalize Run Record
    run_record.status = "COMPLETED"
    run_record.passed_scenarios = passed_count
    run_record.failed_scenarios = failed_count
    run_record.finished_at = utc_now()
    db.commit()

    return {
        "status": "SUCCESS",
        "run_id": batch_run_id,
        "bundle_id": validated.bundle_id,
        "model_name": run_record.model_name,
        "provider_type": run_record.provider_type,
        "total_scenarios": total_scenarios,
        "passed_scenarios": passed_count,
        "failed_scenarios": failed_count,
        "duration_ms": total_duration_ms
    }


def import_colab_results_from_file(
    file_path: str,
    db: Session,
    overwrite: bool = False
) -> Dict[str, Any]:
    """Reads JSON from file and calls import_colab_results."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return import_colab_results(db, data, overwrite=overwrite)
