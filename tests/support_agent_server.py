"""Standalone Synthetic Customer Support AI Agent (FastAPI).

Implements the EvalNexus Custom Agent HTTP contract:
- Request: CustomAgentRequestPayload (messages, tools, temperature, timeout_sec)
- Response: CustomAgentResponsePayload (content, tool_calls, prompt_tokens, completion_tokens)

Supports:
- Order status inquiries (ORD-1001 -> IN_TRANSIT)
- Unknown orders (ORD-9999 -> NOT_FOUND)
- Customer authorization checks (ORD-2002 by CUST-441 -> ACCESS_DENIED)
- Deterministic fault injection triggers:
  - [FAULT:HALLUCINATE] -> returns DELIVERED_YESTERDAY instead of IN_TRANSIT
  - [FAULT:TIMEOUT]     -> sleeps to trigger HTTP timeout
  - [FAULT:INVALID_JSON]-> emits unparsed markup / broken non-JSON string
  - [FAULT:UNAUTHORIZED]-> invokes prohibited leak tool
"""
import time
import json
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Customer Support Agent v1", version="1.0.0")

VALID_AUTH_TOKEN = "support-agent-secret-token-2026"


class ToolCallFunction(BaseModel):
    name: str
    arguments: Any


class ToolCall(BaseModel):
    id: Optional[str] = None
    type: str = "function"
    function: ToolCallFunction


class InvocationsRequest(BaseModel):
    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    temperature: Optional[float] = 0.0
    timeout_sec: Optional[float] = 15.0
    probe: Optional[bool] = False


class InvocationsResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = Field(default_factory=list)
    prompt_tokens: int = 140
    completion_tokens: int = 45
    metadata: Optional[Dict[str, Any]] = None


@app.get("/health")
def health():
    return {"status": "ok", "agent": "support_agent_v1"}


@app.post("/invocations")
async def invoke_agent(
    payload: InvocationsRequest,
    authorization: Optional[str] = Header(None)
):
    # 1. Authenticate Request
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    token = authorization.replace("Bearer ", "").strip()
    if token != VALID_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API credential")

    # 2. Handle Lightweight Probe / Ping
    if payload.probe:
        return {
            "status": "ONLINE",
            "agent": "support_agent_v1",
            "message": "Ready to process customer support inquiries"
        }

    # 3. Analyze Message History
    messages = payload.messages or []
    last_user_msg = ""
    last_tool_msg = None

    for m in reversed(messages):
        role = m.get("role")
        if role == "user" and not last_user_msg:
            last_user_msg = m.get("content") or ""
        elif role == "tool" and last_tool_msg is None:
            last_tool_msg = m

    # 4. Check for Fault Injection Triggers
    if "[FAULT:TIMEOUT]" in last_user_msg:
        # Sleep for 5 seconds to trigger client-side timeout
        await asyncio.sleep(5.0)
        return InvocationsResponse(content="Delayed response after timeout")

    if "[FAULT:INVALID_JSON]" in last_user_msg:
        # Emit unresolved tool call markup instead of valid JSON answer
        return InvocationsResponse(
            content="<tool_call>\n{\"name\": \"query_order_status\", \"arguments\": {\"order_id\": \"ORD-1001\"}}\n</tool_call>"
        )

    # 5. Multi-Turn Logic: Check if we are responding to a tool execution result
    if last_tool_msg:
        tool_name = last_tool_msg.get("name")
        raw_content = last_tool_msg.get("content") or "{}"
        try:
            tool_data = json.loads(raw_content)
        except Exception:
            tool_data = {}

        # If user injected hallucination fault
        if "[FAULT:HALLUCINATE]" in last_user_msg:
            hallucinated_answer = {
                "order_id": "ORD-1001",
                "status": "DELIVERED_YESTERDAY",
                "estimated_delivery": "2026-11-13",
                "support_message": "Your package was delivered yesterday to the front porch."
            }
            return InvocationsResponse(
                content=json.dumps(hallucinated_answer),
                tool_calls=[],
                prompt_tokens=220,
                completion_tokens=55
            )

        # Handle authorization result
        if tool_name == "check_customer_auth":
            # Check if access was denied
            if "ORD-2002" in last_user_msg:
                denied_answer = {
                    "order_id": "ORD-2002",
                    "status": "ACCESS_DENIED",
                    "support_message": "Access denied: You are not authorized to view details for this order."
                }
                return InvocationsResponse(
                    content=json.dumps(denied_answer),
                    tool_calls=[],
                    prompt_tokens=180,
                    completion_tokens=40
                )

        # Handle order status tool result
        if "ORD-9999" in last_user_msg:
            not_found_answer = {
                "order_id": "ORD-9999",
                "status": "NOT_FOUND",
                "support_message": "Order ORD-9999 was not found in our fulfillment records."
            }
            return InvocationsResponse(
                content=json.dumps(not_found_answer),
                tool_calls=[],
                prompt_tokens=190,
                completion_tokens=45
            )

        # Default Valid Order (ORD-1001)
        valid_answer = {
            "order_id": "ORD-1001",
            "status": "IN_TRANSIT",
            "estimated_delivery": "2026-11-15",
            "support_message": "Your order ORD-1001 is currently in transit and expected to arrive on 2026-11-15."
        }
        return InvocationsResponse(
            content=json.dumps(valid_answer),
            tool_calls=[],
            prompt_tokens=200,
            completion_tokens=50
        )

    # 6. First Turn Logic: Inspect User Request & Decide Tool Call
    if "ORD-2002" in last_user_msg:
        # Cross-customer access inquiry -> call auth verification tool
        tc = ToolCall(
            id="call_auth_001",
            function=ToolCallFunction(
                name="check_customer_auth",
                arguments={"customer_id": "CUST-441", "order_id": "ORD-2002"}
            )
        )
        return InvocationsResponse(
            content=None,
            tool_calls=[tc],
            prompt_tokens=130,
            completion_tokens=25
        )

    if "[FAULT:UNAUTHORIZED]" in last_user_msg:
        # Call a prohibited / unallowlisted tool
        tc = ToolCall(
            id="call_prohibited_001",
            function=ToolCallFunction(
                name="leak_customer_address",
                arguments={"order_id": "ORD-1001"}
            )
        )
        return InvocationsResponse(
            content=None,
            tool_calls=[tc],
            prompt_tokens=120,
            completion_tokens=25
        )

    # Standard order lookup (ORD-1001 or ORD-9999)
    order_id = "ORD-9999" if "ORD-9999" in last_user_msg else "ORD-1001"
    tc = ToolCall(
        id="call_order_001",
        function=ToolCallFunction(
            name="query_order_status",
            arguments={"order_id": order_id}
        )
    )
    return InvocationsResponse(
        content=None,
        tool_calls=[tc],
        prompt_tokens=135,
        completion_tokens=25
    )

