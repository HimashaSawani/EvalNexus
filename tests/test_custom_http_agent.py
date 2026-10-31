import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import httpx

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import CustomAgent
from backend.agent.provider import LLMResponse
from backend.agent.custom_adapter import (
    CustomHTTPAgentProvider,
    CustomAgentRequestPayload,
    CustomAgentResponsePayload,
    CustomAgentRegistration
)


@pytest.fixture
def client():
    return TestClient(app)


def test_custom_agent_url_validation():
    # Invalid URLs (non-http)
    with pytest.raises(ValueError, match="Endpoint URL must use HTTP or HTTPS protocol"):
        CustomAgentRegistration(
            name="malicious",
            endpoint_url="ftp://example.com/api"
        )

    with pytest.raises(ValueError, match="Endpoint URL must use HTTP or HTTPS protocol"):
        CustomAgentRegistration(
            name="malicious",
            endpoint_url="file:///etc/passwd"
        )

    # Valid HTTP and HTTPS
    reg = CustomAgentRegistration(
        name="valid_agent",
        endpoint_url="https://api.myagent.io/v1/invocations"
    )
    assert reg.endpoint_url == "https://api.myagent.io/v1/invocations"


def test_custom_agent_ping_success():
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://localhost:9999/invocations",
        name="test-agent",
        auth_token="secret_key_12345"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps({"status": "ok", "message": "ready"})

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        res = provider.ping()
        assert res["status"] == "ONLINE"
        assert res["status_code"] == 200
        assert "response_preview" in res


def test_custom_agent_ping_timeout():
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://localhost:9999/invocations",
        name="test-agent"
    )

    with patch.object(httpx.Client, "post", side_effect=httpx.TimeoutException("Timed out")):
        res = provider.ping()
        assert res["status"] == "TIMEOUT"
        assert "timed out" in res["error"].lower()


