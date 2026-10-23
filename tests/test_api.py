from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "AgentWindTunnel"


def test_list_scenarios():
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2


def test_run_scripted_via_api():
    response = client.post("/api/runs/scripted", json={
        "scenario_file": "eligible_refund_scenario.json"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PASSED"
    assert "run_id" in data
    assert "scenario_run_id" in data

    # Query details endpoint
    run_id = data["run_id"]
    detail_res = client.get(f"/api/runs/{run_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["status"] == "COMPLETED"


def test_root_dashboard_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "AgentWindTunnel" in response.text


def test_agent_versions_endpoint():
    response = client.get("/api/agent-versions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3


def test_execute_agent_run_via_api():
    response = client.post("/api/runs/execute", json={
        "scenario_file": "eligible_refund_scenario.json",
        "agent_version_id": "agent_v2_improved"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PASSED"
    assert "run_id" in data


def test_healthz_and_readyz():
    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert hz.json()["status"] == "healthy"

    rz = client.get("/readyz")
    assert rz.status_code == 200
    assert rz.json()["status"] == "ready"


def test_overview_metrics_endpoint():
    res = client.get("/api/overview/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "total_runs" in data
    assert "mock_runs" in data
    assert "real_runs" in data
    assert "behavioral_pass_rate" in data
    assert "completion_rate" in data
    assert isinstance(data["recent_runs"], list)


def test_settings_endpoint_masks_secrets():
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "credentials" in data
    # Ensure NO api key text or tokens leaked!
    raw_text = res.text
    assert "AIza" not in raw_text
    assert "sk-" not in raw_text
    assert "execution_limits" in data
    assert data["execution_limits"]["scenario_timeout_sec"] == 30.0


def test_queue_run_and_status_flow():
    # Queue a mock run
    res = client.post("/api/runs/queue", json={
        "agent_version_id": "agent_v2_improved",
        "provider_type": "mock",
        "model_name": "mock-deterministic-v1",
        "scenarios": ["eligible_refund_scenario.json"]
    })
    assert res.status_code == 200
    data = res.json()
    run_id = data["run_id"]
    assert data["status"] == "QUEUED"

    # Check runs list
    list_res = client.get("/api/runs")
    assert list_res.status_code == 200
    runs = list_res.json()
    assert any(r["id"] == run_id for r in runs)

    # Check export endpoint
    export_json = client.get(f"/api/runs/{run_id}/export?format=json")
    assert export_json.status_code == 200

    export_md = client.get(f"/api/runs/{run_id}/export?format=markdown")
    assert export_md.status_code == 200
    assert "AgentWindTunnel Run Report" in export_md.text


