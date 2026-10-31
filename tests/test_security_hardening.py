import os
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.security import RateLimiter, PaidProviderGuard, sanitize_secret

client = TestClient(app)


def test_public_endpoints_accessible_without_auth():
    """Health and dashboard endpoints must remain accessible for probes and browser loading."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"

    r_ready = client.get("/readyz")
    assert r_ready.status_code == 200

    r_root = client.get("/")
    assert r_root.status_code == 200


def test_local_dev_mode_permits_anonymous_access():
    """In local development mode (no AWT_REQUIRE_AUTH), API endpoints are usable out-of-the-box."""
    os.environ["AWT_REQUIRE_AUTH"] = "0"
    r = client.get("/api/agent-versions")
    assert r.status_code == 200


def test_authentication_enforcement_when_configured():
    """When AWT_REQUIRE_AUTH=1, requests without valid credentials must be rejected with 401."""
    os.environ["AWT_REQUIRE_AUTH"] = "1"
    os.environ["AWT_API_KEY"] = "awt-secret-test-token-456"

    try:
        # 1. Missing credentials -> 401
        r_unauth = client.get("/api/settings")
        assert r_unauth.status_code == 401
        assert "Unauthorized" in r_unauth.json()["detail"]

        # 2. Invalid credentials -> 401
        r_invalid = client.get(
            "/api/settings",
            headers={"Authorization": "Bearer wrong-key"}
        )
        assert r_invalid.status_code == 401

        # 3. Valid Bearer Token -> 200
        r_bearer = client.get(
            "/api/settings",
            headers={"Authorization": "Bearer awt-secret-test-token-456"}
        )
        assert r_bearer.status_code == 200

        # 4. Valid X-API-Key Header -> 200
        r_header = client.get(
            "/api/settings",
            headers={"X-API-Key": "awt-secret-test-token-456"}
        )
        assert r_header.status_code == 200

    finally:
        # Restore local dev mode
        os.environ["AWT_REQUIRE_AUTH"] = "0"
        os.environ.pop("AWT_API_KEY", None)


def test_rate_limiter_unit():
    """Verifies that RateLimiter correctly enforces sliding window limits."""
    limiter = RateLimiter(requests_per_minute=5)
    client_ip = "192.168.1.100"

    for _ in range(5):
        assert limiter.check(client_ip) is True

    # 6th request within window must be rejected
    assert limiter.check(client_ip) is False


def test_paid_provider_guard_limits():
    """Verifies concurrency and token budget constraints on paid providers."""
    guard = PaidProviderGuard(max_concurrent_paid=1, max_tokens_budget_per_run=20000, max_paid_queue_depth=2)

    # Mock provider never throttled
    guard.check_and_acquire("mock", queue_depth_paid=100)
    guard.release("mock")

    # First paid provider acquisition succeeds
    guard.check_and_acquire("gemini", queue_depth_paid=0)

    # Second concurrent acquisition rejected
    with pytest.raises(Exception) as excinfo:
        guard.check_and_acquire("gemini", queue_depth_paid=1)
    assert excinfo.value.status_code == 429

    guard.release("gemini")

    # Queue depth limit check
    with pytest.raises(Exception) as excinfo_queue:
        guard.check_and_acquire("gemini", queue_depth_paid=2)
    assert excinfo_queue.value.status_code == 429

    # Budget capping
    capped = guard.validate_execution_budget({"max_tokens_budget": 50000})
    assert capped["max_tokens_budget"] == 20000


def test_credential_sanitization():
    """Ensures secret keys are masked from exception messages and strings."""
    secret = "AIzaSySecretGoogleKey1234567890123"
    leaky_msg = f"Failed to connect to Google with key {secret} in url"
    sanitized = sanitize_secret(leaky_msg, secret)
    assert secret not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


def test_secrets_never_leak_in_api_responses():
    """Confirms credentials and external agent tokens are never returned in cleartext via API."""
    os.environ["GEMINI_API_KEY"] = "AIzaSySecretTestKey999"
    try:
        r = client.get("/api/settings")
        assert r.status_code == 200
        content = r.text
        assert "AIzaSySecretTestKey999" not in content

        # Register custom agent with secret token
        r_agent = client.post("/api/custom-agents", json={
            "name": "Secret Leak Test Agent",
            "endpoint_url": "https://api.example.com/agent",
            "auth_token": "super_secret_bearer_token_12345"
        })
        assert r_agent.status_code == 200
        agent_data = r_agent.json()
        assert "super_secret_bearer_token_12345" not in r_agent.text
        assert "super_secret_bearer_token_12345" not in agent_data.get("auth_token_masked", "")
    finally:
        os.environ.pop("GEMINI_API_KEY", None)


def test_multi_process_paid_concurrency_db_backed():
    """
    Verifies that QueueWorker concurrency guard uses the database to limit concurrent paid jobs,
    ensuring multi-process worker pools cannot exceed AWT_MAX_CONCURRENT_PAID_JOBS.
    """
    import uuid
    from backend.database.connection import SessionLocal
    from backend.database.models import QueueJob, Run, AgentVersion, utc_now
    from backend.worker import QueueWorker

    db = SessionLocal()
    try:
        if not db.query(AgentVersion).filter(AgentVersion.id == "sec_agent").first():
            db.add(AgentVersion(id="sec_agent", name="Security Agent", system_prompt="Test"))
            db.commit()

        # Clear or cancel any existing QUEUED jobs to ensure deterministic FIFO testing
        db.query(QueueJob).filter(QueueJob.status == "QUEUED").update({"status": "CANCELLED"})
        db.commit()

        # Job 1: Paid job already RUNNING
        run_1_id = f"r_run_{uuid.uuid4().hex[:6]}"
        job_1_id = f"j_run_{uuid.uuid4().hex[:6]}"
        db.add(Run(id=run_1_id, agent_version_id="sec_agent", status="RUNNING", provider_type="gemini", is_mock=0))
        db.add(QueueJob(id=job_1_id, run_id=run_1_id, status="RUNNING", agent_version_id="sec_agent", provider_type="gemini", model_name="gemini-flash-lite", scenario_ids=["s1"], is_paid=1, heartbeat_at=utc_now()))

        # Job 2: Second paid job in QUEUED status
        run_2_id = f"r_queue_{uuid.uuid4().hex[:6]}"
        job_2_id = f"j_queue_{uuid.uuid4().hex[:6]}"
        db.add(Run(id=run_2_id, agent_version_id="sec_agent", status="QUEUED", provider_type="gemini", is_mock=0))
        db.add(QueueJob(id=job_2_id, run_id=run_2_id, status="QUEUED", agent_version_id="sec_agent", provider_type="gemini", model_name="gemini-flash-lite", scenario_ids=["s2"], is_paid=1))

        # Job 3: Non-paid (mock) job in QUEUED status
        run_3_id = f"r_mock_{uuid.uuid4().hex[:6]}"
        job_3_id = f"j_mock_{uuid.uuid4().hex[:6]}"
        db.add(Run(id=run_3_id, agent_version_id="sec_agent", status="QUEUED", provider_type="mock", is_mock=1))
        db.add(QueueJob(id=job_3_id, run_id=run_3_id, status="QUEUED", agent_version_id="sec_agent", provider_type="mock", model_name="mock-model", scenario_ids=["s3"], is_paid=0))
        db.commit()

        # With AWT_MAX_CONCURRENT_PAID_JOBS=1, second worker must skip paid job_2 and claim non-paid job_3!
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("AWT_MAX_CONCURRENT_PAID_JOBS", "1")
            worker2 = QueueWorker(worker_id="worker_process_beta")
            claimed = worker2.claim_next_job(db)

            assert claimed is not None
            # Must claim non-paid job_3, not paid job_2!
            assert claimed.id == job_3_id
            assert claimed.is_paid == 0
    finally:
        db.query(QueueJob).filter(QueueJob.id.in_([job_1_id, job_2_id, job_3_id])).delete(synchronize_session=False)
        db.query(Run).filter(Run.id.in_([run_1_id, run_2_id, run_3_id])).delete(synchronize_session=False)
        db.commit()
        db.close()


