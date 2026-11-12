import json
import uuid
import hashlib
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
GENERIC_RESULT_SCHEMA = "evalnexus-generic-run-result/v2"
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


def _trace_event_id(scenario_run_id: str, suffix: Any) -> str:
    """Deterministic, collision-free TraceEvent PK that fits String(64).

    The previous scheme sliced f"tr_{scenario_run_id}_{seq}" to 64 chars, which
    cut off the sequence number whenever scenario_run_id was long (>= ~58 chars),
    making every event of a run collapse onto the same primary key.
    A fixed-length digest of the owning scenario run keeps ownership, and the
    sequence suffix is always preserved.
    """
    digest = hashlib.sha256(scenario_run_id.encode("utf-8")).hexdigest()[:24]
    return f"tr_{digest}_{suffix}"[:64]


def detect_incomplete_execution(
    final_answer: Optional[str],
    traces: List[Any],
    scenario: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Optional[str]:
    """Server-side, fail-closed completion check that does not trust client flags.

    Returns an error string if the artifact shows no valid standalone final answer
    or exceeded the scenario's declared limits; otherwise None.
    """
    answer = (final_answer or "").strip()
    if not answer:
        return "No final answer was produced (execution did not reach a standalone final response)."
    if "<tool_call>" in answer or "</tool_call>" in answer:
        return ("Final answer contains unresolved <tool_call> markup; the model never produced "
                "a standalone final response (max-turn exhaustion).")
    limits = (scenario or {}).get("limits") or (scenario or {}).get("execution_limits") or {}
    tool_events = [t for t in traces if getattr(t, "tool", None)]
    max_tool_calls = limits.get("max_tool_calls") if isinstance(limits, dict) else None
    if isinstance(max_tool_calls, int) and len(tool_events) > max_tool_calls:
        return f"Tool call limit exceeded ({len(tool_events)} > {max_tool_calls})."
    return None


class GenericColabTraceEvent(BaseModel):
    seq: int
    event_type: str = "TOOL_EXECUTION"
    tool: Optional[str] = None
    arguments: Optional[Any] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: int = 0
    timestamp: Optional[str] = None


class GenericColabResultImportPayload(BaseModel):
    schema_version: str = Field(default=GENERIC_RESULT_SCHEMA)
    run_id: str = Field(min_length=3, max_length=64)
    scenario_id: str = Field(min_length=3, max_length=64)
    domain: Optional[str] = Field(default="general", max_length=64)
    model_name: str = Field(default="Qwen/Qwen2.5-1.5B-Instruct (Colab Offline)", max_length=128)
    provider_type: str = Field(default="colab_offline", max_length=64)
    executed_at: Optional[str] = None
    final_answer: Optional[str] = None
    parsed_json: Optional[Dict[str, Any]] = None
    duration_ms: int = Field(default=0, ge=0)
    status: Optional[str] = "COMPLETED"
    traces: Optional[List[GenericColabTraceEvent]] = Field(default_factory=list)
    client_check_results: Optional[List[Dict[str, Any]]] = Field(default=None, alias="check_results")
    execution_error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("run_id")
    def validate_run_id_field(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 3 or len(v) > 64:
            raise ValueError("run_id must be between 3 and 64 characters.")
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

def import_generic_colab_results(
    db: Session,
    payload: Dict[str, Any],
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    Securely imports and validates an offline generic Colab evaluation result artifact (V4).
    Persists Run, ScenarioRun, TraceEvents, and independently evaluates assertions on the server.
    Guarantees:
      - Duplicate protection on run_id
      - Server-side declarative evaluation via GenericAssertionEvaluator (no client success flags trusted)
      - Zero mutation of historical DB runs or evaluation revisions
    """
    from backend.scenarios.custom_scenario_service import get_custom_scenario
    from backend.runner.generic_evaluator import GenericAssertionEvaluator
    from backend.scenarios.generic_scenario import GenericAssertion

    validated = GenericColabResultImportPayload(**payload)
    run_id = validated.run_id

    # 1. Validation & Pre-Resolution (Read-Only phase: no writes before full validation)
    validated = GenericColabResultImportPayload(**payload)
    run_id = validated.run_id

    # Duplicate detection & protection
    existing_run = db.query(Run).filter(Run.id == run_id).first()
    if existing_run:
        if not overwrite:
            raise ValueError(
                f"Duplicate import detected: Run '{run_id}' has already been imported into EvalNexus. "
                "Specify overwrite=True if you wish to re-evaluate this run."
            )

    # Scenario definition lookup
    scen_data = get_custom_scenario(db, validated.scenario_id)
    if not scen_data:
        # Fallback alias check
        if validated.scenario_id == "generic_sentiment_qwen":
            scen_data = get_custom_scenario(db, "generic_sentiment_positive")
        elif validated.scenario_id == "generic_sentiment_positive":
            scen_data = get_custom_scenario(db, "generic_sentiment_qwen")

    if not scen_data:
        # Fallback to filesystem locations relative to repository
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        custom_file = repo_root / "scenarios" / "custom" / f"{validated.scenario_id}.json"
        generic_file = repo_root / "backend" / "scenarios" / "generic" / f"{validated.scenario_id}.json"
        bundle_file = repo_root / "docs" / "scenarios" / "generic_travel_bundle.json"

        if custom_file.is_file():
            with open(custom_file, "r", encoding="utf-8") as f:
                scen_data = json.load(f)
        elif generic_file.is_file():
            with open(generic_file, "r", encoding="utf-8") as f:
                scen_data = json.load(f)
        elif bundle_file.is_file():
            with open(bundle_file, "r", encoding="utf-8") as f:
                b = json.load(f)
                if b.get("scenario", {}).get("id") == validated.scenario_id:
                    scen_data = b["scenario"]

    if not scen_data:
        raise ValueError(f"Unknown generic scenario ID '{validated.scenario_id}' in imported results.")

    assertions = [
        GenericAssertion(**a) if isinstance(a, dict) else a
        for a in scen_data.get("assertions", [])
    ]

    effective_error = validated.execution_error
    if not effective_error:
        effective_error = detect_incomplete_execution(
            validated.final_answer,
            validated.traces or [],
            scen_data,
            validated.metadata or {},
        )

    # 2. Atomic Write Transaction (All writes, evaluation, and checks committed together)
    try:
        # Delete old records if overwriting
        if existing_run and overwrite:
            old_scen_runs = db.query(ScenarioRun).filter(ScenarioRun.run_id == run_id).all()
            for osr in old_scen_runs:
                db.query(TraceEvent).filter(TraceEvent.scenario_run_id == osr.id).delete()
                db.query(CheckResult).filter(CheckResult.scenario_run_id == osr.id).delete()
            db.query(ScenarioRun).filter(ScenarioRun.run_id == run_id).delete()
            db.delete(existing_run)
            db.flush()

        # Ensure ScenarioVersion exists (flush only)
        scen_ver = db.query(ScenarioVersion).filter(ScenarioVersion.id == validated.scenario_id).first()
        if not scen_ver:
            scen_ver = ScenarioVersion(
                id=validated.scenario_id,
                name=scen_data.get("name", validated.scenario_id),
                category=scen_data.get("domain", "GENERIC").upper(),
                description=scen_data.get("description", ""),
                fixed_clock=utc_now(),
                initial_data=scen_data,
                customer_messages=scen_data.get("customer_messages", []),
                expected_checks={"EVALUATION_MODE": "GENERIC"}
            )
            db.add(scen_ver)
            db.flush()

        # Ensure AgentVersion exists (flush only)
        agent_ver_id = "qwen2.5_instruct_colab"
        agent_ver = db.query(AgentVersion).filter(AgentVersion.id == agent_ver_id).first()
        if not agent_ver:
            agent_ver = AgentVersion(
                id=agent_ver_id,
                name="Qwen2.5-1.5B-Instruct (Colab Offline)",
                system_prompt="You are an expert AI assistant. Always output structured JSON when requested.",
                model_name=validated.model_name,
                tool_schema_version="generic-v2"
            )
            db.add(agent_ver)
            db.flush()

        # Create Run Record
        run_record = Run(
            id=run_id,
            agent_version_id=agent_ver_id,
            provider_type=validated.provider_type,
            model_name=validated.model_name,
            is_mock=0,
            execution_config={
                "source": "google_colab_offline",
                "evaluation_mode": "GENERIC",
                "domain": validated.domain,
                "scenario_id": validated.scenario_id,
                "schema_version": validated.schema_version,
                "imported_at": utc_now().isoformat(),
                "client_executed_at": validated.executed_at,
                "metadata": validated.metadata or {}
            },
            status="RUNNING",
            total_scenarios=1,
            started_at=utc_now()
        )
        db.add(run_record)

        scenario_run_id = f"scen_run_{run_id}_{validated.scenario_id}"[:64]
        scenario_run = ScenarioRun(
            id=scenario_run_id,
            run_id=run_id,
            scenario_version_id=validated.scenario_id,
            status="RUNNING",
            started_at=utc_now(),
            duration_ms=validated.duration_ms
        )
        db.add(scenario_run)

        # Seed TraceEvents
        for t in validated.traces:
            t_time = datetime.datetime.fromisoformat(t.timestamp) if t.timestamp else utc_now()
            db.add(TraceEvent(
                id=_trace_event_id(scenario_run_id, t.seq),
                scenario_run_id=scenario_run_id,
                seq_num=t.seq,
                timestamp=t_time,
                duration_ms=t.duration_ms,
                event_type=t.event_type,
                tool_name=t.tool,
                tool_arguments=t.arguments if isinstance(t.arguments, dict) else ({"raw": t.arguments} if t.arguments else None),
                tool_result=t.result if isinstance(t.result, dict) else ({"raw": t.result} if t.result else None),
                error_message=t.error,
                token_usage=None,
                cost_estimate=0
            ))

        # Seed AGENT_RESPONSE trace event
        if validated.final_answer:
            db.add(TraceEvent(
                id=_trace_event_id(scenario_run_id, "resp"),
                scenario_run_id=scenario_run_id,
                seq_num=len(validated.traces) + 1,
                timestamp=utc_now(),
                duration_ms=0,
                event_type="AGENT_RESPONSE",
                tool_result={"content": validated.final_answer}
            ))

        # Flush trace events into the active transaction so evaluator queries can see them
        db.flush()

        # Server-side evaluation: evaluator does NOT commit independently (auto_commit=False)
        evaluator = GenericAssertionEvaluator(db, scenario_run_id)
        server_checks = evaluator.evaluate_all(
            assertions=assertions,
            final_answer=validated.final_answer,
            execution_error=effective_error,
            auto_commit=False
        )

        all_passed = all(c.status == "PASSED" for c in server_checks)
        scenario_run.status = "PASSED" if all_passed else "FAILED"
        scenario_run.finished_at = utc_now()

        run_record.status = "COMPLETED"
        run_record.passed_scenarios = 1 if all_passed else 0
        run_record.failed_scenarios = 0 if all_passed else 1
        run_record.finished_at = utc_now()

        # Single atomic commit for the complete import operation
        db.commit()

    except Exception:
        db.rollback()
        raise

    return {
        "status": "SUCCESS",
        "run_id": run_id,
        "scenario_id": validated.scenario_id,
        "domain": validated.domain,
        "model_name": run_record.model_name,
        "provider_type": run_record.provider_type,
        "evaluation_mode": "GENERIC",
        "passed": all_passed,
        "total_checks": len(server_checks),
        "passed_checks": sum(1 for c in server_checks if c.status == "PASSED"),
        "failed_checks": sum(1 for c in server_checks if c.status == "FAILED"),
        "check_results": [
            {
                "check_name": c.check_name,
                "status": c.status,
                "message": c.message,
                "evidence": c.evidence
            }
            for c in server_checks
        ],
        "duration_ms": validated.duration_ms
    }

def import_colab_results(
    db: Session,
    payload: Dict[str, Any],
    overwrite: bool = False
) -> Dict[str, Any]:
    """
    Securely imports and validates an offline Colab evaluation result artifact.
    Persists Run, ScenarioRun, TraceEvents, and executes server-side DeterministicEvaluator.
    Prevents duplicate imports, preserves history, and labels origin clearly.
    Supports both V1 Transactional batch results and V2 Generic evaluation results.
    """
    # Route V2 Generic Results to dedicated generic importer
    schema = payload.get("schema_version")
    if schema == GENERIC_RESULT_SCHEMA or "final_answer" in payload or payload.get("domain") in ["sentiment", "travel", "general"]:
        return import_generic_colab_results(db, payload, overwrite=overwrite)

    # 1. Pydantic validation (V1 Transactional Batch Result)
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
