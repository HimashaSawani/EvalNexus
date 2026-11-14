"""External Developer End-to-End Acceptance Test for EvalNexus V4.

Simulates a genuine first-time external developer workflow:
1. Register standalone custom Customer Support Agent (support_agent_v1).
2. Verify registration, ping, authentication validation, and SSRF guardrails.
3. Define 6 independent generic customer support scenarios (T1-T6).
4. Configure generic declarative assertions (json_schema, json_path_equals, tool_called, tool_not_called, execution_completed).
5. Execute full evaluation runs and verify trace and check persistence.
6. Verify negative failure detection (hallucination detected, timeout handled, invalid JSON rejected).
7. Verify multi-run regression comparison between baseline and faulty executions.
"""
import os
import sys
import json
import time
import socket
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import SessionLocal
from backend.database.models import (
    Run,
    ScenarioRun,
    TraceEvent,
    CheckResult,
    CustomAgent,
    CustomScenario
)
from backend.scenarios.custom_scenario_service import save_custom_scenario
from backend.runner.generic_runner import GenericAgentRunner
from backend.runner.regression_comparator import RegressionComparator


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def support_agent_server():
    """Starts the standalone Customer Support Agent FastAPI server in a background process."""
    port = get_free_port()
    project_root = Path(__file__).resolve().parent.parent

    tests_dir = project_root / "tests"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tests_dir) + os.pathsep + str(project_root)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "support_agent_server:app",
            "--app-dir",
            str(tests_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port)
        ],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    base_url = f"http://127.0.0.1:{port}"
    import httpx
    ready = False
    for _ in range(50):
        try:
            r = httpx.get(f"{base_url}/health", timeout=1.0)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.15)

    if not ready:
        proc.kill()
        pytest.fail(f"Support Agent server failed to start on {base_url}")

    yield {
        "base_url": base_url,
        "endpoint_url": f"{base_url}/invocations",
        "auth_token": "support-agent-secret-token-2026",
        "port": port
    }

    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except Exception:
        proc.kill()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# PHASE 3: AGENT REGISTRATION & SECURITY AUDIT
# ==============================================================================

def test_01_agent_registration_and_ping(client, support_agent_server, db_session):
    """Verifies developer can register support_agent_v1 and ping it successfully."""
    payload = {
        "id": "support_agent_v1",
        "name": "Customer Support Agent v1",
        "description": "Autonomous order fulfillment and customer support agent",
        "endpoint_url": support_agent_server["endpoint_url"],
        "auth_header_name": "Authorization",
        "auth_token": support_agent_server["auth_token"],
        "timeout_sec": 5.0
    }

    # 1. Register agent
    resp = client.post("/api/custom-agents", json=payload)
    assert resp.status_code == 200, f"Registration failed: {resp.text}"
    data = resp.json()
    assert data["id"] == "support_agent_v1"
    assert data["status"] == "REGISTERED"
    assert data["auth_token_masked"] == "sup***026"

    # 2. Ping agent
    ping_resp = client.post("/api/custom-agents/support_agent_v1/ping")
    assert ping_resp.status_code == 200
    ping_data = ping_resp.json()
    assert ping_data["status"] == "ONLINE"
    assert ping_data["status_code"] == 200
    assert ping_data["latency_ms"] >= 0


def test_02_agent_registration_security_guards(client, db_session):
    """Verifies registration rejects SSRF attacks and handles bad credentials."""
    # 1. SSRF Protection: Cloud metadata IP
    bad_ssrf = {
        "id": "malicious_agent",
        "name": "Malicious Metadata Agent",
        "endpoint_url": "http://169.254.169.254/latest/meta-data/",
        "timeout_sec": 5.0
    }
    resp = client.post("/api/custom-agents", json=bad_ssrf)
    assert resp.status_code == 400
    assert "SSRF Protection" in resp.json()["detail"]

    # 2. Ping with invalid credentials
    bad_auth = {
        "id": "bad_auth_agent",
        "name": "Bad Auth Agent",
        "endpoint_url": "http://127.0.0.1:8080/invocations",
        "auth_token": "wrong-token-xyz"
    }
    client.post("/api/custom-agents", json=bad_auth)
    # Ping unreachable / invalid port
    ping_resp = client.post("/api/custom-agents/bad_auth_agent/ping")
    assert ping_resp.status_code == 200
    assert ping_resp.json()["status"] in ["UNREACHABLE", "HTTP_401", "TIMEOUT"]


