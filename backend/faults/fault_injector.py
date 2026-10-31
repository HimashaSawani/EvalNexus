import time
import random
import datetime
from typing import Dict, Any, Optional, List


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
    AgentWindTunnel V3 Chaos Engineering & Fault Injection Engine.
    Deterministically intercepts agent and tool interactions based on:
    - Tool name or agent step
    - Call counter
    - Seeded pseudo-randomness for reproducibility
    - 12 industrial chaos fault modes:
        1. TIMEOUT_BEFORE_WRITE: Aborts before mutation
        2. TIMEOUT_AFTER_WRITE: Record is committed, but response withheld
        3. TEMPORARY_UNAVAILABLE (503): Transient outage
        4. STALE_READ: Outdated/cached state
        5. MALFORMED_RESPONSE: Missing required keys or corrupted payload
        6. HTTP_429_RATE_LIMIT: Downstream rate limit with retry-after
        7. HTTP_500_INTERNAL_ERROR: Unexpected crash in backend
        8. PARTIAL_PAYLOAD: Abruptly truncated response
        9. SCHEMA_MUTATION: Mutated field names or type corruptions
        10. DROPOUT: Connection reset by peer / network severed
        11. CLOCK_SKEW: Out of sync / future or past timestamp
        12. TOKEN_FLOOD: Excessive synthetic tokens stressing context window
        13. LATENCY: Artificial delay injection
    """

    def __init__(self, fault_configs: Optional[Dict[str, Any]] = None, seed: Optional[int] = None):
        self.fault_configs = fault_configs or {}
        self.call_counters: Dict[str, int] = {}
        self.triggered_faults: List[Dict[str, Any]] = []
        self.seed = seed
        self.prng = random.Random(seed) if seed is not None else random.Random(42)

    def before_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Called immediately before executing a tool.
        Returns:
            - None: Proceed normally
            - Dict: Mocked immediate return
        Raises:
            - FaultInjectionError for failure modes
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
        t_stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Latency injection
        delay_ms = config.get("delay_ms", 0)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        if fault_type == "TIMEOUT_BEFORE_WRITE":
            self.triggered_faults.append({
                "timestamp": t_stamp,
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
                "timestamp": t_stamp,
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

        if fault_type == "HTTP_429_RATE_LIMIT":
            retry_after = config.get("retry_after_sec", 2)
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type,
                "retry_after_sec": retry_after
            })
            raise FaultInjectionError(
                fault_type="HTTP_429_RATE_LIMIT",
                agent_visible_message=f"Too Many Requests: Rate limit exceeded for {tool_name}. Retry-After: {retry_after}s.",
                internal_evidence={"retry_after_sec": retry_after, "call_num": current_call, "tool_name": tool_name},
                status_code=429
            )

        if fault_type == "HTTP_500_INTERNAL_ERROR":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            raise FaultInjectionError(
                fault_type="HTTP_500_INTERNAL_ERROR",
                agent_visible_message=f"Internal Server Error: Unexpected failure occurred in {tool_name} microservice.",
                internal_evidence={"call_num": current_call, "tool_name": tool_name},
                status_code=500
            )

        if fault_type == "DROPOUT":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            raise FaultInjectionError(
                fault_type="DROPOUT",
                agent_visible_message=f"Connection reset by peer (ECONNRESET) during transmission to {tool_name}.",
                internal_evidence={"call_num": current_call, "tool_name": tool_name},
                status_code=502
            )

        if fault_type == "STALE_READ":
            self.triggered_faults.append({
                "timestamp": t_stamp,
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

        if fault_type == "CLOCK_SKEW":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            # Return payload timestamped 10 years in the past
            return {
                "order_id": arguments.get("order_id"),
                "status": "DELIVERED",
                "total_amount_cents": 5000,
                "currency": "USD",
                "delivery_date": "2014-01-01T00:00:00Z",
                "warning": "System clock anomaly: upstream source drift detected."
            }

        return None

    def after_tool_call(self, tool_name: str, raw_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called immediately after tool execution commits.
        Can withhold response or mutate/corrupt output payload.
        """
        current_call = self.call_counters.get(tool_name, 1)
        config = self.fault_configs.get(tool_name)
        if not config:
            return raw_result

        target_call = config.get("trigger_on_call", 1)
        if current_call != target_call:
            return raw_result

        fault_type = config.get("fault_type")
        t_stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if fault_type == "TIMEOUT_AFTER_WRITE":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type,
                "write_committed": True
            })
            raise FaultInjectionError(
                fault_type="TIMEOUT_AFTER_WRITE",
                agent_visible_message="Gateway Timeout: Connection to upstream payment processor lost while awaiting confirmation.",
                internal_evidence={"write_committed": True, "call_num": current_call, "tool_name": tool_name},
                status_code=504
            )

        if fault_type == "MALFORMED_RESPONSE":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            return {
                "raw_response": "0xDEADBEEF",
                "warning": "Malformed upstream packet: required fields missing"
            }

        if fault_type == "PARTIAL_PAYLOAD":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            # Return only the first key or truncated fragment
            keys = list(raw_result.keys())
            truncated = {keys[0]: raw_result[keys[0]]} if keys else {"partial": True}
            return truncated

        if fault_type == "SCHEMA_MUTATION":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            mutated = {}
            for k, v in raw_result.items():
                if isinstance(v, (int, float)):
                    mutated[f"mutated_{k}"] = f"CORRUPT_{v}"
                elif isinstance(v, str):
                    mutated[k.upper()] = v
                else:
                    mutated[k] = None
            return mutated

        if fault_type == "TOKEN_FLOOD":
            self.triggered_faults.append({
                "timestamp": t_stamp,
                "tool_name": tool_name,
                "call_num": current_call,
                "fault_type": fault_type
            })
            flood_text = "OVERFLOW_DATA " * 500
            return {
                "order_id": raw_result.get("order_id"),
                "status": raw_result.get("status"),
                "debug_dump": flood_text
            }

        return raw_result

    def calculate_resilience_metrics(
        self,
        final_status: str,
        execution_duration_ms: int
    ) -> Dict[str, Any]:
        """
        Calculates standardized resilience score and recovery rate.
        """
        total_faults = len(self.triggered_faults)
        if total_faults == 0:
            return {
                "total_faults_injected": 0,
                "recovery_rate": 1.0,
                "resilience_score": 100,
                "verdict": "NO_FAULTS_INJECTED"
            }

        # If overall test/workflow status passed despite faults, agent demonstrated resilience
        recovered = (final_status == "PASSED")
        recovery_rate = 1.0 if recovered else 0.0

        # Resilience score combines recovery success with time/resource penalty
        penalty = min(20, int(execution_duration_ms / 1000))
        base_score = 100 if recovered else 20
        resilience_score = max(0, base_score - penalty)

        return {
            "total_faults_injected": total_faults,
            "recovered": recovered,
            "recovery_rate": recovery_rate,
            "resilience_score": resilience_score,
            "triggered_faults": self.triggered_faults,
            "verdict": "RESILIENT" if recovered else "FAILED_RECOVERY"
        }