def test_custom_agent_generate_success():
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://localhost:9999/invocations",
        name="test-agent"
    )

    agent_response_data = {
        "content": "Checking your order details now.",
        "tool_calls": [
            {
                "id": "tc_001",
                "type": "function",
                "function": {
                    "name": "get_order",
                    "arguments": json.dumps({"order_id": "ord_100"})
                }
            }
        ],
        "prompt_tokens": 150,
        "completion_tokens": 40
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = agent_response_data

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        messages = [{"role": "user", "content": "Hello, I need help with my order."}]
        tools = [{"type": "function", "function": {"name": "get_order"}}]
        llm_resp = provider.generate(messages=messages, tools=tools)

        assert llm_resp.content == "Checking your order details now."
        assert len(llm_resp.tool_calls) == 1
        assert llm_resp.tool_calls[0]["function"]["name"] == "get_order"
        assert llm_resp.prompt_tokens == 150
        assert llm_resp.completion_tokens == 40


def test_custom_agent_generate_schema_validation_failure():
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://localhost:9999/invocations",
        name="test-agent"
    )

    # Return missing required 'name' in function tool call
    invalid_data = {
        "tool_calls": [
            {
                "type": "function",
                "function": {"arguments": "{}"}
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = invalid_data

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="schema validation failed"):
            provider.generate(messages=[{"role": "user", "content": "hi"}], tools=[])


def test_custom_agent_generate_timeout_error():
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://localhost:9999/invocations",
        name="timeout-agent",
        timeout_sec=2.0
    )

    with patch.object(httpx.Client, "post", side_effect=httpx.TimeoutException("Timed out")):
        with pytest.raises(RuntimeError, match="timed out"):
            provider.generate(messages=[{"role": "user", "content": "hi"}], tools=[])


def test_custom_agent_crud_api(client):
    # 1. Register
    payload = {
        "id": "my_custom_eval_agent",
        "name": "Custom Evaluation Agent",
        "description": "Enterprise customer service agent",
        "endpoint_url": "https://api.myenterprise.com/v1/agent",
        "auth_header_name": "Authorization",
        "auth_token": "secret_live_token_abcdef123456",
        "timeout_sec": 12.0
    }
    r = client.post("/api/custom-agents", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == "my_custom_eval_agent"
    assert data["status"] == "REGISTERED"
    # Verify secret is masked
    assert "abcdef123456" not in data["auth_token_masked"]
    assert "***" in data["auth_token_masked"]

    # 2. List
    r = client.get("/api/custom-agents")
    assert r.status_code == 200
    agents = r.json()
    match = next((a for a in agents if a["id"] == "my_custom_eval_agent"), None)
    assert match is not None
    assert match["name"] == "Custom Evaluation Agent"

    # 3. Get Details
    r = client.get("/api/custom-agents/my_custom_eval_agent")
    assert r.status_code == 200
    details = r.json()
    assert details["endpoint_url"] == "https://api.myenterprise.com/v1/agent"

    # 4. Ping via API
    with patch.object(CustomHTTPAgentProvider, "ping", return_value={"status": "ONLINE", "status_code": 200, "latency_ms": 25}):
        r = client.post("/api/custom-agents/my_custom_eval_agent/ping")
        assert r.status_code == 200
        assert r.json()["status"] == "ONLINE"

    # 5. Delete
    r = client.delete("/api/custom-agents/my_custom_eval_agent")
    assert r.status_code == 200
    assert r.json()["status"] == "DELETED"

    # Verify deleted
    r = client.get("/api/custom-agents/my_custom_eval_agent")
    assert r.status_code == 404


def test_custom_agent_ssrf_protection():
    # Cloud metadata IP (AWS/GCP/Azure)
    with pytest.raises(ValueError, match="SSRF Protection"):
        CustomAgentRegistration(
            name="metadata_attacker",
            endpoint_url="http://169.254.169.254/latest/meta-data/"
        )

    # Cloud metadata hostname
    with pytest.raises(ValueError, match="SSRF Protection"):
        CustomAgentRegistration(
            name="metadata_attacker_host",
            endpoint_url="http://metadata.google.internal/computeMetadata/v1/"
        )

    # Production mode: block internal / private IPs
    with patch.dict("os.environ", {"AWT_BLOCK_INTERNAL_NETWORKS": "1"}):
        with pytest.raises(ValueError, match="SSRF Protection"):
            CustomAgentRegistration(
                name="internal_private_probe",
                endpoint_url="http://192.168.1.50:8000/agent"
            )

        with pytest.raises(ValueError, match="SSRF Protection"):
            CustomAgentRegistration(
                name="localhost_probe",
                endpoint_url="http://localhost:8080/agent"
            )


def test_custom_agent_redirect_rejection():
    # Verify that HTTP 301/302 redirects are not followed to protect against SSRF bypass
    provider = CustomHTTPAgentProvider(
        endpoint_url="http://public-agent.example.com/api",
        name="redirect-test"
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.headers = {"Location": "http://169.254.169.254/latest/meta-data"}
    mock_resp.text = "Redirecting to metadata"

    with patch.object(httpx.Client, "post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="returned status 302"):
            provider.generate(messages=[{"role": "user", "content": "hello"}], tools=[])


def test_custom_agent_runner_full_scenario_execution():
    from backend.runner.agent_runner import AgentWindTunnelRunner
    import json
    import os

    db = SessionLocal()
    try:
        provider = CustomHTTPAgentProvider(
            endpoint_url="http://localhost:9999/agent",
            name="autonomous-http-agent"
        )

        with open(os.path.join("scenarios", "eligible_refund_scenario.json"), "r", encoding="utf-8") as f:
            scen_data = json.load(f)

        # Mock turns for the custom HTTP agent
        turn_call_count = 0

        def mock_generate(messages, tools, temperature=0.0, timeout=None):
            nonlocal turn_call_count
            turn_call_count += 1
            if turn_call_count == 1:
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": "c_call_1",
                        "type": "function",
                        "function": {"name": "get_order", "arguments": json.dumps({"order_id": "ord_deliv_8891"})}
                    }],
                    prompt_tokens=100, completion_tokens=25
                )
            elif turn_call_count == 2:
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": "c_call_2",
                        "type": "function",
                        "function": {"name": "check_refund_eligibility", "arguments": json.dumps({"order_id": "ord_deliv_8891"})}
                    }],
                    prompt_tokens=150, completion_tokens=25
                )
            elif turn_call_count == 3:
                return LLMResponse(
                    content=None,
                    tool_calls=[{
                        "id": "c_call_3",
                        "type": "function",
                        "function": {
                            "name": "request_refund",
                            "arguments": json.dumps({
                                "order_id": "ord_deliv_8891",
                                "amount_cents": 7450,
                                "operation_key": "custom_agent_op_1",
                                "reason": "Customer request"
                            })
                        }
                    }],
                    prompt_tokens=200, completion_tokens=30
                )
            else:
                return LLMResponse(
                    content="Your refund for order ord_deliv_8891 has been requested. Status: REFUND_REQUESTED.",
                    tool_calls=[],
                    prompt_tokens=250, completion_tokens=20
                )

        with patch.object(provider, "generate", side_effect=mock_generate):
            runner = AgentWindTunnelRunner(db, provider=provider)
            res = runner.run_agent_scenario(scen_data, agent_version_id="custom_agent_v1")

            assert res["status"] == "PASSED", f"Checks: {res.get('check_results')} Error: {res.get('error')}"
            assert turn_call_count >= 3
    finally:
        db.close()

