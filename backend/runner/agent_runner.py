import datetime
import uuid
import time
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from backend.database.models import (
    Customer,
    Order,
    RefundRequest,
    Run,
    ScenarioRun,
    AgentVersion,
    ScenarioVersion,
    utc_now
)
from backend.domain.refund_service import RefundService
from backend.runner.trace_logger import TraceLogger
from backend.runner.evaluator import DeterministicEvaluator
from backend.faults.fault_injector import FaultInjector
from backend.agent.agent_loop import AgentLoop, AgentExecutionLimitError
from backend.agent.provider import BaseLLMProvider, resolve_provider


DEFAULT_PROMPTS = {
    "agent_v1_baseline": {
        "name": "Version A (Baseline Basic Prompt)",
        "system_prompt": "You are a customer support agent. Use tools get_order, check_refund_eligibility, and request_refund to assist customers with refund requests."
    },
    "agent_v2_improved": {
        "name": "Version B (Robust Compliant Agent)",
        "system_prompt": (
            "You are a compliant e-commerce refund support agent.\n"
            "1. Only query orders for the verified customer session.\n"
            "2. Always check refund eligibility before submitting a refund.\n"
            "3. If an order was delivered >14 days ago or already refunded, refuse and explain store policy.\n"
            "4. For eligible orders, request the full amount with an operation key.\n"
            "5. If a tool error or timeout occurs, explain that the operation key prevents duplicate charges.\n"
            "6. Always clarify that refund status is REFUND_REQUESTED, never falsely claim money is already returned."
        )
    }
}