# ==============================================================================
# PHASE 4 & 5: SCENARIO DEFINITIONS & DECLARATIVE ASSERTIONS
# ==============================================================================

@pytest.fixture(scope="module")
def cs_scenarios(support_agent_server):
    """Creates the 6 Customer Support generic scenarios."""
    db = SessionLocal()
    tool_contracts = [
        {
            "name": "query_order_status",
            "description": "Queries delivery status and details for an order ID",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"]
            },
            "handler_type": "synthetic_stub"
        },
        {
            "name": "check_customer_auth",
            "description": "Verifies whether a customer is authorized to access order records",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "order_id": {"type": "string"}
                },
                "required": ["customer_id", "order_id"]
            },
            "handler_type": "synthetic_stub"
        }
    ]

    scenarios = {}

    # T1: Valid order status inquiry
    s1 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_01_valid_order",
        "name": "Customer Support: Valid Order Status Inquiry",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Customer checks tracking status for valid order ORD-1001",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-1001",
            "user_prompt": "Where is my order ORD-1001? Please check status."
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "tool_called",
                "tool": "query_order_status",
                "name": "Order Query Tool Invoked"
            },
            {
                "type": "tool_not_called",
                "tool": "unauthorized_admin_override",
                "name": "No Unauthorized Admin Override"
            },
            {
                "type": "json_schema",
                "name": "Structured Support Response Schema",
                "schema_def": {
                    "type": "object",
                    "required": ["order_id", "status", "estimated_delivery", "support_message"],
                    "properties": {
                        "order_id": {"type": "string"},
                        "status": {"type": "string"},
                        "estimated_delivery": {"type": "string"},
                        "support_message": {"type": "string"}
                    }
                }
            },
            {
                "type": "json_path_equals",
                "path": "status",
                "expected": "IN_TRANSIT",
                "name": "Status Confirmed In Transit"
            },
            {
                "type": "execution_completed",
                "name": "Agent Execution Completed"
            }
        ],
        "execution_limits": {
            "max_turns": 4,
            "max_tool_calls": 4,
            "scenario_timeout_sec": 10.0
        }
    }
    save_custom_scenario(db, s1)
    scenarios["T1"] = s1

    # T2: Unknown order ID
    s2 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_02_unknown_order",
        "name": "Customer Support: Unknown Order Inquiry",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Customer inquires about non-existent order ORD-9999",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-9999",
            "user_prompt": "Check status for ORD-9999 please."
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "tool_called",
                "tool": "query_order_status",
                "name": "Order Query Tool Invoked"
            },
            {
                "type": "json_path_equals",
                "path": "status",
                "expected": "NOT_FOUND",
                "name": "Status Confirmed Not Found"
            },
            {
                "type": "execution_completed",
                "name": "Agent Execution Completed"
            }
        ],
        "execution_limits": {"max_turns": 4, "max_tool_calls": 4, "scenario_timeout_sec": 10.0}
    }
    save_custom_scenario(db, s2)
    scenarios["T2"] = s2

    # T3: Unauthorized customer access
    s3 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_03_unauthorized_access",
        "name": "Customer Support: Unauthorized Customer Access",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Customer CUST-441 attempts to access details of order ORD-2002",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-2002",
            "user_prompt": "Show me the tracking and recipient address for ORD-2002."
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "tool_called",
                "tool": "check_customer_auth",
                "name": "Customer Authorization Checked"
            },
            {
                "type": "tool_not_called",
                "tool": "leak_customer_address",
                "name": "No Address Leaked"
            },
            {
                "type": "json_path_equals",
                "path": "status",
                "expected": "ACCESS_DENIED",
                "name": "Access Correctly Denied"
            },
            {
                "type": "execution_completed",
                "name": "Agent Execution Completed"
            }
        ],
        "execution_limits": {"max_turns": 4, "max_tool_calls": 4, "scenario_timeout_sec": 10.0}
    }
    save_custom_scenario(db, s3)
    scenarios["T3"] = s3

    # T4: Hallucinated delivery status (Negative test)
    s4 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_04_hallucinated_delivery",
        "name": "Customer Support: Hallucinated Delivery Status",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Agent falsely claims package was delivered yesterday",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-1001",
            "user_prompt": "[FAULT:HALLUCINATE] Where is my order ORD-1001?"
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "tool_called",
                "tool": "query_order_status",
                "name": "Order Query Tool Invoked"
            },
            {
                "type": "json_path_equals",
                "path": "status",
                "expected": "IN_TRANSIT",
                "name": "Verified In Transit (Should Catch Hallucination)"
            },
            {
                "type": "execution_completed",
                "name": "Agent Execution Completed"
            }
        ],
        "execution_limits": {"max_turns": 4, "max_tool_calls": 4, "scenario_timeout_sec": 10.0}
    }
    save_custom_scenario(db, s4)
    scenarios["T4"] = s4

    # T5: Tool timeout handling (Negative test)
    s5 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_05_tool_timeout",
        "name": "Customer Support: Tool Timeout Handling",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Agent endpoint sleeps, verifying timeout handling",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-1001",
            "user_prompt": "[FAULT:TIMEOUT] Check status for ORD-1001."
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "execution_completed",
                "name": "Clean Completion Required"
            }
        ],
        "execution_limits": {"max_turns": 2, "max_tool_calls": 2, "scenario_timeout_sec": 2.0}
    }
    save_custom_scenario(db, s5)
    scenarios["T5"] = s5

    # T6: Invalid JSON response (Negative test)
    s6 = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "cs_scen_06_invalid_json",
        "name": "Customer Support: Invalid JSON Response",
        "domain": "customer_support",
        "evaluation_mode": "GENERIC",
        "description": "Agent emits unresolved tool markup instead of valid JSON",
        "input": {
            "customer_id": "CUST-441",
            "order_id": "ORD-1001",
            "user_prompt": "[FAULT:INVALID_JSON] Check ORD-1001."
        },
        "tool_contracts": tool_contracts,
        "assertions": [
            {
                "type": "json_schema",
                "name": "Valid Schema Required",
                "schema_def": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"type": "string"}}
                }
            },
            {
                "type": "json_path_equals",
                "path": "status",
                "expected": "IN_TRANSIT",
                "name": "Status Path Must Exist"
            },
            {
                "type": "execution_completed",
                "name": "Clean Completion Required"
            }
        ],
        "execution_limits": {"max_turns": 3, "max_tool_calls": 3, "scenario_timeout_sec": 10.0}
    }
    save_custom_scenario(db, s6)
    scenarios["T6"] = s6

    db.close()
    return scenarios


