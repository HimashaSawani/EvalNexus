import asyncio
from unittest.mock import Mock
from backend import main

def test_standalone_mode_does_not_start_embedded_worker(monkeypatch):
    factory = Mock()
    monkeypatch.setenv("AWT_EMBEDDED_WORKER", "0")
    monkeypatch.setattr(main, "QueueWorker", factory)
    async def check():
        async with main.lifespan(main.app):
            factory.assert_not_called()
    asyncio.run(check())

def test_configured_key_is_not_claimed_verified(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-credential")
    db = Mock()
    db.query.return_value.filter.return_value.count.return_value = 0
    db.query.return_value.order_by.return_value.first.return_value = None
    status = main.get_system_settings(db)["credentials"]["GEMINI_API_KEY"]
    assert status["configured"]
    assert status["status"] == "Configured (not validated)"

def test_discovered_models_are_not_claimed_to_have_verified_tool_calling(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-credential")
    monkeypatch.setattr(main, "discover_available_gemini_models", lambda: ["discovered-model"])
    model = next(model for model in main.list_available_models() if model["id"] == "discovered-model")
    assert "not verified" in model["description"]

def test_timeout_evidence_persists_on_settlement():
    from backend.agent.agent_loop import AgentLoop
    from backend.agent.provider import MockToolCallingProvider
    import threading
    released = threading.Event()
    service = Mock()
    service.get_order.side_effect = lambda **kw: released.wait(2)
    logger = Mock()
    loop = AgentLoop(service, logger, MockToolCallingProvider(), tool_timeout_sec=0.01)
    try:
        output, error = loop._execute_tool_with_timeout("c1", "get_order", {"order_id":"o1"})
        assert output is None and "Gateway Timeout" in error
        assert loop.unresolved_tasks
        assert loop.pending_timeout_events
    finally:
        released.set()
        loop.settle_in_flight_tasks()
    assert not loop.pending_timeout_events
    assert any(c.kwargs.get("event_type") == "TOOL_TIMEOUT" for c in logger.log_event.call_args_list)

def test_queue_runner_saves_result_on_parent_run(tmp_path, monkeypatch):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from backend.database.connection import Base
    from backend.database.models import Run, QueueJob, ScenarioRun
    from backend import worker as module
    engine = create_engine("sqlite:///"+str(tmp_path / "queue.db"), connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(module, "SessionLocal", sessions)
    db = sessions()
    run = Run(id="parent",agent_version_id="agent_v2_improved",status="QUEUED",total_scenarios=1,
              execution_config={"max_turns":6,"tool_timeout_sec":0.9})
    job = QueueJob(id="job",run_id="parent",agent_version_id="agent_v2_improved",provider_type="mock",model_name="mock-deterministic-v1",
                   status="QUEUED",scenario_ids=["eligible_refund_scenario.json"])
    db.add_all([run,job]); db.commit()
    worker = module.QueueWorker()
    assert worker.claim_next_job(db)
    worker.execute_job("job")
    db.expire_all()
    assert db.get(Run,"parent").status == "COMPLETED"
    assert db.query(ScenarioRun).filter_by(run_id="parent").count() == 1
    assert db.query(Run).count() == 1
    assert db.get(QueueJob,"job").error_message is None
    db.close(); engine.dispose()


def test_comparison_rejects_different_execution_limits():
    from types import SimpleNamespace
    from backend import main
    def record(id, turns):
        return SimpleNamespace(id=id,provider_type="mock",model_name="mock-deterministic-v1",is_mock=1,
            execution_config={"max_turns":turns},scenario_runs=[],passed_scenarios=0,total_scenarios=0,
            agent_version_id="agent_v2_improved",status="COMPLETED")
    db=Mock()
    db.query.return_value.filter.return_value.first.side_effect=[record("a",6),record("b",3)]
    result=main.compare_runs("a","b",db)
    assert not result["is_compatible"]
    assert "Execution configuration mismatch" in result["config_diffs"]


def test_application_sqlite_uses_wal():
    from backend.database.connection import engine
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_late_final_model_response_cannot_pass_deadline():
    import time
    import pytest
    from types import SimpleNamespace
    from backend.agent.agent_loop import AgentLoop, AgentExecutionLimitError
    from backend.agent.provider import MockToolCallingProvider
    provider=MockToolCallingProvider()
    def slow_generate(**kwargs):
        time.sleep(0.04)
        return SimpleNamespace(content="Finished",tool_calls=[],total_tokens=0,prompt_tokens=0,completion_tokens=0)
    provider.generate=slow_generate
    loop=AgentLoop(Mock(),Mock(),provider,scenario_timeout_sec=0.01)
    with pytest.raises(AgentExecutionLimitError) as error:
        loop.execute_turn_loop("c1","refund","system")
    assert error.value.limit_type == "SCENARIO_TIMEOUT"


def test_background_trace_waits_for_owner_session():
    import threading
    from backend.runner.trace_logger import TraceLogger
    db=Mock()
    logger=TraceLogger(db,"thread-check")
    def emit():
        logger.log_event("TOOL_CALL",tool_name="get_order")
        logger.log_event("TOOL_CALL",tool_name="check_refund_eligibility")
    t=threading.Thread(target=emit)
    t.start();t.join()
    db.add.assert_not_called()
    assert not logger.events
    logger.flush_pending()
    assert db.add.call_count == 2
    assert [e["tool_name"] for e in logger.events] == ["get_order", "check_refund_eligibility"]
