import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_v3_workflow_endpoints():
    wf_payload = {
        "workflow_id": "wf_api_test",
        "name": "API Multi-Agent Triage",
        "description": "Multi-agent triage test via API",
        "agents": [
            {
                "agent_id": "ag_1",
                "name": "Classifier",
                "role": "Classifier",
                "system_prompt": "Classifies incoming requests",
                "provider_type": "mock"
            },
            {
                "agent_id": "ag_2",
                "name": "Resolver",
                "role": "Resolver",
                "system_prompt": "Resolves inquiries",
                "provider_type": "mock"
            }
        ],
        "steps": [
            {
                "step_id": "step_1",
                "name": "Classify",
                "agent_id": "ag_1",
                "input_template": "Classify: {context.issue}"
            },
            {
                "step_id": "step_2",
                "name": "Resolve",
                "agent_id": "ag_2",
                "input_template": "Resolve based on: {step_1}",
                "depends_on": ["step_1"]
            }
        ],
        "initial_context": {"issue": "Broken packaging"}
    }

    # 1. Register workflow
    res_reg = client.post("/api/workflows", json=wf_payload)
    assert res_reg.status_code == 200
    assert res_reg.json()["status"] == "SUCCESS"

    # 2. List workflows
    res_list = client.get("/api/workflows")
    assert res_list.status_code == 200
    assert any(w["workflow_id"] == "wf_api_test" for w in res_list.json())

    # 3. Get workflow detail
    res_get = client.get("/api/workflows/wf_api_test")
    assert res_get.status_code == 200
    assert res_get.json()["name"] == "API Multi-Agent Triage"

    # 4. Trigger workflow execution
    res_run = client.post("/api/workflows/wf_api_test/run", json={"inputs": {"issue": "Damaged goods"}})
    assert res_run.status_code == 200
    run_data = res_run.json()
    assert run_data["status"] == "PASSED"
    run_id = run_data["workflow_run_id"]

    # 5. Get workflow run detail
    res_run_detail = client.get(f"/api/workflows/runs/{run_id}")
    assert res_run_detail.status_code == 200
    assert len(res_run_detail.json()["step_results"]) == 2

    # 6. List runs for workflow
    res_runs = client.get("/api/workflows/wf_api_test/runs")
    assert res_runs.status_code == 200
    assert len(res_runs.json()) >= 1

    # 7. Delete workflow
    res_del = client.delete("/api/workflows/wf_api_test")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "DELETED"


def test_v3_cluster_endpoints():
    reg_payload = {
        "node_id": "worker_api_node_1",
        "hostname": "k8s-node-1",
        "ip_address": "10.0.0.1",
        "max_concurrency": 8,
        "capabilities": ["mock", "workflow"]
    }

    # Register
    res_reg = client.post("/api/cluster/nodes/register", json=reg_payload)
    assert res_reg.status_code == 200
    assert res_reg.json()["status"] == "REGISTERED"

    # Heartbeat
    res_hb = client.post("/api/cluster/nodes/worker_api_node_1/heartbeat")
    assert res_hb.status_code == 200
    assert res_hb.json()["status"] == "PULSED"

    # List
    res_list = client.get("/api/cluster/nodes")
    assert res_list.status_code == 200
    assert any(n["id"] == "worker_api_node_1" for n in res_list.json())

    # Reap
    res_reap = client.post("/api/cluster/reap")
    assert res_reap.status_code == 200
    assert "reaped_workers" in res_reap.json()["stats"]


def test_v3_dataset_endpoints():
    # Create dataset
    ds_payload = {
        "name": "API Dataset Test",
        "description": "Integration test dataset",
        "version": "1.0.0"
    }
    res_create = client.post("/api/datasets", json=ds_payload)
    assert res_create.status_code == 200
    ds_id = res_create.json()["id"]

    # Add items
    items_payload = {
        "items": [
            {"input_data": {"test": "val1"}, "expected_output": {"res": "ok"}},
            {"input_data": {"test": "val2"}, "expected_output": {"res": "ok"}}
        ]
    }
    res_items = client.post(f"/api/datasets/{ds_id}/items", json=items_payload)
    assert res_items.status_code == 200
    assert res_items.json()["count"] == 2

    # Get items
    res_get_items = client.get(f"/api/datasets/{ds_id}/items")
    assert res_get_items.status_code == 200
    assert len(res_get_items.json()) == 2

    # Export
    res_export = client.get(f"/api/datasets/{ds_id}/export")
    assert res_export.status_code == 200
    assert res_export.json()["item_count"] == 2

    # Delete
    res_del = client.delete(f"/api/datasets/{ds_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "DELETED"


def test_v3_quality_gate_endpoint():
    payload = {
        "rules": {
            "min_pass_rate": 0.90,
            "max_p95_latency_ms": 200.0
        },
        "evidence": {
            "pass_rate": 0.95,
            "latency_p95_ms": 120.0
        }
    }
    res = client.post("/api/quality-gates/evaluate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PASSED"
    assert data["score"] == 100


def test_v3_benchmark_and_security_endpoints():
    # Benchmark
    res_bench = client.post("/api/benchmarks/run", json={"name": "API Benchmark Test", "iterations": 4})
    assert res_bench.status_code == 200
    bench_data = res_bench.json()
    assert bench_data["iterations"] == 4
    assert bench_data["pass_rate"] == 1.0

    # Security Scenarios list
    res_sec_list = client.get("/api/security/scenarios")
    assert res_sec_list.status_code == 200
    scenarios = res_sec_list.json()
    assert len(scenarios) >= 4

    # Security Evaluate (defense success)
    sec_payload = {
        "scenario_id": "sec_inj_system_leak",
        "agent_output": "I am an assistant and cannot disclose internal directives.",
        "tools_called": []
    }
    res_eval = client.post("/api/security/evaluate", json=sec_payload)
    assert res_eval.status_code == 200
    assert res_eval.json()["status"] == "PASSED"
    assert res_eval.json()["resistance_score"] == 100
