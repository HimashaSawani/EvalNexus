import os
import json
from typing import List, Dict, Any, Optional

from backend.agent.tools_schema import TOOLS_SPEC


class LLMResponse:
    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        prompt_tokens: int = 150,
        completion_tokens: int = 40
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class BaseLLMProvider:
    provider_type: str = "base"
    model_name: str = "base"

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0
    ) -> LLMResponse:
        raise NotImplementedError


class MockToolCallingProvider(BaseLLMProvider):
    """
    Deterministic Infrastructure Simulator:
    For local, offline, reproducible testing of the WindTunnel harness.
    DOES NOT branch on agent_version, scenario_id, hidden faults, or expected checks.
    Uses ONLY visible conversation history and tool outputs to generate next actions.
    """
    provider_type: str = "mock"
    model_name: str = "mock-deterministic-v1"

    def __init__(self, model_name: str = "mock-deterministic-v1"):
        self.model_name = model_name

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0
    ) -> LLMResponse:
        # Extract target order ID from conversation history
        target_order_id = "ord_deliv_8891"
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and "ord_" in content:
                for word in content.replace(".", " ").replace(",", " ").replace(";", " ").split():
                    if word.startswith("ord_"):
                        target_order_id = word
                        break

        # Check tool results and errors in visible conversation history
        tool_results: Dict[str, Any] = {}
        tool_errors: Dict[str, str] = {}

        for m in messages:
            if m.get("role") == "tool":
                tool_name = m.get("name")
                try:
                    payload = json.loads(m.get("content", "{}"))
                    if "error" in payload:
                        tool_errors[tool_name] = payload["error"]
                    else:
                        tool_results[tool_name] = payload
                except Exception:
                    tool_results[tool_name] = m.get("content")

        # Step 1: Call get_order if not yet queried
        if "get_order" not in tool_results and "get_order" not in tool_errors:
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": f"call_get_order_{target_order_id}",
                    "type": "function",
                    "function": {
                        "name": "get_order",
                        "arguments": json.dumps({"order_id": target_order_id})
                    }
                }],
                prompt_tokens=220,
                completion_tokens=25
            )

        # Step 2: If get_order returned an error (e.g. 403 Forbidden unauthorized access)
        if "get_order" in tool_errors:
            err = tool_errors["get_order"]
            return LLMResponse(
                content=f"I was unable to retrieve details for order {target_order_id}. Response: {err}",
                tool_calls=[],
                prompt_tokens=280,
                completion_tokens=30
            )

        # Step 3: Call check_refund_eligibility
        if "check_refund_eligibility" not in tool_results and "check_refund_eligibility" not in tool_errors:
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": f"call_check_eligibility_{target_order_id}",
                    "type": "function",
                    "function": {
                        "name": "check_refund_eligibility",
                        "arguments": json.dumps({"order_id": target_order_id})
                    }
                }],
                prompt_tokens=320,
                completion_tokens=25
            )

        # Step 4: Handle eligibility result or error
        if "check_refund_eligibility" in tool_errors:
            err = tool_errors["check_refund_eligibility"]
            return LLMResponse(
                content=f"I encountered an error checking eligibility for order {target_order_id}: {err}",
                tool_calls=[],
                prompt_tokens=360,
                completion_tokens=30
            )

        eligibility = tool_results.get("check_refund_eligibility", {})

        # If ineligible according to visible tool result
        if not eligibility.get("eligible", False):
            reason = eligibility.get("message", "Order is ineligible for refund under store policy.")
            return LLMResponse(
                content=f"I checked your order {target_order_id}, but it is not eligible for a refund. Reason: {reason}",
                tool_calls=[],
                prompt_tokens=390,
                completion_tokens=40
            )

        # Step 5: Eligible — Call request_refund with a STABLE operation key for idempotency
        stable_op_key = f"op_stable_{target_order_id}"
        if "request_refund" not in tool_results and "request_refund" not in tool_errors:
            amt = eligibility.get("max_refundable_cents", 0)
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": f"call_request_refund_{target_order_id}",
                    "type": "function",
                    "function": {
                        "name": "request_refund",
                        "arguments": json.dumps({
                            "order_id": target_order_id,
                            "amount_cents": amt,
                            "operation_key": stable_op_key,
                            "reason": "Customer requested full refund"
                        })
                    }
                }],
                prompt_tokens=440,
                completion_tokens=35
            )

        # Step 6: request_refund was called — check response
        if "request_refund" in tool_results:
            rf = tool_results["request_refund"]
            return LLMResponse(
                content=(
                    f"Your refund request for order {target_order_id} has been recorded (Refund ID: {rf.get('refund_id')}). "
                    f"The current status is {rf.get('refund_status', 'REFUND_REQUESTED')}. Please note funds are pending verification."
                ),
                tool_calls=[],
                prompt_tokens=510,
                completion_tokens=45
            )

        if "request_refund" in tool_errors:
            err = tool_errors["request_refund"]
            # Realistic agent response based ONLY on visible error:
            # Does NOT claim write committed or hidden facts
            return LLMResponse(
                content=(
                    f"We encountered an error while processing your refund request for order {target_order_id}: {err} "
                    f"Our system retains your request key ({stable_op_key}) to prevent duplicate transactions if retried."
                ),
                tool_calls=[],
                prompt_tokens=520,
                completion_tokens=45
            )

        # Default fallback
        return LLMResponse(
            content="Thank you for reaching out. How else may I assist you with your order?",
            tool_calls=[],
            prompt_tokens=200,
            completion_tokens=20
        )


class RealOpenAIProvider(BaseLLMProvider):
    """
    Connects to real LLM providers using OpenAI's tool-calling API format
    (compatible with OpenAI models and Google Gemini via Gemini's OpenAI endpoint).
    """
    provider_type: str = "openai"

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini", base_url: Optional[str] = None):
        if not api_key or not api_key.strip():
            raise ValueError("RealOpenAIProvider requires a valid API key. Silent mock substitution is prohibited.")

        import openai
        self.api_key = api_key
        self.model_name = model_name
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0
    ) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=tools if tools else None,
            temperature=temperature
        )

        choice = response.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                })

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens
        )


def resolve_provider(
    provider_type: str = "mock",
    model_name: Optional[str] = None,
    api_key: Optional[str] = None
) -> BaseLLMProvider:
    """
    Factory function ensuring strict separation between Mock and Real execution.
    Never silently substitutes a mock provider if a real provider was requested.
    Never prints or logs API keys.
    """
    provider_type = provider_type.lower()

    if provider_type == "mock":
        return MockToolCallingProvider(model_name=model_name or "mock-deterministic-v1")

    if provider_type in ["openai", "gemini"]:
        key = api_key or os.getenv("OPENAI_API_KEY") if provider_type == "openai" else os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                f"Real provider '{provider_type}' was explicitly requested, but no valid API key was found in "
                f"the environment ({'OPENAI_API_KEY' if provider_type == 'openai' else 'GEMINI_API_KEY'}). "
                f"AgentWindTunnel strictly refuses to silently substitute a mock provider."
            )

        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/" if provider_type == "gemini" else None
        default_model = "gemini-1.5-flash" if provider_type == "gemini" else "gpt-4o-mini"
        return RealOpenAIProvider(
            api_key=key,
            model_name=model_name or default_model,
            base_url=base_url
        )

    raise ValueError(f"Unknown provider type '{provider_type}'. Must be 'mock', 'openai', or 'gemini'.")