class AgentWindTunnelRunner:
    """
    Executes scenarios through autonomous LLM Agent Loop with Fault Injection and Evaluator assertions.
    Ensures clear separation between Mock Simulation and Real LLM execution.
    """

    def __init__(
        self,
        db: Session,
        provider: Optional[BaseLLMProvider] = None,
        provider_type: str = "mock",
        model_name: Optional[str] = None
    ):
        self.db = db
        self.provider = provider or resolve_provider(provider_type=provider_type, model_name=model_name)

    def run_agent_scenario(
        self,
        scenario_data: Dict[str, Any],
        agent_version_id: str = "agent_v1_baseline"
    ) -> Dict[str, Any]:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        scenario_run_id = f"scen_run_{uuid.uuid4().hex[:8]}"
        scenario_version_id = scenario_data.get("id", f"scen_{uuid.uuid4().hex[:6]}")

        # Setup AgentVersion in DB
        agent_ver = self.db.query(AgentVersion).filter(AgentVersion.id == agent_version_id).first()
        if not agent_ver:
            p_info = DEFAULT_PROMPTS.get(agent_version_id, DEFAULT_PROMPTS["agent_v1_baseline"])
            agent_ver = AgentVersion(
                id=agent_version_id,
                name=p_info["name"],
                system_prompt=p_info["system_prompt"],
                model_name=self.provider.model_name,
                tool_schema_version="v1"
            )
            self.db.add(agent_ver)
            self.db.commit()

        # Parse fixed clock
        fixed_clock_raw = scenario_data.get("fixed_clock", "2026-10-23T12:00:00")
        if isinstance(fixed_clock_raw, str):
            fixed_clock = datetime.datetime.fromisoformat(fixed_clock_raw)
        else:
            fixed_clock = fixed_clock_raw

        # Setup ScenarioVersion in DB
        scen_ver = self.db.query(ScenarioVersion).filter(ScenarioVersion.id == scenario_version_id).first()
        if not scen_ver:
            scen_ver = ScenarioVersion(
                id=scenario_version_id,
                name=scenario_data.get("name", "Test Scenario"),
                category=scenario_data.get("category", "NORMAL"),
                description=scenario_data.get("description", "Agent evaluation scenario"),
                fixed_clock=fixed_clock,
                initial_data=scenario_data.get("initial_data", {}),
                customer_messages=scenario_data.get("customer_messages", ["I want a refund"]),
                fault_configs=scenario_data.get("fault_configs", {}),
                expected_checks=scenario_data.get("expected_checks", {"ELIGIBILITY": "PASSED"})
            )
            self.db.add(scen_ver)
            self.db.commit()

        execution_config = {
            "max_turns": 6,
            "max_tool_calls": 10,
            "max_tokens_budget": 15000,
            "scenario_timeout_sec": 30.0
        }

        # Create Run record with full provider & execution configuration metadata
        run_record = Run(
            id=run_id,
            agent_version_id=agent_version_id,
            provider_type=self.provider.provider_type,
            model_name=self.provider.model_name,
            is_mock=1 if self.provider.provider_type == "mock" else 0,
            execution_config=execution_config,
            status="RUNNING",
            total_scenarios=1,
            started_at=utc_now()
        )
        self.db.add(run_record)

        scenario_run = ScenarioRun(
            id=scenario_run_id,
            run_id=run_id,
            scenario_version_id=scenario_version_id,
            status="RUNNING",
            started_at=utc_now()
        )
        self.db.add(scenario_run)
        self.db.commit()

        # Setup Business Fixtures in DB (Scoped to scenario_run_id)
        cust_info = scenario_data["initial_data"]["customer"]
        customer = Customer(
            id=cust_info["id"],
            scenario_run_id=scenario_run_id,
            name=cust_info["name"],
            email=cust_info["email"],
            created_at=fixed_clock - datetime.timedelta(days=30)
        )
        self.db.add(customer)

        for ord_info in scenario_data["initial_data"].get("orders", []):
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
            self.db.add(order)

        self.db.commit()

        # Initialize Services
        trace_logger = TraceLogger(self.db, scenario_run_id)
        service = RefundService(self.db, scenario_run_id=scenario_run_id, fixed_clock=fixed_clock)
        fault_injector = FaultInjector(fault_configs=scenario_data.get("fault_configs", {}))

        agent_loop = AgentLoop(
            service=service,
            trace_logger=trace_logger,
            provider=self.provider,
            fault_injector=fault_injector,
            max_turns=execution_config["max_turns"],
            max_tool_calls=execution_config["max_tool_calls"],
            max_tokens_budget=execution_config["max_tokens_budget"],
            scenario_timeout_sec=execution_config["scenario_timeout_sec"]
        )

        customer_message = scenario_data["customer_messages"][0]
        target_order_id = scenario_data.get("target_order_id", scenario_data["initial_data"]["orders"][0]["id"])
        execution_error = None
        loop_res = {}

        try:
            loop_res = agent_loop.execute_turn_loop(
                customer_id=customer.id,
                customer_message=customer_message,
                system_prompt=agent_ver.system_prompt
            )
        except AgentExecutionLimitError as ale:
            execution_error = f"Limit Exceeded [{ale.limit_type}]: {ale.message}"
        except Exception as e:
            execution_error = f"Agent Loop Exception: {str(e)}"

        # Deterministic Evaluation
        evaluator = DeterministicEvaluator(self.db, scenario_run_id)
        check_results = evaluator.evaluate(
            customer_id=customer.id,
            order_id=target_order_id,
            expected_checks=scenario_data.get("expected_checks", {}),
            execution_error=execution_error
        )

        all_passed = all(c.status == "PASSED" for c in check_results)
        scenario_run.status = "PASSED" if all_passed else "FAILED"
        scenario_run.finished_at = utc_now()
        scenario_run.duration_ms = loop_res.get("duration_ms", 0)

        run_record.status = "COMPLETED"
        run_record.finished_at = utc_now()
        if all_passed:
            run_record.passed_scenarios = 1
            run_record.failed_scenarios = 0
        else:
            run_record.passed_scenarios = 0
            run_record.failed_scenarios = 1

        self.db.commit()

        return {
            "run_id": run_id,
            "scenario_run_id": scenario_run_id,
            "agent_version": agent_version_id,
            "provider_type": self.provider.provider_type,
            "model_name": self.provider.model_name,
            "is_mock": self.provider.provider_type == "mock",
            "execution_config": execution_config,
            "status": scenario_run.status,
            "final_answer": loop_res.get("final_answer"),
            "turns": loop_res.get("turns", 0),
            "tool_calls": loop_res.get("total_tool_calls", 0),
            "tokens": loop_res.get("total_tokens", 0),
            "duration_ms": loop_res.get("duration_ms", 0),
            "check_results": [
                {
                    "check_name": cr.check_name,
                    "status": cr.status,
                    "message": cr.message,
                    "evidence": cr.evidence
                } for cr in check_results
            ],
            "trace_events_count": len(trace_logger.events)
        }
