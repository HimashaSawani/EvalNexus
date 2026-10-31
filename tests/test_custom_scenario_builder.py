import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.scenarios.custom_scenario_service import (
    validate_and_parse_scenario,
    CustomScenarioPayload
)


@pytest.fixture
def client():
    return TestClient(app)


def test_scenario_path_traversal_prevention():
    # Attempt directory traversal in ID
    invalid_ids = [
        "../../etc/passwd",
        "../custom_scenario",
        "subfolder/test_scen",
        "test\\windows\\traversal",
        "scenario with spaces",
        "scen!@#$"
    ]
    for bad_id in invalid_ids:
        payload = {
            "id": bad_id,
            "name": "Malicious Traversal Attempt",
            "initial_data": {
                "customer": {"id": "c1", "name": "Alice", "email": "alice@test.com"},
                "orders": [{"id": "o1", "amount_cents": 5000, "status": "DELIVERED"}]
            },
            "customer_messages": ["Please refund order o1"]
        }
        with pytest.raises(Exception):
            validate_and_parse_scenario(payload)


def test_scenario_schema_validation():
    # Negative order amount rejected
    bad_payload = {
        "id": "valid_id_negative_amt",
        "name": "Negative Amount",
        "initial_data": {
            "customer": {"id": "c1", "name": "Alice", "email": "alice@test.com"},
            "orders": [{"id": "o1", "amount_cents": -500, "status": "DELIVERED"}]
        },
        "customer_messages": ["Refund me"]
    }
    with pytest.raises(Exception):
        validate_and_parse_scenario(bad_payload)

    # Empty customer messages rejected
    empty_msgs_payload = {
        "id": "valid_id_empty_msgs",
        "name": "Empty Msgs",
        "initial_data": {
            "customer": {"id": "c1", "name": "Alice", "email": "alice@test.com"},
            "orders": [{"id": "o1", "amount_cents": 1000, "status": "DELIVERED"}]
        },
        "customer_messages": []
    }
    with pytest.raises(Exception):
        validate_and_parse_scenario(empty_msgs_payload)


def test_custom_scenario_crud_and_export_import(client):
    scenario_payload = {
        "id": "custom_test_eval_scenario_01",
        "name": "Custom VIP Customer Scenario",
        "category": "CUSTOM",
        "description": "Evaluation of VIP refund request with high value item",
        "fixed_clock": "2026-10-31T12:00:00Z",
        "initial_data": {
            "customer": {"id": "cust_vip_01", "name": "Sophia VIP", "email": "sophia@example.com"},
            "orders": [
                {
                    "id": "ord_vip_1001",
                    "status": "DELIVERED",
                    "amount_cents": 12500,
                    "currency": "USD",
                    "delivery_days_ago": 3
                }
            ]
        },
        "customer_messages": [
            "Hi, I received order ord_vip_1001 3 days ago and would like a full refund."
        ],
        "fault_configs": [],
        "expected_checks": {
            "ownership": "PASS",
            "eligibility": "PASS",
            "duplicate": "PASS",
            "state": "PASS",
            "completion": "PASS"
        },
        "tags": ["vip", "high_value"]
    }

    # 1. Create scenario
    r = client.post("/api/scenarios/custom", json=scenario_payload)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["id"] == "custom_test_eval_scenario_01"
    assert res["status"] == "SAVED"

    # 2. List custom scenarios
    r = client.get("/api/scenarios/custom")
    assert r.status_code == 200
    scenarios = r.json()
    match = next((s for s in scenarios if s["id"] == "custom_test_eval_scenario_01"), None)
    assert match is not None
    assert match["name"] == "Custom VIP Customer Scenario"

    # 3. Get single scenario
    r = client.get("/api/scenarios/custom/custom_test_eval_scenario_01")
    assert r.status_code == 200
    single = r.json()
    assert single["id"] == "custom_test_eval_scenario_01"
    assert len(single["customer_messages"]) == 1

    # 4. Export scenario JSON
    r = client.get("/api/scenarios/custom/custom_test_eval_scenario_01/export")
    assert r.status_code == 200
    exported_json = r.json()
    assert exported_json["id"] == "custom_test_eval_scenario_01"

    # 5. Import scenario JSON with modified ID
    exported_json["id"] = "custom_test_eval_scenario_imported"
    exported_json["name"] = "Imported Scenario Copy"
    r = client.post("/api/scenarios/custom/import", json={"content": json.dumps(exported_json)})
    assert r.status_code == 200
    assert r.json()["id"] == "custom_test_eval_scenario_imported"

    # Verify imported scenario exists
    r = client.get("/api/scenarios/custom/custom_test_eval_scenario_imported")
    assert r.status_code == 200

    # 6. Delete scenarios
    r = client.delete("/api/scenarios/custom/custom_test_eval_scenario_01")
    assert r.status_code == 200
    assert r.json()["status"] == "DELETED"

    r = client.delete("/api/scenarios/custom/custom_test_eval_scenario_imported")
    assert r.status_code == 200
    assert r.json()["status"] == "DELETED"

