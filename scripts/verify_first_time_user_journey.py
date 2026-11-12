import sys
import time
import json
import httpx

BASE_URL = "http://127.0.0.1:8001"
SYNTH_AGENT_URL = "http://127.0.0.1:8009"

def log(msg, status="INFO"):
    print(f"[{status}] {msg}", flush=True)

def main():
    log("=== Starting EvalNexus First-Time User Journey Verification ===")
    
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # Step 1: Healthcheck
        r = client.get("/healthz")
        assert r.status_code == 200, f"Backend not ready: {r.text}"
        log("Backend is healthy (HTTP 200)", "PASS")

        # Step 2: Register Custom Agent
        log("Step 2: Registering Synthetic AI Agent...")
        agent_payload = {
            "id": "synthetic-refund-agent-v1",
            "name": "Acme Synthetic Refund Bot",
            "endpoint_url": f"{SYNTH_AGENT_URL}/invocations",
            "auth_header_name": "Authorization",
            "auth_token": "test-secret-token-12345",
            "timeout_sec": 10.0
        }
        r = client.post("/api/custom-agents", json=agent_payload)
        assert r.status_code == 200, f"Agent registration failed: {r.text}"
        reg_data = r.json()
        assert reg_data["id"] == "synthetic-refund-agent-v1"
        assert reg_data["auth_token_masked"] == "tes***345"
        log(f"Registered agent '{reg_data['id']}' with masked token '{reg_data['auth_token_masked']}'", "PASS")

        # Step 3: Ping Probe Endpoint
        log("Step 3: Probing Synthetic Agent Endpoint via Ping...")
        r = client.post(f"/api/custom-agents/synthetic-refund-agent-v1/ping")
        assert r.status_code == 200, f"Ping request failed: {r.text}"
        ping_data = r.json()
        assert ping_data["status"] == "ONLINE", f"Ping status not ONLINE: {ping_data}"
        assert ping_data["latency_ms"] >= 0
        log(f"Agent Ping ONLINE! Latency: {ping_data['latency_ms']}ms, Preview: '{ping_data['response_preview']}'", "PASS")

        # Step 4: Create Compatible Custom Scenario
        log("Step 4: Creating Compatible Custom Test Scenario in Scenario Builder...")
        scen_payload = {
            "id": "scen_custom_synthetic_01",
            "name": "Synthetic Agent 3-Day Delivered Order Refund",
            "category": "CUSTOM",
            "description": "Custom customer order delivered 3 days ago. Valid for refund.",
            "fixed_clock": "2026-10-31T12:00:00Z",
            "initial_data": {
                "customer": {
                    "id": "cust_synth_01",
                    "name": "Alex Mercer",
                    "email": "alex.mercer@example.com"
                },
                "orders": [
                    {
                        "id": "ord_synthetic_01",
                        "status": "DELIVERED",
                        "amount_cents": 4500,
                        "currency": "USD",
                        "delivery_days_ago": 3
                    }
                ]
            },
            "customer_messages": ["I ordered ord_synthetic_01 3 days ago and would like a full refund."],
            "expected_checks": {
                "ownership": "PASS",
                "eligibility": "PASS",
                "duplicate": "PASS",
                "state": "PASS",
                "completion": "PASS"
            }
        }
        r = client.post("/api/scenarios/custom", json=scen_payload)
        assert r.status_code == 200, f"Scenario creation failed: {r.text}"
        scen_data = r.json()
        assert scen_data["id"] == "scen_custom_synthetic_01"
        log(f"Created custom scenario '{scen_data['id']}' ({scen_data['name']})", "PASS")

        # Step 5: Execute Evaluation via Test Studio Queue
        log("Step 5: Queuing Evaluation Run against Registered Custom Agent...")
        run_req = {
            "agent_version_id": "synthetic-refund-agent-v1",
            "provider_type": "custom_http",
            "model_name": "synthetic-refund-agent-v1",
            "scenarios": ["scen_custom_synthetic_01"]
        }
        r = client.post("/api/runs/queue", json=run_req)
        assert r.status_code == 200, f"Queue run failed: {r.text}"
        queue_data = r.json()
        run_id = queue_data["run_id"]
        log(f"Queued run '{run_id}' with provider 'custom_http' and model 'synthetic-refund-agent-v1'", "PASS")

        # Step 6: Poll for Completion
        log(f"Step 6: Polling run '{run_id}' for completion...")
        max_wait = 30
        completed = False
        run_record = None
        for i in range(max_wait):
            time.sleep(1.0)
            r = client.get(f"/api/runs/{run_id}")
            assert r.status_code == 200
            run_record = r.json()
            status = run_record.get("status")
            if status in ["COMPLETED", "FAILED"]:
                completed = True
                break
        
        assert completed, f"Run did not finish in {max_wait}s: {run_record}"
        assert run_record["status"] == "COMPLETED", f"Run failed: {run_record}"
        assert run_record["passed_scenarios"] == 1, f"Expected 1 passed scenario, got {run_record['passed_scenarios']}"
        assert run_record["failed_scenarios"] == 0
        log(f"Run {run_id} COMPLETED with 1/1 passed scenarios!", "PASS")

        # Step 7: Inspect Granular Traces & Spans
        log("Step 7: Verifying genuine agent tool execution traces from run record...")
        scen_runs = run_record.get("scenario_runs", [])
        assert len(scen_runs) > 0, "No scenario runs found"
        events = scen_runs[0].get("traces", [])
        log(f"Retrieved {len(events)} execution trace events from scenario run {scen_runs[0]['scenario_run_id']}")
        
        tool_names_called = [ev.get("tool") for ev in events if ev.get("tool")]
        log(f"Traces retrieved: {len(events)} events. Tools called: {tool_names_called}")
        assert "check_refund_eligibility" in tool_names_called, f"Missing check_refund_eligibility in {tool_names_called}"
        assert "request_refund" in tool_names_called, f"Missing request_refund in {tool_names_called}"
        log(f"Genuine tool calls verified: {tool_names_called}", "PASS")

        # Step 8: Negative Test Cases
        log("Step 8: Testing Negative Edge Cases...")
        
        # 8a: Ping agent with wrong auth token
        bad_token_agent = {
            "id": "bad-token-agent",
            "name": "Bad Token Bot",
            "endpoint_url": f"{SYNTH_AGENT_URL}/invocations",
            "auth_header_name": "Authorization",
            "auth_token": "wrong-secret-token",
            "timeout_sec": 5.0
        }
        client.post("/api/custom-agents", json=bad_token_agent)
        r = client.post("/api/custom-agents/bad-token-agent/ping")
        assert r.status_code == 200
        assert r.json()["status"] == "HTTP_401", f"Expected HTTP_401, got {r.json()}"
        log("8a: Unauthorized auth token probe cleanly caught (HTTP_401)", "PASS")

        # 8b: Ping agent with malformed schema endpoint
        malformed_agent = {
            "id": "malformed-agent",
            "name": "Malformed Response Bot",
            "endpoint_url": f"{SYNTH_AGENT_URL}/malformed",
            "auth_header_name": "Authorization",
            "auth_token": "test-secret-token-12345",
            "timeout_sec": 5.0
        }
        client.post("/api/custom-agents", json=malformed_agent)
        # Attempt immediate evaluation against malformed endpoint
        r = client.post("/api/runs/queue", json={
            "agent_version_id": "malformed-agent",
            "provider_type": "custom_http",
            "model_name": "malformed-agent",
            "scenarios": ["scen_custom_synthetic_01"]
        })
        m_run_id = r.json()["run_id"]
        for _ in range(15):
            time.sleep(1.0)
            m_rec = client.get(f"/api/runs/{m_run_id}").json()
            if m_rec.get("status") in ["COMPLETED", "FAILED"]:
                break
        assert m_rec["failed_scenarios"] == 1, "Malformed agent did not fail evaluation"
        log(f"8b: Malformed schema rejected and recorded as failed scenario", "PASS")

        # 8c: SSRF Link-Local Block
        ssrf_payload = {
            "name": "SSRF Attack Bot",
            "endpoint_url": "http://169.254.169.254/latest/meta-data"
        }
        r = client.post("/api/custom-agents", json=ssrf_payload)
        assert r.status_code == 400
        assert "SSRF Protection" in r.text
        log("8c: SSRF metadata endpoint registration blocked (HTTP 400)", "PASS")

    log("=== ALL FIRST-TIME USER JOURNEY TESTS PASSED SUCCESSFULLY! ===", "PASS")

if __name__ == "__main__":
    main()
