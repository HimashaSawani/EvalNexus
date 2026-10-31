import os
import pytest
from backend.agent.provider import calculate_cost_microcents
from backend.runner.agent_runner import AgentWindTunnelRunner
from backend.database.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_cost_calculation_semantics():
    """Validates that mock runs cost $0.00 while paid models compute deterministic microcents."""
    # Mock simulator
    assert calculate_cost_microcents("mock", "mock-deterministic-v1", 1000, 500) == 0

    # Gemini Flash Lite (750 microcents/prompt token, 3000 microcents/completion token)
    gemini_cost = calculate_cost_microcents("gemini", "gemini-flash-lite-latest", 1000, 200)
    assert gemini_cost == (1000 * 750) + (200 * 3000)
    assert gemini_cost > 0

    # GPT-4o-mini
    openai_cost = calculate_cost_microcents("openai", "gpt-4o-mini", 1000, 200)
    assert openai_cost == (1000 * 1500) + (200 * 6000)
    assert openai_cost > gemini_cost


def test_failure_classification_behavioral_vs_provider():
    """Validates that runner distinguishes behavioral failure from provider/operational errors."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        runner = AgentWindTunnelRunner(session, provider_type="mock")
        # Run eligible scenario
        with open("scenarios/eligible_refund_scenario.json", "r", encoding="utf-8") as f:
            import json
            data = json.load(f)

        res = runner.run_agent_scenario(data, agent_version_id="agent_v2_improved")
        assert res["status"] == "PASSED"
        assert res["failure_category"] is None
        assert res["is_mock"] is True
        assert res["cost_microcents"] == 0
    finally:
        session.close()


def test_comparison_statistical_confidence():
    """Ensures A/B comparison warns when sample size N < 10."""
    from backend.database.models import Run, utc_now
    from backend.database.connection import SessionLocal

    db = SessionLocal()
    try:
        now = utc_now()
        r1 = Run(
            id="run_stat_a",
            agent_version_id="agent_v1_baseline",
            provider_type="mock",
            model_name="mock-deterministic-v1",
            is_mock=1,
            status="COMPLETED",
            total_scenarios=3,
            passed_scenarios=2,
            execution_config={"max_turns": 6},
            created_at=now
        )
        r2 = Run(
            id="run_stat_b",
            agent_version_id="agent_v2_improved",
            provider_type="mock",
            model_name="mock-deterministic-v1",
            is_mock=1,
            status="COMPLETED",
            total_scenarios=3,
            passed_scenarios=3,
            execution_config={"max_turns": 6},
            created_at=now
        )
        db.add(r1)
        db.add(r2)
        db.commit()

        res = client.get("/api/comparisons?run_a=run_stat_a&run_b=run_stat_b")
        assert res.status_code == 200
        data = res.json()
        assert "INSUFFICIENT_SAMPLE_SIZE" in data["statistical_confidence"]
        assert data["pass_rate_delta"] > 0
    finally:
        db.close()

