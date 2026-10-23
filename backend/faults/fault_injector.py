from typing import Dict, Any, Optional


class FaultInjectionError(Exception):
    def __init__(
        self,
        fault_type: str,
        agent_visible_message: str,
        internal_evidence: Optional[Dict[str, Any]] = None,
        status_code: int = 500
    ):
        super().__init__(agent_visible_message)
        self.fault_type = fault_type
        self.agent_visible_message = agent_visible_message
        self.internal_evidence = internal_evidence or {}
        self.status_code = status_code


class FaultInjector:
    """
    Step 10: Fault Injector
    Deterministically intercepts tool execution based on:
    - Tool name
    - Call number for that tool
    - Configured fault type:
        1. TIMEOUT_BEFORE_WRITE: Aborts before mutation
        2. TIMEOUT_AFTER_WRITE: Record is committed, but response is withheld / times out
        3. TEMPORARY_UNAVAILABLE: First call fails (503); subsequent call succeeds
        4. STALE_READ: Returns outdated / cached state
        5. MALFORMED_RESPONSE: Missing required keys or corrupted payload

    CRITICAL SECURITY & FIDELITY:
    Agent-visible errors NEVER reveal internal state (e.g., whether write committed or fault names).
    Internal ground truth is reserved exclusively for audit traces and deterministic evaluators.
    """

    def __init__(self, fault_configs: Optional[Dict[str, Any]] = None):
        self.fault_configs = fault_configs or {}
        self.call_counters: Dict[str, int] = {}
        self.triggered_faults = []

    def before_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Called immediately before executing a tool.
        Returns:
            - None: Proceed normally
            - Dict: Mocked immediate return (e.g., STALE_READ)
        Raises:
            - FaultInjectionError: for TIMEOUT_BEFORE_WRITE, TEMPORARY_UNAVAILABLE
        """
        self.call_counters[tool_name] = self.call_counters.get(tool_name, 0) + 1
        current_call = self.call_counters[tool_name]

        config = self.fault_configs.get(tool_name)
        if not config:
            return None

        target_call = config.get("trigger_on_call", 1)
        if current_call != target_call:
            return None

        fault_type = config.get("fault_type")

        if fault_type == "TIMEOUT_BEFORE_WRITE":
            self.triggered_faults.append({
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type,
                "write_committed": False
            })
            raise FaultInjectionError(
                fault_type="TIMEOUT_BEFORE_WRITE",
                agent_visible_message=f"Gateway Timeout: Request to {tool_name} timed out before upstream connection was established.",
                internal_evidence={"write_committed": False, "call_num": current_call, "tool_name": tool_name},
                status_code=504
            )

        if fault_type == "TEMPORARY_UNAVAILABLE":
            self.triggered_faults.append({
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            raise FaultInjectionError(
                fault_type="TEMPORARY_UNAVAILABLE",
                agent_visible_message=f"Service Unavailable: {tool_name} service is temporarily unavailable (HTTP 503). Please retry.",
                internal_evidence={"transient": True, "call_num": current_call, "tool_name": tool_name},
                status_code=503
            )

        if fault_type == "STALE_READ":
            self.triggered_faults.append({
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            stale_payload = config.get("stale_payload", {
                "order_id": arguments.get("order_id"),
                "status": "PROCESSING",
                "total_amount_cents": 5000,
                "currency": "USD",
                "delivery_date": None
            })
            return stale_payload

        return None

    def after_tool_call(self, tool_name: str, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called immediately after tool execution commits.
        Can withhold response (TIMEOUT_AFTER_WRITE) or corrupt response (MALFORMED_RESPONSE).
        """
        current_call = self.call_counters.get(tool_name, 1)
        config = self.fault_configs.get(tool_name)
        if not config:
            return raw_result

        target_call = config.get("trigger_on_call", 1)
        if current_call != target_call:
            return raw_result

        fault_type = config.get("fault_type")

        if fault_type == "TIMEOUT_AFTER_WRITE":
            self.triggered_faults.append({
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type,
                "write_committed": True
            })
            # Realistic simulation: DB write committed, but agent receives uncertain gateway timeout
            raise FaultInjectionError(
                fault_type="TIMEOUT_AFTER_WRITE",
                agent_visible_message=f"Gateway Timeout: Connection to upstream payment processor lost while awaiting confirmation.",
                internal_evidence={"write_committed": True, "call_num": current_call, "tool_name": tool_name},
                status_code=504
            )

        if fault_type == "MALFORMED_RESPONSE":
            self.triggered_faults.append({
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            # Corrupt payload by omitting expected status / keys
            return {
                "raw_response": "0xDEADBEEF",
                "warning": "Malformed upstream packet: required fields missing"
            }

        return raw_result
