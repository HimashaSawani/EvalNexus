import urllib.request
import urllib.error
import json

base_url = "http://127.0.0.1:8001"

def request(method, path, body=None, headers=None):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_body = str(e)
        return e.code, err_body

results = {}

# 1. Invalid scenario ID in export
status, body = request("POST", "/api/scenarios/bundle/export", {"scenario_ids": ["non_existent_scen_9999"]})
results["1_invalid_scenario_id"] = {
    "status": status,
    "expected": 400,
    "pass": status == 400,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 2. Invalid / missing run lookup (404)
status, body = request("GET", "/api/runs/non_existent_run_8888")
results["2_missing_run_404"] = {
    "status": status,
    "expected": 404,
    "pass": status == 404,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 3. Malformed import payload
status, body = request("POST", "/api/runs/import-colab", {"invalid_key": "junk_data"})
results["3_malformed_import_payload"] = {
    "status": status,
    "expected_in": [400, 422],
    "pass": status in [400, 422],
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 4. Duplicate Colab import rejection (409 Conflict)
# Attempt importing identical batch_run_id without overwrite=True
status, body = request("POST", "/api/runs/import-colab", {
    "schema_version": "evalnexus-evaluation-result/v1",
    "bundle_id": "test_bundle",
    "batch_run_id": "colab_single_20261111_105817_4c22cb",
    "model_name": "Qwen2.5-1.5B",
    "results": []
})
results["4_duplicate_import_conflict"] = {
    "status": status,
    "expected": 409,
    "pass": status == 409,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 5. Invalid Custom Agent SSRF protection (private IP blocking)
status, body = request("POST", "/api/custom-agents", {
    "name": "Malicious Agent",
    "endpoint_url": "http://169.254.169.254/latest/meta-data/",
    "auth_token": "token"
})
results["5_ssrf_metadata_blocked"] = {
    "status": status,
    "expected": 400,
    "pass": status == 400,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 6. Cancellation of non-existent run
status, body = request("POST", "/api/runs/non_existent_run_7777/cancel", {})
results["6_cancel_missing_run"] = {
    "status": status,
    "expected": 404,
    "pass": status == 404,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 7. Quality gate evaluation on missing run
status, body = request("POST", "/api/quality-gates/evaluate", {
    "rules": {"min_pass_rate": 100.0},
    "evidence": {"pass_rate": 50.0}
})
results["7_quality_gate_failure_behavior"] = {
    "status": status,
    "expected_gate_status": "FAILED",
    "pass": body.get("status") == "FAILED",
    "score": body.get("score")
}

# 8. Invalid workflow ID lookup
status, body = request("GET", "/api/workflows/non_existent_wf_9999")
results["8_missing_workflow_404"] = {
    "status": status,
    "expected": 404,
    "pass": status == 404,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 9. Custom Scenario path traversal attack attempt
status, body = request("POST", "/api/scenarios/custom", {
    "name": "../../etc/passwd",
    "data": {"malicious": True}
})
results["9_path_traversal_blocked"] = {
    "status": status,
    "expected_in": [400, 422],
    "pass": status in [400, 422],
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

# 10. Re-evaluate non-existent run
status, body = request("POST", "/api/runs/non_existent_run_4444/re-evaluate", {
    "evaluation_mode": "read_only_inquiry"
})
results["10_re_evaluate_missing_run_404"] = {
    "status": status,
    "expected": 404,
    "pass": status == 404,
    "detail": body.get("detail") if isinstance(body, dict) else str(body)
}

print(json.dumps(results, indent=2))

