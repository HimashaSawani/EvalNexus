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
    ScenarioVersion
)
from backend.domain.refund_service import RefundService, RefundDomainError
from backend.runner.trace_logger import TraceLogger
from backend.runner.evaluator import DeterministicEvaluator


class ScriptedRunner:
    def __init__(self, db: Session):
        self.db = db

    def run_scenario(
        self,
        scenario_data: Dict[str, Any],
        agent_version_id: Optional[str] = "agent_scripted_baseline",
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a deterministic scripted scenario:
        1. Sets up DB fixtures
        2. Executes tools in strict sequence (mocking agent tool calling)
        3. Logs trace events
        4. Evaluates outcome against assertions
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        scenario_run_id = f"scen_run_{uuid.uuid4().hex[:8]}"
        scenario_version_id = scenario_data.get("id", f"scen_{uuid.uuid4().hex[:6]}")

        # Ensure AgentVersion exists
        agent_ver = self.db.query(AgentVersion).filter(AgentVersion.id == agent_version_id).first()
        if not agent_ver:
            agent_ver = AgentVersion(
                id=agent_version_id,
                name="Scripted Tool-Calling Baseline",
                system_prompt="Standard deterministic scripted runner baseline",
                model_name="scripted-v1",
                tool_schema_version="v1"
            )
            self.db.add(agent_ver)
            self.db.commit()

        # Parse fixed clock
        fixed_clock_raw = scenario_data.get("fixed_clock", "2026-10-23T10:00:00")
        if isinstance(fixed_clock_raw, str):
            fixed_clock = datetime.datetime.fromisoformat(fixed_clock_raw)
        else:
            fixed_clock = fixed_clock_raw

        # Ensure ScenarioVersion exists
        scen_ver = self.db.query(ScenarioVersion).filter(ScenarioVersion.id == scenario_version_id).first()
        if not scen_ver:
            scen_ver = ScenarioVersion(
                id=scenario_version_id,
                name=scenario_data.get("name", "Eligible Order Refund"),
                category=scenario_data.get("category", "NORMAL"),
                description=scenario_data.get("description", "Customer requests refund for eligible order"),
                fixed_clock=fixed_clock,
                initial_data=scenario_data.get("initial_data", {}),
                customer_messages=scenario_data.get("customer_messages", ["I want a refund for my order."]),
                fault_configs=scenario_data.get("fault_configs", {}),
                expected_checks=scenario_data.get("expected_checks", {"ELIGIBILITY": "PASSED", "OWNERSHIP": "PASSED", "DUPLICATE": "PASSED", "STATE": "PASSED"})
            )
            self.db.add(scen_ver)
            self.db.commit()

        # Create or reuse Run record
        run_record = self.db.query(Run).filter(Run.id == run_id).first()
        if not run_record:
            run_record = Run(
                id=run_id,
                agent_version_id=agent_version_id,
                status="RUNNING",
                total_scenarios=1,
                started_at=datetime.datetime.now(datetime.timezone.utc)
            )
            self.db.add(run_record)

        # Create ScenarioRun record
        scenario_run = ScenarioRun(
            id=scenario_run_id,
            run_id=run_id,
            scenario_version_id=scenario_version_id,
            status="RUNNING",
            started_at=datetime.datetime.now(datetime.timezone.utc)
        )
        self.db.add(scenario_run)
        self.db.commit()

        trace_logger = TraceLogger(self.db, scenario_run_id)

        # 1. Setup Fixture Data in DB
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

        # 2. Execution Start
        start_time = time.time()
        service = RefundService(self.db, scenario_run_id=scenario_run_id, fixed_clock=fixed_clock)

        target_order_id = scenario_data.get("target_order_id", scenario_data["initial_data"]["orders"][0]["id"])
        session_customer_id = customer.id

        # Log User Message
        user_msg = scenario_data["customer_messages"][0]
        trace_logger.log_event(
            event_type="USER_MESSAGE",
            tool_name=None,
            tool_arguments={"message": user_msg}
        )

        execution_error = None

        try:
            # Step A: Call get_order
            t0 = time.time()
            order_res = service.get_order(session_customer_id, target_order_id)
            d0 = int((time.time() - t0) * 1000)
            trace_logger.log_event(
                event_type="TOOL_CALL",
                tool_name="get_order",
                tool_arguments={"order_id": target_order_id},
                tool_result=order_res,
                duration_ms=d0
            )

            # Step B: Call check_refund_eligibility
            t1 = time.time()
            eligibility_res = service.check_refund_eligibility(session_customer_id, target_order_id)
            d1 = int((time.time() - t1) * 1000)
            trace_logger.log_event(
                event_type="TOOL_CALL",
                tool_name="check_refund_eligibility",
                tool_arguments={"order_id": target_order_id},
                tool_result=eligibility_res,
                duration_ms=d1
            )

            # Step C: If eligible, call request_refund
            if eligibility_res["eligible"]:
                t2 = time.time()
                op_key = f"op_scripted_{target_order_id}_{int(fixed_clock.timestamp())}"
                refund_res = service.request_refund(
                    session_customer_id=session_customer_id,
                    order_id=target_order_id,
                    amount_cents=eligibility_res["max_refundable_cents"],
                    operation_key=op_key,
                    reason="Scripted automated customer refund request"
                )
                d2 = int((time.time() - t2) * 1000)
                trace_logger.log_event(
                    event_type="TOOL_CALL",
                    tool_name="request_refund",
                    tool_arguments={
                        "order_id": target_order_id,
                        "amount_cents": eligibility_res["max_refundable_cents"],
                        "operation_key": op_key
                    },
                    tool_result=refund_res,
                    duration_ms=d2
                )
            else:
                trace_logger.log_event(
                    event_type="AGENT_DECISION",
                    tool_name=None,
                    tool_arguments={"decision": "Refund rejected based on policy", "reason": eligibility_res["message"]}
                )

        except RefundDomainError as rde:
            execution_error = f"RefundDomainError [{rde.code}]: {rde.message}"
            trace_logger.log_event(
                event_type="ERROR",
                tool_name=None,
                error_message=execution_error
            )
        except Exception as e:
            execution_error = f"Unexpected Exception: {str(e)}"
            trace_logger.log_event(
                event_type="ERROR",
                tool_name=None,
                error_message=execution_error
            )

        total_duration_ms = int((time.time() - start_time) * 1000)

        # 3. Deterministic Evaluation
        evaluator = DeterministicEvaluator(self.db, scenario_run_id)
        check_results = evaluator.evaluate(
            customer_id=session_customer_id,
            order_id=target_order_id,
            expected_checks=scenario_data.get("expected_checks", {}),
            execution_error=execution_error if scenario_data.get("expect_error") is not True else None
        )

        all_passed = all(c.status == "PASSED" for c in check_results)
        scenario_run.status = "PASSED" if all_passed else "FAILED"
        scenario_run.finished_at = datetime.datetime.now(datetime.timezone.utc)
        scenario_run.duration_ms = total_duration_ms

        if (run_record.total_scenarios or 1) <= 1:
            run_record.status = "COMPLETED"
            run_record.finished_at = datetime.datetime.now(datetime.timezone.utc)
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
            "scenario_name": scen_ver.name,
            "status": scenario_run.status,
            "duration_ms": total_duration_ms,
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
