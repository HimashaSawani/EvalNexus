import time
import json
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Synthetic Test AI Agent")

VALID_TOKEN = "Bearer test-secret-token-12345"

@app.post("/invocations")
async def invocations(request: Request, authorization: Optional[str] = Header(None)):
    if authorization != VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing bearer token")

    body = await request.json()
    messages = body.get("messages", [])

    # Check for ping probe
    if len(messages) == 1 and messages[0].get("content") == "ping":
        return {
            "content": "synthetic-agent-v1-online",
            "tool_calls": [],
            "prompt_tokens": 10,
            "completion_tokens": 5
        }

    # Inspect visible tool results
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    tool_names = [m.get("name") for m in tool_messages]

    # Turn 1: Call check_refund_eligibility
    if "check_refund_eligibility" not in tool_names:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_synth_elig_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": "check_refund_eligibility",
                        "arguments": json.dumps({"order_id": "ord_synthetic_01"})
                    }
                }
            ],
            "prompt_tokens": 160,
            "completion_tokens": 25
        }

    # Turn 2: Call request_refund with idempotency key
    if "request_refund" not in tool_names:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_synth_req_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": "request_refund",
                        "arguments": json.dumps({
                            "order_id": "ord_synthetic_01",
                            "operation_key": "op_synth_key_999",
                            "amount_cents": 4500
                        })
                    }
                }
            ],
            "prompt_tokens": 250,
            "completion_tokens": 30
        }

    # Turn 3: Final terminal answer
    return {
        "content": "Your refund request of $45.00 for order ord_synthetic_01 has been initiated with status REFUND_REQUESTED.",
        "tool_calls": [],
        "prompt_tokens": 320,
        "completion_tokens": 40
    }

@app.post("/malformed")
async def malformed_endpoint():
    # Returns non-conforming schema (missing required fields / invalid tool_call shape)
    return {"invalid_key": 12345}

@app.post("/timeout")
async def timeout_endpoint():
    time.sleep(10.0)
    return {"content": "too late"}


# -------------------------------------------------------------
# Generic Cross-Domain Reference Agent Endpoints (V4)
# -------------------------------------------------------------

@app.post("/sentiment")
async def sentiment_agent(request: Request, authorization: Optional[str] = Header(None)):
    """Reference Agent A: Sentiment Classifier"""
    if authorization != VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing bearer token")

    body = await request.json()
    messages = body.get("messages", [])
    
    # Extract last user message
    user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    
    # Check for malformed mode flag
    if "malformed_output" in user_msg.lower():
        return {
            "content": "This is plain unparseable text without any JSON brackets.",
            "tool_calls": [],
            "prompt_tokens": 50,
            "completion_tokens": 10
        }

    user_lower = user_msg.lower()
    neg_words = ["bad", "terrible", "awful", "hate", "frustrat", "slow", "broken", "worst", "horrible"]
    is_neg = any(w in user_lower for w in neg_words)

    if is_neg:
        res_payload = {
            "sentiment": "NEGATIVE",
            "score": 0.14,
            "confidence": 0.95,
            "summary": "Customer expressed dissatisfaction and frustration."
        }
    else:
        res_payload = {
            "sentiment": "POSITIVE",
            "score": 0.94,
            "confidence": 0.98,
            "summary": "Customer expressed positive feedback and high satisfaction."
        }

    return {
        "content": json.dumps(res_payload, indent=2),
        "tool_calls": [],
        "prompt_tokens": 120,
        "completion_tokens": 40
    }


@app.post("/travel")
async def travel_agent(request: Request, authorization: Optional[str] = Header(None)):
    """Reference Agent B: Structured Travel Itinerary Planner with Tool Calling"""
    if authorization != VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing bearer token")

    body = await request.json()
    messages = body.get("messages", [])

    # Extract user message & destination
    user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    dest = "Kyoto"
    for cand in ["Tokyo", "Kyoto", "Paris", "London", "Rome", "New York"]:
        if cand.lower() in user_msg.lower():
            dest = cand
            break

    # Check visible tool calls
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    tool_names = [m.get("name") for m in tool_messages]

    # Mode: Prohibited tool test
    if "call_prohibited" in user_msg.lower() and "unauthorized_booking" not in tool_names:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_proh_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": "unauthorized_booking",
                        "arguments": json.dumps({"destination": dest, "charge_usd": 1500})
                    }
                }
            ],
            "prompt_tokens": 150,
            "completion_tokens": 25
        }

    # Step 1: Call check_weather
    if "check_weather" not in tool_names:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_weather_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": "check_weather",
                        "arguments": json.dumps({"city": dest})
                    }
                }
            ],
            "prompt_tokens": 180,
            "completion_tokens": 25
        }

    # Step 2: Call lookup_poi
    if "lookup_poi" not in tool_names:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_poi_{int(time.time()*1000)}",
                    "type": "function",
                    "function": {
                        "name": "lookup_poi",
                        "arguments": json.dumps({"city": dest, "category": "historic"})
                    }
                }
            ],
            "prompt_tokens": 240,
            "completion_tokens": 25
        }

    # Step 3: Produce final structured itinerary
    payload = {
        "destination": dest,
        "days": 3,
        "status": "PLANNED",
        "itinerary": {
            "days": [
                {"day": 1, "activity": f"Explore {dest} Historic Shrines & Temples", "weather": "Sunny"},
                {"day": 2, "activity": f"Visit {dest} Traditional Market & Gardens", "weather": "Sunny"},
                {"day": 3, "activity": f"Scenic Walking Tour & Departure from {dest}", "weather": "Sunny"}
            ]
        }
    }

    return {
        "content": json.dumps(payload, indent=2),
        "tool_calls": [],
        "prompt_tokens": 340,
        "completion_tokens": 85
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8009, log_level="warning")