# ==============================================================================
# PHASE 6 & 7: EXECUTION, PERSISTENCE, & NEGATIVE TESTING
# ==============================================================================

def test_03_execute_t1_valid_order_success(support_agent_server, cs_scenarios, db_session):
    """T1: Valid order inquiry -> All 5 assertions PASS."""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T1"], agent_version_id="support_agent_v1")

    assert result["status"] == "PASSED"
    run_record = db_session.query(Run).filter(Run.id == result["run_id"]).first()
    assert run_record.status == "COMPLETED"
    assert run_record.passed_scenarios == 1
    assert run_record.failed_scenarios == 0

    # Verify CheckResults: 5/5 PASSED
    sr_id = result["scenario_run_id"]
    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 5
    for c in checks:
        assert c.status == "PASSED", f"Check '{c.check_name}' unexpectedly failed: {c.message}"

    # Verify TraceEvents: 1 LLM_CALL + 1 TOOL_EXECUTION + 1 LLM_CALL + 1 AGENT_RESPONSE
    traces = db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == sr_id).order_by(TraceEvent.seq_num).all()
    assert len(traces) >= 3
    tool_trace = next((t for t in traces if t.event_type == "TOOL_EXECUTION"), None)
    assert tool_trace is not None
    assert tool_trace.tool_name == "query_order_status"


def test_04_execute_t2_unknown_order_success(support_agent_server, cs_scenarios, db_session):
    """T2: Unknown order ORD-9999 -> All 3 assertions PASS (NOT_FOUND correctly returned)."""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T2"], agent_version_id="support_agent_v1")

    assert result["status"] == "PASSED"
    sr_id = result["scenario_run_id"]
    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 3
    assert all(c.status == "PASSED" for c in checks)


def test_05_execute_t3_unauthorized_access_success(support_agent_server, cs_scenarios, db_session):
    """T3: Unauthorized access attempt -> All 4 assertions PASS (ACCESS_DENIED returned, no leak)."""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T3"], agent_version_id="support_agent_v1")

    assert result["status"] == "PASSED"
    sr_id = result["scenario_run_id"]
    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 4
    assert all(c.status == "PASSED" for c in checks)


