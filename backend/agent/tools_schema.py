from typing import List, Dict, Any

TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": "Fetch status, total amount, delivery timestamp, and details for a customer's order. Customer identity is automatically enforced from the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique ID of the order to query, e.g. 'ord_deliv_8891'."
                    }
                },
                "required": ["order_id"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_refund_eligibility",
            "description": "Check whether an order is eligible for a refund according to store business policies (e.g. 14-day window for delivered orders, cancelled orders, duplicate protection).",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique ID of the order to evaluate."
                    }
                },
                "required": ["order_id"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "request_refund",
            "description": "Submit a full refund request for an eligible order. Must specify the full order amount in cents and a unique operation key for idempotency.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The unique ID of the order being refunded."
                    },
                    "amount_cents": {
                        "type": "integer",
                        "description": "The exact full order amount in cents (e.g. 7450 for $74.50). Partial refunds are not supported."
                    },
                    "operation_key": {
                        "type": "string",
                        "description": "A unique client-generated key (e.g. 'op_order123_uuid') to ensure idempotent processing."
                    },
                    "reason": {
                        "type": "string",
                        "description": "The customer's stated reason for the refund request."
                    }
                },
                "required": ["order_id", "amount_cents", "operation_key"],
                "additionalProperties": False
            }
        }
    }
]


def validate_tool_arguments(tool_name: str, args: Dict[str, Any]) -> None:
    """
    Validates required tool arguments before execution.
    Raises ValueError on schema mismatch.
    """
    if tool_name == "get_order":
        if "order_id" not in args or not isinstance(args["order_id"], str):
            raise ValueError("Tool 'get_order' requires a string 'order_id'.")
    elif tool_name == "check_refund_eligibility":
        if "order_id" not in args or not isinstance(args["order_id"], str):
            raise ValueError("Tool 'check_refund_eligibility' requires a string 'order_id'.")
    elif tool_name == "request_refund":
        if "order_id" not in args:
            raise ValueError("Tool 'request_refund' requires 'order_id'.")
        if "amount_cents" not in args or not isinstance(args["amount_cents"], int):
            raise ValueError("Tool 'request_refund' requires an integer 'amount_cents'.")
        if "operation_key" not in args or not isinstance(args["operation_key"], str):
            raise ValueError("Tool 'request_refund' requires a string 'operation_key'.")
    else:
        raise ValueError(f"Unknown or unauthorized tool '{tool_name}'.")
