import time
import json
import concurrent.futures
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


class CancellationToken:
    """Thread-safe cancellation token to prevent late writes from timed-out executions."""
    def __init__(self):
        self.is_cancelled = False
        self.timed_out = False

    def cancel(self):
        self.is_cancelled = True
        self.timed_out = True


class AgentLoop:
    """
    Step 8: Interactive Agent Loop
    Manages multi-turn conversation between LLM and tools with strict operational budgets and fault injection:
    - Wall-clock scenario timeout limit (scenario_timeout_sec)
    - Active tool execution timeout limit (tool_timeout_sec) via ThreadPool interrupt
    - Turn limits (max_turns)
    - Tool call limits (max_tool_calls)
    - Token budget limits (max_tokens_budget)
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
        tool_timeout_sec: float = 5.0,
        scenario_timeout_sec: float = 30.0,
        provider_timeout_sec: float = 15.0
    ):
        self.service = service
        self.trace_logger = trace_logger
        self.provider = provider
        self.fault_injector = fault_injector or FaultInjector()
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_tokens_budget = max_tokens_budget
        self.tool_timeout_sec = tool_timeout_sec
        self.scenario_timeout_sec = scenario_timeout_sec
        self.provider_timeout_sec = getattr(provider, "provider_timeout_sec", provider_timeout_sec)
        self.unresolved_tasks: List[Dict[str, Any]] = []
        self.pending_timeout_events: List[Dict[str, Any]] = []
        self.active_executors: List[concurrent.futures.ThreadPoolExecutor] = []
        self.active_futures: List[concurrent.futures.Future] = []

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

            # Check scenario wall-clock timeout limit before model call
            elapsed = time.time() - start_time
            remaining = self.scenario_timeout_sec - elapsed
            if remaining <= 0:
                raise AgentExecutionLimitError(
                    limit_type="SCENARIO_TIMEOUT",
                    message=f"Scenario exceeded execution time limit of {self.scenario_timeout_sec}s (elapsed: {elapsed:.2f}s)."
                )

            # Check token budget before call
            if total_tokens >= self.max_tokens_budget:
                raise AgentExecutionLimitError(
                    limit_type="TOKEN_BUDGET_EXCEEDED",
                    message=f"Token budget of {self.max_tokens_budget} exceeded (used: {total_tokens})."
                )

            # Model Call: dynamically bounded by remaining scenario deadline
            effective_provider_timeout = max(0.05, min(self.provider_timeout_sec, remaining))
            t_model_start = time.time()
            try:
                try:
                    llm_res = self.provider.generate(messages=messages, tools=TOOLS_SPEC, timeout=effective_provider_timeout)
                except TypeError:
                    llm_res = self.provider.generate(messages=messages, tools=TOOLS_SPEC)
            except TimeoutError as te:
                if (time.time() - start_time) >= self.scenario_timeout_sec:
                    raise AgentExecutionLimitError(
                        limit_type="SCENARIO_TIMEOUT",
                        message=f"Scenario exceeded execution time limit of {self.scenario_timeout_sec}s during model call: {str(te)}"
                    )
                raise te

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

            # A final response must not bypass the scenario deadline after a slow provider or trace commit.
            if time.time() - start_time >= self.scenario_timeout_sec:
                raise AgentExecutionLimitError(
                    limit_type="SCENARIO_TIMEOUT",
                    message=f"Scenario exceeded execution time limit of {self.scenario_timeout_sec}s after model response."
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

                # Dynamically calculate remaining time before tool execution
                elapsed_now = time.time() - start_time
                remaining_tool = self.scenario_timeout_sec - elapsed_now
                if remaining_tool <= 0:
                    raise AgentExecutionLimitError(
                        limit_type="SCENARIO_TIMEOUT",
                        message=f"Scenario exceeded execution time limit of {self.scenario_timeout_sec}s before tool '{fn_name}' execution."
                    )
                effective_tool_timeout = max(0.05, min(self.tool_timeout_sec, remaining_tool))

                # Tool Execution with Fault Injection and dynamic timeout interruption
                tool_output, agent_error = self._execute_tool_with_timeout(
                    customer_id=customer_id,
                    tool_name=fn_name,
                    arguments=fn_args,
                    timeout_sec=effective_tool_timeout
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
            "duration_ms": int((time.time() - start_time) * 1000),
            "unresolved_tasks": [
                {
                    "tool_name": ut["tool_name"],
                    "is_write": ut["is_write"],
                    "status": "SETTLED_LATE" if ut["future"].done() else "STILL_UNRESOLVED"
                }
                for ut in self.unresolved_tasks
            ]
        }

    def _execute_tool_with_timeout(
        self,
        customer_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout_sec: Optional[float] = None
    ) -> (Optional[Dict[str, Any]], Optional[str]):
        """
        Executes tool within active timeout window using ThreadPoolExecutor.
        Interrupts waiting if tool exceeds active timeout and records unresolved tasks
        to defend against indeterminate states.
        """
        active_timeout = timeout_sec if timeout_sec is not None else self.tool_timeout_sec
        tool_deadline = time.monotonic() + active_timeout
        token = CancellationToken()
        if hasattr(self.service, "cancel_token"):
            self.service.cancel_token = token

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._execute_tool_in_session, customer_id, tool_name, arguments, token)
        self.active_executors.append(executor)
        self.active_futures.append(future)

        try:
            result = future.result(timeout=max(0.0, tool_deadline - time.monotonic()))
            if hasattr(self.trace_logger, "flush_pending"):
                self.trace_logger.flush_pending()
            return result
        except concurrent.futures.TimeoutError:
            token.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            duration = int(active_timeout * 1000)
            timeout_msg = f"Gateway Timeout: Tool '{tool_name}' timed out after {active_timeout:g}s."
            self.pending_timeout_events.append(dict(
                event_type="TOOL_TIMEOUT",
                tool_name=tool_name,
                tool_arguments=arguments,
                error_message=f"Active tool timeout interrupted after {active_timeout:.2f}s (recorded for indeterminate state tracking)",
                duration_ms=duration
            ))
            # Track unresolved task
            is_write = (tool_name == "request_refund")
            self.unresolved_tasks.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "is_write": is_write,
                "timeout_sec": active_timeout,
                "timed_out_at": time.time(),
                "future": future
            })
            return None, timeout_msg
        finally:
            pass

    def settle_in_flight_tasks(self, timeout_sec: float = 0.5):
        """
        Drains and settles any timed-out or in-flight background worker threads.
        Attempts to wait up to timeout_sec for thread settlement.
        Any tasks still running are tracked as unresolved.
        """
        # Persist timeout evidence outside the deadline-sensitive return path.
        for event in self.pending_timeout_events:
            self.trace_logger.log_event(**event)
        self.pending_timeout_events.clear()
        for fut in self.active_futures:
            if not fut.done():
                if hasattr(self.service, "cancel_token") and self.service.cancel_token:
                    self.service.cancel_token.cancel()
                try:
                    fut.result(timeout=timeout_sec)
                except Exception:
                    pass
        for exc in self.active_executors:
            try:
                exc.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

        if hasattr(self.trace_logger, "flush_pending"):
            self.trace_logger.flush_pending()

    def _execute_tool_in_session(self, customer_id, tool_name, arguments, token):
        # A timed-out future must never share the runner's SQLAlchemy Session.
        if type(self.service) is RefundService:
            isolated_db = Session(bind=self.service.db.get_bind())
            isolated_service = RefundService(isolated_db, self.service.scenario_run_id,
                                             self.service.fixed_clock, cancel_token=token)
            try:
                return self._execute_tool_internal(customer_id, tool_name, arguments, service=isolated_service)
            finally:
                isolated_db.close()
        return self._execute_tool_internal(customer_id, tool_name, arguments)

    def _execute_tool_internal(
        self,
        customer_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        service=None
    ) -> (Optional[Dict[str, Any]], Optional[str]):
        """
        Executes domain tool with FaultInjector hooks.
        CRITICAL: Never leaks internal fault names or 'write committed' status into agent observation!
        """
        service = service or self.service
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
                raw_res = service.get_order(
                    session_customer_id=customer_id,
                    order_id=arguments["order_id"]
                )
            elif tool_name == "check_refund_eligibility":
                raw_res = service.check_refund_eligibility(
                    session_customer_id=customer_id,
                    order_id=arguments["order_id"]
                )
            elif tool_name == "request_refund":
                raw_res = service.request_refund(
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