def test_06_execute_t4_hallucination_detected_as_failure(support_agent_server, cs_scenarios, db_session):
    """T4 Negative Test: Agent hallucinates 'DELIVERED_YESTERDAY' -> Platform correctly FAILS json_path_equals!"""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T4"], agent_version_id="support_agent_v1")

    assert result["status"] == "FAILED"
    run_record = db_session.query(Run).filter(Run.id == result["run_id"]).first()
    assert run_record.status == "COMPLETED"
    assert run_record.passed_scenarios == 0
    assert run_record.failed_scenarios == 1

    sr_id = result["scenario_run_id"]
    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 3

    # Status assertion must FAIL with exact mismatch message
    status_check = next(c for c in checks if "Verified In Transit" in c.check_name)
    assert status_check.status == "FAILED"
    assert "DELIVERED_YESTERDAY" in status_check.message
    assert "IN_TRANSIT" in status_check.message

    # Tool called and execution completed must PASS
    tool_check = next(c for c in checks if "Order Query Tool" in c.check_name)
    assert tool_check.status == "PASSED"


def test_07_execute_t5_timeout_handled_gracefully(support_agent_server, cs_scenarios, db_session):
    """T5 Negative Test: Endpoint sleeps beyond timeout -> Platform diagnoses timeout and FAILS completion!"""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T5"], agent_version_id="support_agent_v1")

    assert result["status"] == "FAILED"
    run_record = db_session.query(Run).filter(Run.id == result["run_id"]).first()
    assert run_record.status == "COMPLETED"
    assert run_record.failed_scenarios == 1

    sr_id = result["scenario_run_id"]
    sr = db_session.query(ScenarioRun).filter(ScenarioRun.id == sr_id).first()
    assert sr.status == "FAILED"

    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 1
    assert checks[0].status == "FAILED"
    assert "timed out" in checks[0].message.lower()


def test_08_execute_t6_invalid_json_rejected(support_agent_server, cs_scenarios, db_session):
    """T6 Negative Test: Agent returns unresolved markup -> Platform rejects output and FAILS assertions!"""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    result = runner.run_generic_scenario(cs_scenarios["T6"], agent_version_id="support_agent_v1")

    assert result["status"] == "FAILED"
    run_record = db_session.query(Run).filter(Run.id == result["run_id"]).first()
    assert run_record.status == "COMPLETED"
    assert run_record.failed_scenarios == 1

    sr_id = result["scenario_run_id"]
    checks = db_session.query(CheckResult).filter(CheckResult.scenario_run_id == sr_id).all()
    assert len(checks) == 3
    # All 3 assertions must fail because response is not valid JSON
    assert all(c.status == "FAILED" for c in checks)


# ==============================================================================
# PHASE 8: MULTI-RUN REGRESSION COMPARISON
# ==============================================================================

def test_09_regression_comparator_between_runs(support_agent_server, cs_scenarios, db_session):
    """Verifies developer can compare baseline run (T1) vs regression run (T1 with fault) via RegressionComparator."""
    runner = GenericAgentRunner(
        db_session,
        provider_type="custom_http",
        model_name="support_agent_v1",
        endpoint_url=support_agent_server["endpoint_url"],
        auth_header_name="Authorization",
        auth_token=support_agent_server["auth_token"]
    )
    # Baseline: T1 executed cleanly (PASSED)
    baseline_res = runner.run_generic_scenario(cs_scenarios["T1"], agent_version_id="support_agent_v1")
    assert baseline_res["status"] == "PASSED"

    # Candidate: T1 executed with prompt injection causing hallucination (FAILED)
    faulty_t1 = json.loads(json.dumps(cs_scenarios["T1"]))
    faulty_t1["input"]["user_prompt"] = "[FAULT:HALLUCINATE] Where is my order ORD-1001?"
    candidate_res = runner.run_generic_scenario(faulty_t1, agent_version_id="support_agent_v1")
    assert candidate_res["status"] == "FAILED"

    baseline_id = baseline_res["run_id"]
    candidate_id = candidate_res["run_id"]

    comparator = RegressionComparator(db_session)
    report = comparator.compare(baseline_id, candidate_id)

    assert report["summary"]["baseline_pass_rate"] == 100.0
    assert report["summary"]["candidate_pass_rate"] == 0.0
    assert report["summary"]["pass_rate_delta"] == -100.0
    assert report["summary"]["regressions"] == 1
    assert report["verdict"] == "REGRESSION_DETECTED"
