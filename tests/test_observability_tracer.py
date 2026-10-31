import pytest
import time
from backend.observability.tracer import (
    ExecutionTracer,
    mask_sensitive_data
)


def test_sensitive_data_masking():
    # String masking
    text = "Authorization: Bearer sk-ant-1234567890abcdef with key api_key=supersecret123 and user@example.com card 4111-2222-3333-4444"
    masked = mask_sensitive_data(text)
    assert "Bearer ***MASKED***" in masked
    assert "api_key=***MASKED***" in masked
    assert "***@***.***" in masked
    assert "****-****-****-****" in masked
    assert "supersecret123" not in masked
    assert "sk-ant" not in masked

    # Dict masking
    payload = {
        "api_key": "raw_secret_key_value",
        "nested": {
            "token": "tok_xyz987654321",
            "normal": "safe value"
        }
    }
    cleaned = mask_sensitive_data(payload)
    assert cleaned["api_key"] == "***MASKED***"
    assert cleaned["nested"]["token"] == "***MASKED***"
    assert cleaned["nested"]["normal"] == "safe value"


def test_hierarchical_spans_and_parenting():
    tracer = ExecutionTracer()
    
    # Root span
    root_id = tracer.start_span("agent_run.root", attributes={"agent.id": "agent_alpha"})
    
    # Child span
    step_id = tracer.start_span("workflow.step", attributes={"step.id": "step_1"})
    assert tracer.spans[step_id].parent_span_id == root_id

    # Grandchild span
    tool_id = tracer.start_span("tool.invocation", attributes={"tool.name": "search_db"})
    assert tracer.spans[tool_id].parent_span_id == step_id

    # Add event to tool span
    tracer.add_event(tool_id, "query_dispatched", {"query": "SELECT 1"})
    assert len(tracer.spans[tool_id].events) == 1

    # End grandchild
    tracer.end_span(tool_id, status="OK")
    
    # End child
    tracer.end_span(step_id, status="OK")
    
    # End root
    tracer.end_span(root_id, status="OK")

    assert len(tracer.spans) == 3
    assert tracer.spans[tool_id].status == "OK"
    assert tracer.spans[step_id].status == "OK"
    assert tracer.spans[root_id].status == "OK"


def test_token_and_cost_aggregation():
    tracer = ExecutionTracer()
    s1 = tracer.start_span("call_1", attributes={"tokens.prompt": 100, "tokens.completion": 50, "cost.usd": 0.00015})
    tracer.end_span(s1)

    s2 = tracer.start_span("call_2", attributes={"tokens.prompt": 200, "tokens.completion": 80, "cost.usd": 0.00028})
    tracer.end_span(s2)

    summary = tracer.get_summary()
    assert summary["span_count"] == 2
    assert summary["total_prompt_tokens"] == 300
    assert summary["total_completion_tokens"] == 130
    assert summary["total_tokens"] == 430
    assert summary["total_cost_usd"] == pytest.approx(0.00043, rel=1e-4)
    assert summary["has_errors"] is False


def test_opentelemetry_export():
    tracer = ExecutionTracer()
    s1 = tracer.start_span("root_span", attributes={"env": "testing"})
    tracer.end_span(s1, status="OK")

    otel = tracer.export_opentelemetry_format()
    assert "resource" in otel
    assert "scopeSpans" in otel
    spans = otel["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    assert spans[0]["name"] == "root_span"
    assert spans[0]["status"]["code"] == 1
