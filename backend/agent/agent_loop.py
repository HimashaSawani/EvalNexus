import time
import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.domain.refund_service import RefundService, RefundDomainError
from backend.runner.trace_logger import TraceLogger
from backend.faults.fault_injector import FaultInjector, FaultInjectionError
from backend.agent.tools_schema import TOOLS_SPEC, validate_tool_arguments
from backend.agent.provider import BaseLLMProvider


class AgentExecutionLimitError(Exception):
    def __init__(self, limit_type: str, message: str):
        super().__init__(message)
        self.limit_type = limit_type
        self.message = message


class AgentLoop:
    """
    Step 8: Interactive Agent Loop
    Manages multi-turn conversation between LLM and tools with strict operational budgets and fault injection.
    """

    def __init__(
        self,
        service: RefundService,
        trace_logger: TraceLogger,
        provider: BaseLLMProvider,
        fault_injector: Optional[FaultInjector] = None,
        max_turns: int = 6,
        max_tool_calls: int = 10,
        max_tokens_budget: int = 15000,
        scenario_timeout_sec: float = 30.0
    ):
        self.service = service
        self.trace_logger = trace_logger
        self.provider = provider
        self.fault_injector = fault_injector or FaultInjector()
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_tokens_budget = max_tokens_budget
        self.scenario_timeout_sec = scenario_timeout_sec

    def execute_turn_loop(
        self,
        customer_id: str,
        customer_message: str,
        system_prompt: str
    ) -> Dict[str, Any]:
        start_time = time.time()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": customer_message}
        ]

        # Log User Message to trace
        self.trace_logger.log_event(
            event_type="USER_MESSAGE",
            tool_name=None,
            tool_arguments={"customer_id": customer_id, "content": customer_message}
        )

        turns = 0
        total_tool_calls = 0
        total_tokens = 0
        final_answer = None

        while turns < self.max_turns:
            turns += 1

            # Check scenario timeout limit
            if (time.time() - start_time) > self.scenario_timeout_sec:
                raise AgentExecutionLimitError(
                    limit_type="SCENARIO_TIMEOUT",
                    message=f"Scenario exceeded execution time limit of {self.scenario_timeout_sec}s."
                )

            # Check token budget before call
            if total_tokens >= self.max_tokens_budget:
                raise AgentExecutionLimitError(
                    limit_type="TOKEN_BUDGET_EXCEEDED",
                    message=f"Token budget of {self.max_tokens_budget} exceeded (used: {total_tokens})."
                )

            # Model Call
            t_model_start = time.time()
            llm_res = self.provider.generate(messages=messages, tools=TOOLS_SPEC)
            d_model = int((time.time() - t_model_start) * 1000)

            total_tokens += llm_res.total_tokens

            # Trace log model call
            self.trace_logger.log_event(
                event_type="MODEL_CALL",
                tool_name=None,
                tool_result={"content": llm_res.content, "has_tool_calls": len(llm_res.tool_calls) > 0},
                duration_ms=d_model,
                token_usage={
                    "prompt_tokens": llm_res.prompt_tokens,
                    "completion_tokens": llm_res.completion_tokens,
                    "total_tokens": llm_res.total_tokens
                }
            )

            # If model produced a final text response without tool calls, loop terminates
            if not llm_res.tool_calls:
                final_answer = llm_res.content
                messages.append({"role": "assistant", "content": final_answer})
                self.trace_logger.log_event(
                    event_type="FINAL_ANSWER",
                    tool_name=None,
                    tool_result={"final_answer": final_answer}
                )
                break

            # Append assistant message with tool calls to prompt history
            messages.append({
                "role": "assistant",
                "content": llm_res.content,
                "tool_calls": llm_res.tool_calls
            })

            # Process each requested tool call
            for tc in llm_res.tool_calls:
                total_tool_calls += 1
                if total_tool_calls > self.max_tool_calls:
                    raise AgentExecutionLimitError(
                        limit_type="MAX_TOOL_CALLS_EXCEEDED",
                        message=f"Agent exceeded maximum tool call limit of {self.max_tool_calls} calls."
                    )

                fn_info = tc["function"]
                fn_name = fn_info["name"]
                raw_args = fn_info["arguments"]
                fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

                # Validate tool schema before execution
                validate_tool_arguments(fn_name, fn_args)

                # Tool Execution with Fault Injection
                # Returns agent_visible_payload (for LLM) and updates audit trace
                tool_output, agent_error = self._execute_tool_with_faults(
                    customer_id=customer_id,
                    tool_name=fn_name,
                    arguments=fn_args
                )

                tool_response_payload = tool_output if tool_output is not None else {"error": agent_error}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": json.dumps(tool_response_payload)
                })

        return {
            "final_answer": final_answer,
            "turns": turns,
            "total_tool_calls": total_tool_calls,
            "total_tokens": total_tokens,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    def _execute_tool_with_faults(
        self,
        customer_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> (Optional[Dict[str, Any]], Optional[str]):
        """
        Executes tool with FaultInjector hooks.
        CRITICAL: Never leaks internal fault names or 'write committed' status into agent observation!
        """
        t0 = time.time()
        tool_output = None
        agent_visible_error = None

        try:
            # 1. Fault Injector Check: Before tool execution
            early_result = self.fault_injector.before_tool_call(tool_name, arguments)
            if early_result is not None:
                # E.g. Stale read injected
                duration = int((time.time() - t0) * 1000)
                self.trace_logger.log_event(
                    event_type="FAULT_INJECTED",
                    tool_name=tool_name,
                    tool_arguments=arguments,
                    tool_result=early_result,
                    duration_ms=duration
                )
                return early_result, None

            # 2. Tool Execution (Shop Backend)
            if tool_name == "get_order":
                raw_res = self.service.get_order(
                    session_customer_id=customer_id,
                    order_id=arguments["order_id"]
                )
            elif tool_name == "check_refund_eligibility":
                raw_res = self.service.check_refund_eligibility(
                    session_customer_id=customer_id,
                    order_id=arguments["order_id"]
                )
            elif tool_name == "request_refund":
                raw_res = self.service.request_refund(
                    session_customer_id=customer_id,
                    order_id=arguments["order_id"],
                    amount_cents=arguments["amount_cents"],
                    operation_key=arguments["operation_key"],
                    reason=arguments.get("reason", "Customer request")
                )
            else:
                raise ValueError(f"Unauthorized tool: {tool_name}")

            # 3. Fault Injector Check: After write / execution (e.g. TIMEOUT_AFTER_WRITE)
            final_res = self.fault_injector.after_tool_call(tool_name, raw_res)
            tool_output = final_res

            duration = int((time.time() - t0) * 1000)
            self.trace_logger.log_event(
                event_type="TOOL_CALL",
                tool_name=tool_name,
                tool_arguments=arguments,
                tool_result=tool_output,
                duration_ms=duration
            )

        except FaultInjectionError as fie:
            # Internal ground-truth logged to admin trace only
            internal_evidence_str = json.dumps(fie.internal_evidence)
            duration = int((time.time() - t0) * 1000)
            self.trace_logger.log_event(
                event_type="FAULT_INJECTED",
                tool_name=tool_name,
                tool_arguments=arguments,
                error_message=f"FaultInjection [{fie.fault_type}]: {internal_evidence_str}",
                duration_ms=duration
            )
            # Agent sees only generic realistic gateway error
            agent_visible_error = fie.agent_visible_message

        except RefundDomainError as rde:
            duration = int((time.time() - t0) * 1000)
            self.trace_logger.log_event(
                event_type="TOOL_CALL",
                tool_name=tool_name,
                tool_arguments=arguments,
                error_message=f"RefundDomainError [{rde.code}]: {rde.message}",
                duration_ms=duration
            )
            agent_visible_error = f"Error [{rde.code}]: {rde.message}"

        except Exception as e:
            duration = int((time.time() - t0) * 1000)
            self.trace_logger.log_event(
                event_type="ERROR",
                tool_name=tool_name,
                tool_arguments=arguments,
                error_message=f"Execution Error: {str(e)}",
                duration_ms=duration
            )
            agent_visible_error = f"Internal processing error: {str(e)}"

        return tool_output, agent_visible_error
