import urllib.request
import json
import time

base_url = "http://127.0.0.1:8001"

def get(path):
    req = urllib.request.Request(f"{base_url}{path}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

results = {}

# 1. Overview & metrics
status, data = get("/api/overview/metrics")
assert status == 200
results["1_overview"] = {
    "total_runs": data.get("total_runs"),
    "completed_runs": data.get("completed_runs"),
    "completion_rate": data.get("completion_rate"),
    "total_scenario_runs": data.get("total_scenario_runs")
}

# 2. Test Studio mock run queue
status, queue_res = post("/api/runs/queue", {
    "agent_version_id": "agent_v1_baseline",
    "provider_type": "mock",
    "model_name": "mock-deterministic-v1",
    "scenario_ids": ["scen_norm_01_delivered_5d"]
})
assert status == 200
job_id = queue_res.get("run_id")
time.sleep(3.0)
status, run_data = get(f"/api/runs/{job_id}")
results["2_test_studio_queue"] = {
    "run_id": job_id,
    "status": run_data.get("status"),
    "passed_scenarios": run_data.get("passed_scenarios"),
    "total_scenarios": run_data.get("total_scenarios")
}

# 3. Scenarios Catalog
status, scens = get("/api/scenarios")
assert status == 200
results["3_scenarios_catalog"] = {
    "count": len(scens),
    "sample_ids": [s.get("id") for s in scens[:4]],
    "categories": list(set(s.get("category") for s in scens))
}

# 4. Agent Versions
status, versions = get("/api/agent-versions")
assert status == 200
results["4_agent_versions"] = {
    "versions": [v.get("id") for v in versions],
    "count": len(versions)
}

# 5. Run History
status, runs_list = get("/api/runs")
assert status == 200
results["5_run_history"] = {
    "total_runs_listed": len(runs_list),
    "latest_run": runs_list[0].get("id") if runs_list else None
}

# 6. Run Comparisons
completed_runs = [r for r in runs_list if r.get("status") == "COMPLETED"]
if len(completed_runs) >= 2:
    status, comp = get(f"/api/comparisons?run_a={completed_runs[0]['id']}&run_b={completed_runs[1]['id']}")
    results["6_run_comparison"] = {
        "status": status,
        "run_a": completed_runs[0]["id"],
        "run_b": completed_runs[1]["id"],
        "compatible": comp.get("compatible")
    }
else:
    results["6_run_comparison"] = {"status": "SKIPPED_NOT_ENOUGH_RUNS"}

# 7. Regression Testing
if len(completed_runs) >= 2:
    status, reg = post("/api/regression/compare", {
        "baseline_run_id": completed_runs[1]["id"],
        "candidate_run_id": completed_runs[0]["id"]
    })
    results["7_regression_testing"] = {
        "status": status,
        "overall_verdict": reg.get("overall_verdict"),
        "overall_score": reg.get("overall_score")
    }
else:
    results["7_regression_testing"] = {"status": "SKIPPED_NOT_ENOUGH_RUNS"}

# 8. Failure Analysis
status, colab_detail = get("/api/runs/colab_single_20261111_105817_4c22cb")
failed_checks = [c for sr in colab_detail.get("scenario_runs", []) for c in sr.get("checks", []) if c.get("status") == "FAILED"]
results["8_failure_analysis"] = {
    "target_run": colab_detail.get("run_id"),
    "status": colab_detail.get("status"),
    "failed_checks": [{"check_name": c["check_name"], "message": c["message"]} for c in failed_checks]
}

# 9. Quality Gates
status, qg = post("/api/quality-gates/evaluate", {
    "rules": {
        "min_pass_rate": 80.0,
        "max_p90_latency_ms": 3000,
        "require_no_leaks": True
    },
    "evidence": {
        "pass_rate": 95.0,
        "p90_latency_ms": 1200,
        "leak_count": 0
    }
})
results["9_quality_gates"] = {
    "status": qg.get("status"),
    "passed": qg.get("passed"),
    "score": qg.get("score")
}

# 10. Chaos Fault Lab
status, chaos = post("/api/benchmarks/run", {
    "category": "FAULT",
    "scenarios_count": 1
})
results["10_chaos_lab"] = {
    "status": chaos.get("status"),
    "run_id": chaos.get("run_id"),
    "total_scenarios": chaos.get("total_scenarios")
}

# 11. Custom Agent validation
status, ca = post("/api/custom-agents", {
    "name": "UAT Test Agent",
    "description": "Validation without external network call",
    "endpoint_url": "http://127.0.0.1:8001/healthz",
    "auth_token": "uat-secret-auth-token-12345",
    "timeout_sec": 5
})
results["11_custom_agent"] = {
    "agent_id": ca.get("id"),
    "name": ca.get("name"),
    "auth_token_masked": ca.get("auth_token_masked")
}

# 12. Multi-Agent Workflow
status, wf = post("/api/workflows", {
    "workflow_id": f"wf_uat_{int(time.time())}",
    "name": "UAT Multi-Agent Sequence",
    "description": "Validation of 2-step mock DAG",
    "agents": [
        {
            "agent_id": "analyst_agent",
            "name": "Analyst Agent",
            "role": "Analyst",
            "provider_type": "mock",
            "tools": ["get_order", "check_refund_eligibility"]
        }
    ],
    "steps": [
        {
            "step_id": "step_inspect",
            "name": "Inspect Order",
            "agent_id": "analyst_agent",
            "input_template": "Inspect order ord_elig_01"
        }
    ]
})
wf_id = wf.get("workflow_id")
status, wf_run = post(f"/api/workflows/{wf_id}/run", {})
results["12_workflows"] = {
    "workflow_id": wf_id,
    "workflow_run_id": wf_run.get("id"),
    "status": wf_run.get("status")
}

# 13. Distributed Worker Nodes
status, node = post("/api/cluster/nodes/register", {
    "hostname": "uat-worker-node-01",
    "ip_address": "127.0.0.1",
    "max_concurrency": 2
})
node_id = node.get("node_id")
status, hb = post(f"/api/cluster/nodes/{node_id}/heartbeat", {})
status, nodes_list = get("/api/cluster/nodes")
results["13_distributed_nodes"] = {
    "registered_node_id": node_id,
    "heartbeat_status": hb.get("status"),
    "total_online_nodes": len(nodes_list)
}

# 14. Execution Traces, Arguments & Results
colab_sr = colab_detail["scenario_runs"][0]
traces = colab_sr["traces"]
results["14_traces"] = {
    "trace_count": len(traces),
    "events": [
        {"seq": t["seq"], "event_type": t["event_type"], "tool": t.get("tool"), "duration_ms": t.get("duration_ms")}
        for t in traces
    ]
}

# 15. Historical Qwen & Audited Revision
status, revs = get("/api/runs/colab_single_20261111_105817_4c22cb/revisions")
results["15_historical_and_revision"] = {
    "original_run_id": colab_detail["run_id"],
    "original_status": colab_detail["status"],
    "original_passed": colab_detail["passed_scenarios"],
    "original_failed": colab_detail["failed_scenarios"],
    "revisions_count": len(revs),
    "revision_status": revs[0]["new_status"] if revs else None,
    "revision_mode": revs[0]["evaluation_mode"] if revs else None,
    "audited_by": revs[0]["engineer_id"] if revs else None
}

print(json.dumps(results, indent=2))
