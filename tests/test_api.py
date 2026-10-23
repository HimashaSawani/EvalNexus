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

