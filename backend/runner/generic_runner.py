import time
import json
import uuid
import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.database.models import (
    Run,
    ScenarioRun,
    ScenarioVersion,
    AgentVersion,
    TraceEvent,
    CheckResult,
    utc_now
)
from backend.runner.trace_logger import TraceLogger
from backend.runner.generic_evaluator import GenericAssertionEvaluator
from backend.scenarios.generic_scenario import (
    GenericScenarioPayload,
    GenericAssertion,
    is_generic_scenario
)
from backend.agent.provider import (
    BaseLLMProvider,
    LLMResponse,
    resolve_provider,
    calculate_cost_microcents,
    sanitize_secret,
    COST_DISCLAIMER
)


# Standard safe allowlisted synthetic tools
def execute_safe_synthetic_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    tool_contracts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Safely dispatches synthetic tools with zero host access or arbitrary execution.
    """
    if tool_name == "echo_tool":
        msg = arguments.get("message") or arguments.get("text") or str(arguments)
        return {"echo": msg, "status": "ok"}

    if tool_name == "check_weather":
        city = (
            arguments.get("city")
            or arguments.get("destination")
            or arguments.get("location")
            or "Tokyo"
        )
        return {
            "city": city,
            "temperature_c": 22,
            "condition": "Sunny",
            "humidity_pct": 55,
            "forecast": f"Clear skies and mild temperature in {city}."
        }

    if tool_name == "lookup_poi":
        city = (
            arguments.get("city")
            or arguments.get("destination")
            or arguments.get("location")
            or "Tokyo"
        )
        category = arguments.get("category") or "sightseeing"
        return {
            "city": city,
            "category": category,
            "pois": [
                {"name": f"{city} Historic Square", "type": "historic", "rating": 4.8},
                {"name": f"{city} Central Museum", "type": "museum", "rating": 4.7},
                {"name": f"{city} Skyline Tower", "type": "viewpoint", "rating": 4.9}
            ]
        }

    # Check if tool is declared in custom scenario tool contracts
    contract_match = next((tc for tc in tool_contracts if tc.get("name") == tool_name), None)
    if contract_match:
        return {
            "status": "ok",
            "tool": tool_name,
            "handled_by": contract_match.get("handler_type", "synthetic_stub"),
            "data": arguments
        }

    # Prohibited or unauthorized tool
    return {
        "error": f"Tool '{tool_name}' is not permitted in this evaluation scenario.",
        "code": "TOOL_NOT_PERMITTED"
    }


class GenericMockAgent:
    """
    Smart deterministic mock agent for generic scenario domains.
    Provides realistic responses for Sentiment, Travel, and general generic domains
    when running without live network or external LLM credentials.
    """

    def __init__(self, model_name: str = "mock-generic-v1"):
        self.model_name = model_name
        self.provider_type = "mock"

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        domain: str = "general",
        input_data: Optional[Dict[str, Any]] = None,
        turn_num: int = 1
    ) -> LLMResponse:
        domain_clean = (domain or "").lower()
        input_data = input_data or {}

        # 1. Sentiment Domain Mock
        if domain_clean in ["sentiment", "sentiment_classification"]:
            text = (
                input_data.get("text")
                or input_data.get("message")
                or messages[-1].get("content")
                or ""
            )
            text_lower = text.lower()
            negative_keywords = ["bad", "terrible", "awful", "hate", "frustrat", "slow", "broken", "worst"]
            is_negative = any(w in text_lower for w in negative_keywords)

            if is_negative:
                payload = {
                    "sentiment": "NEGATIVE",
                    "score": 0.12,
                    "confidence": 0.94,
                    "summary": "Customer expressed frustration and dissatisfaction."
                }
            else:
                payload = {
                    "sentiment": "POSITIVE",
                    "score": 0.96,
                    "confidence": 0.99,
                    "summary": "Customer expressed high satisfaction with product and service."
                }
            return LLMResponse(
                content=json.dumps(payload, indent=2),
                tool_calls=[],
                prompt_tokens=180,
                completion_tokens=45
            )

        # 2. Travel Itinerary Domain Mock
        if domain_clean in ["travel", "travel_planner", "itinerary"]:
            dest = (
                input_data.get("destination")
                or input_data.get("city")
                or "Tokyo"
            )
            days = input_data.get("days", 3)

            tool_results = {}
            for m in messages:
                if m.get("role") == "tool":
                    tool_results[m.get("name")] = m.get("content")

            # Step 1: Call check_weather if available
            has_weather_tool = any(t.get("function", {}).get("name") == "check_weather" for t in tools)
            if has_weather_tool and "check_weather" not in tool_results:
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": f"call_weather_{uuid.uuid4().hex[:6]}",
                        "type": "function",
                        "function": {
                            "name": "check_weather",
                            "arguments": json.dumps({"city": dest})
                        }
                    }],
                    prompt_tokens=220,
                    completion_tokens=30
                )

            # Step 2: Call lookup_poi if available
            has_poi_tool = any(t.get("function", {}).get("name") == "lookup_poi" for t in tools)
            if has_poi_tool and "lookup_poi" not in tool_results:
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": f"call_poi_{uuid.uuid4().hex[:6]}",
                        "type": "function",
                        "function": {
                            "name": "lookup_poi",
                            "arguments": json.dumps({"city": dest, "category": "attractions"})
                        }
                    }],
                    prompt_tokens=260,
                    completion_tokens=30
                )

            # Step 3: Return final structured itinerary
            itinerary_days = []
            for d in range(1, days + 1):
                itinerary_days.append({
                    "day": d,
                    "activity": f"Visit {dest} Top Attraction {d}",
                    "weather": "Sunny"
                })

            payload = {
                "destination": dest,
                "days": days,
                "status": "PLANNED",
                "itinerary": {
                    "days": itinerary_days
                }
            }
            return LLMResponse(
                content=json.dumps(payload, indent=2),
                tool_calls=[],
                prompt_tokens=320,
                completion_tokens=90
            )

        # 3. General Fallback Domain Mock
        payload = {
            "status": "SUCCESS",
            "message": "Task completed successfully.",
            "data": input_data
        }
        return LLMResponse(
            content=json.dumps(payload, indent=2),
            tool_calls=[],
            prompt_tokens=150,
            completion_tokens=35
        )


class GenericAgentRunner:
    """
    Executes cross-domain generic scenarios (Sentiment, Travel, Finance, Coding, etc.)
    with strict isolation, safe allowlisted tools, and declarative assertion evaluation.
    """

    def __init__(
        self,
        db: Session,
        provider: Optional[BaseLLMProvider] = None,
        provider_type: str = "mock",
        model_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        auth_header_name: Optional[str] = None,
        auth_token: Optional[str] = None
    ):
        self.db = db
        self.provider_type = (provider_type or "mock").lower()
        self.model_name = model_name or "mock-generic-v1"
        self.endpoint_url = endpoint_url
        self.auth_header_name = auth_header_name
        self.auth_token = auth_token

        if provider:
            self.provider = provider
        elif self.provider_type == "mock":
            self.provider = GenericMockAgent(model_name=self.model_name)
        else:
            self.provider = resolve_provider(
                provider_type=self.provider_type,
                model_name=self.model_name,
                endpoint_url=self.endpoint_url,
                auth_header_name=self.auth_header_name,
                auth_token=self.auth_token
            )

    def run_generic_scenario(
        self,
        scenario_data: Dict[str, Any],
        agent_version_id: str = "agent_v1_baseline",
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a Generic V2 Scenario through multi-turn loop and evaluates declarative assertions.
        """
        # Parse payload
        if not isinstance(scenario_data, GenericScenarioPayload):
            scenario = GenericScenarioPayload(**scenario_data)
        else:
            scenario = scenario_data

        queue_owned = run_id is not None
        run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        scenario_run_id = f"scen_run_{uuid.uuid4().hex[:8]}"
        scenario_version_id = scenario.id

        # Setup AgentVersion record if missing
        agent_ver = self.db.query(AgentVersion).filter(AgentVersion.id == agent_version_id).first()
        if not agent_ver:
            agent_ver = AgentVersion(
                id=agent_version_id,
                name=f"Generic Agent ({agent_version_id})",
                system_prompt="You are a helpful AI assistant. Always output structured JSON when requested.",
                model_name=self.model_name,
                tool_schema_version="generic-v2"
            )
            self.db.add(agent_ver)
            self.db.commit()

        # Setup ScenarioVersion record if missing
        scen_ver = self.db.query(ScenarioVersion).filter(ScenarioVersion.id == scenario_version_id).first()
        if not scen_ver:
            scen_ver = ScenarioVersion(
                id=scenario_version_id,
                name=scenario.name,
                category=scenario.domain.upper(),
                description=scenario.description or f"Generic scenario for {scenario.domain}",
                fixed_clock=datetime.datetime.now(datetime.timezone.utc),
                initial_data=scenario.model_dump(),
                customer_messages=scenario.customer_messages or [json.dumps(scenario.input)],
                fault_configs={},
                expected_checks={"EVALUATION_MODE": "GENERIC"}
            )
            self.db.add(scen_ver)
            self.db.commit()

        # Execution limits
        limits = scenario.execution_limits
        exec_config = {
            "max_turns": limits.max_turns,
            "max_tool_calls": limits.max_tool_calls,
            "max_tokens_budget": limits.max_tokens_budget,
            "scenario_timeout_sec": limits.scenario_timeout_sec,
            "evaluation_mode": "GENERIC",
            "domain": scenario.domain
        }

        # Setup Run record
        run_record = self.db.query(Run).filter(Run.id == run_id).first()
        if not run_record:
            run_record = Run(
                id=run_id,
                agent_version_id=agent_version_id,
                provider_type=self.provider_type,
                model_name=self.model_name,
                is_mock=1 if self.provider_type == "mock" else 0,
                execution_config=exec_config,
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

        trace_logger = TraceLogger(self.db, scenario_run_id)

        # Prepare tool specifications
        tools_spec: List[Dict[str, Any]] = []
        raw_tool_contracts: List[Dict[str, Any]] = [tc.model_dump() for tc in scenario.tool_contracts]
        for tc in scenario.tool_contracts:
            tools_spec.append({
                "type": "function",
                "function": {
                    "name": tc.name,
                    "description": tc.description,
                    "parameters": tc.parameters
                }
            })

        # Multi-turn conversation messages
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": agent_ver.system_prompt}
        ]
        user_prompt = scenario.customer_messages[0] if scenario.customer_messages else json.dumps(scenario.input)
        messages.append({"role": "user", "content": user_prompt})

        # Execution metrics
        start_time = time.time()
        turns = 0
        total_tool_calls = 0
        total_tokens = 0
        total_cost_microcents = 0
        final_answer = None
        execution_error = None

        # Turn execution loop
        while turns < limits.max_turns:
            elapsed = time.time() - start_time
            if elapsed > limits.scenario_timeout_sec:
                execution_error = f"Scenario timeout exceeded ({elapsed:.2f}s > {limits.scenario_timeout_sec}s)."
                break

            turns += 1
            t0 = time.time()

            try:
                if isinstance(self.provider, GenericMockAgent):
                    resp: LLMResponse = self.provider.generate(
                        messages=messages,
                        tools=tools_spec,
                        domain=scenario.domain,
                        input_data=scenario.input,
                        turn_num=turns
                    )
                else:
                    resp = self.provider.generate(
                        messages=messages,
                        tools=tools_spec,
                        timeout=min(15.0, max(1.0, limits.scenario_timeout_sec - elapsed))
                    )
            except Exception as e:
                execution_error = f"Agent Provider Error: {sanitize_secret(str(e))}"
                break

            duration_call_ms = int((time.time() - t0) * 1000)
            p_tok = resp.prompt_tokens or 0
            c_tok = resp.completion_tokens or 0
            call_tok = p_tok + c_tok
            total_tokens += call_tok
            cost_call = calculate_cost_microcents(self.provider_type, self.model_name, p_tok, c_tok)
            total_cost_microcents += cost_call

            trace_logger.log_event(
                event_type="LLM_CALL",
                duration_ms=duration_call_ms,
                token_usage={"prompt_tokens": p_tok, "completion_tokens": c_tok, "total": call_tok},
                cost_estimate=cost_call
            )

            if total_tokens > limits.max_tokens_budget:
                execution_error = f"Token budget exceeded ({total_tokens} > {limits.max_tokens_budget})."
                break

            # Handle Tool Calls
            if resp.tool_calls:
                msg_tool_calls = []
                for tc in resp.tool_calls:
                    total_tool_calls += 1
                    if total_tool_calls > limits.max_tool_calls:
                        execution_error = f"Tool call limit exceeded ({total_tool_calls} > {limits.max_tool_calls})."
                        break

                    tc_fn = tc.get("function", {})
                    fn_name = tc_fn.get("name", "unknown")
                    raw_args = tc_fn.get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            fn_args = json.loads(raw_args)
                        except Exception:
                            fn_args = {"raw": raw_args}
                    else:
                        fn_args = raw_args or {}

                    t_tool_start = time.time()
                    tool_result = execute_safe_synthetic_tool(
                        tool_name=fn_name,
                        arguments=fn_args,
                        tool_contracts=raw_tool_contracts
                    )
                    t_tool_ms = int((time.time() - t_tool_start) * 1000)

                    event_type = "TOOL_EXECUTION"
                    if "error" in tool_result and tool_result.get("code") == "TOOL_NOT_PERMITTED":
                        event_type = "UNAUTHORIZED_TOOL_CALL"

                    trace_logger.log_event(
                        event_type=event_type,
                        tool_name=fn_name,
                        tool_arguments=fn_args,
                        tool_result=tool_result,
                        duration_ms=t_tool_ms
                    )

                    msg_tool_calls.append(tc)
                    # Append tool response message to history
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call_{uuid.uuid4().hex[:6]}"),
                        "name": fn_name,
                        "content": json.dumps(tool_result)
                    })

                if execution_error:
                    break

            # Handle Assistant Output
            if resp.content:
                final_answer = resp.content
                trace_logger.log_event(
                    event_type="AGENT_RESPONSE",
                    tool_result={"content": final_answer},
                    duration_ms=0
                )
                # If there were no tool calls, the agent completed its response
                if not resp.tool_calls:
                    break

        total_duration_ms = int((time.time() - start_time) * 1000)
        # ---------- NEW: Max‑turn exhaustion detection ----------
        if turns == limits.max_turns and not final_answer:
            execution_error = (execution_error or "Maximum turn limit reached without a final JSON answer")
        # ---------------------------------------------------------

        # Check for provider failure
        is_provider_error = bool(
            execution_error and turns == 0 and any(
                term in execution_error for term in ["404", "401", "403", "Provider", "API key", "NOT_FOUND", "Authentication", "Connection"]
            )
        )

        if is_provider_error:
            scenario_run.status = "PROVIDER_ERROR"
            scenario_run.finished_at = utc_now()
            scenario_run.duration_ms = total_duration_ms

            if not queue_owned:
                run_record.status = "PROVIDER_ERROR"
                run_record.finished_at = utc_now()
                run_record.passed_scenarios = 0
                run_record.failed_scenarios = 0

            check_results: List[CheckResult] = []
            for a in scenario.assertions:
                chk_name = a.name or a.id or a.type
                cr = CheckResult(
                    id=f"chk_{scenario_run_id}_{a.id or chk_name}"[:64],
                    scenario_run_id=scenario_run_id,
                    check_name=chk_name[:64],
                    status="NOT_EVALUATED",
                    message=f"Provider setup failure: {execution_error}.",
                    evidence={"provider_error": execution_error}
                )
                self.db.add(cr)
                check_results.append(cr)
        else:
            # Declarative Generic Evaluation
            evaluator = GenericAssertionEvaluator(self.db, scenario_run_id)
            check_results = evaluator.evaluate_all(
                assertions=scenario.assertions,
                final_answer=final_answer,
                execution_error=execution_error
            )

            all_passed = all(c.status == "PASSED" for c in check_results)
            scenario_run.status = "PASSED" if all_passed else "FAILED"
            scenario_run.finished_at = utc_now()
            scenario_run.duration_ms = total_duration_ms

            if not queue_owned and (run_record.total_scenarios or 1) <= 1:
                run_record.status = "COMPLETED"
                run_record.finished_at = utc_now()
                if all_passed:
                    run_record.passed_scenarios = 1
                    run_record.failed_scenarios = 0
                else:
                    run_record.passed_scenarios = 0
                    run_record.failed_scenarios = 1

        self.db.commit()

        failure_category = None
        if scenario_run.status == "PROVIDER_ERROR":
            failure_category = "PROVIDER_ERROR"
        elif execution_error and ("timeout" in execution_error.lower() or "limit" in execution_error.lower()):
            failure_category = "OPERATIONAL_LIMIT_EXCEEDED"
        elif scenario_run.status == "FAILED":
            failure_category = "BEHAVIORAL_POLICY_VIOLATION"

        return {
            "failure_category": failure_category,
            "cost_microcents": total_cost_microcents if not is_provider_error else 0,
            "cost_usd": round(total_cost_microcents / 100_000_000.0, 6) if not is_provider_error else 0.0,
            "cost_disclaimer": COST_DISCLAIMER,
            "run_id": run_id,
            "scenario_run_id": scenario_run_id,
            "scenario_version_id": scenario_version_id,
            "agent_version": agent_version_id,
            "provider_type": self.provider_type,
            "model_name": self.model_name,
            "is_mock": self.provider_type == "mock",
            "execution_config": exec_config,
            "execution_error": execution_error,
            "status": scenario_run.status,
            "final_answer": final_answer,
            "turns": turns,
            "tool_calls": total_tool_calls,
            "tokens": total_tokens if not is_provider_error else None,
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
