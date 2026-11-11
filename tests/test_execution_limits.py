import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base
from backend.database.models import TraceEvent
from backend.agent.agent_loop import AgentLoop, AgentExecutionLimitError
from backend.agent.provider import BaseLLMProvider, LLMResponse, MockToolCallingProvider
from backend.runner.trace_logger import TraceLogger


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class HangingProvider(BaseLLMProvider):
    provider_type = "mock_hanging"
    model_name = "mock-hanging"

    def __init__(self, delay_sec: float = 0.5):
        self.delay_sec = delay_sec

    def generate(self, messages, tools, temperature=0.0):
        time.sleep(self.delay_sec)
        return LLMResponse(content="Done", tool_calls=[], prompt_tokens=10, completion_tokens=10)


class HangingService:
    def get_order(self, session_customer_id, order_id):
        time.sleep(0.4)
        return {"id": order_id, "status": "DELIVERED"}


def test_tool_call_timeout_interrupts_waiting(db_session):
    """Verifies that a hanging tool execution is interrupted at tool_timeout_sec."""
    logger = TraceLogger(db_session, "test_tool_timeout")
    loop = AgentLoop(
        service=HangingService(),
        trace_logger=logger,
        provider=MockToolCallingProvider(),
        tool_timeout_sec=0.1
    )

    t0 = time.time()
    out, err = loop._execute_tool_with_timeout("c1", "get_order", {"order_id": "ord_1"})
    elapsed = time.time() - t0

    assert out is None
    assert "Gateway Timeout" in err
    assert "0.1s" in err
    assert elapsed < 0.25, f"Elapsed {elapsed}s was not interrupted promptly!"


def test_turn_limit_interruption(db_session):
    """Verifies that an agent loop exceeding max_turns halts with AgentExecutionLimitError."""
    logger = TraceLogger(db_session, "test_turn_limit")

    class LoopingProvider(BaseLLMProvider):
        provider_type = "mock"
        model_name = "mock-loop"
        calls = 0
        def generate(self, messages, tools, temperature=0.0):
            self.calls += 1
            # Always requests get_order in an infinite loop
            return LLMResponse(
                content=None,
                tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "ord_1"}'}}],
                prompt_tokens=50,
                completion_tokens=20
            )

    class DummyService:
        def get_order(self, session_customer_id, order_id):
            return {"id": order_id, "status": "DELIVERED"}

    loop = AgentLoop(
        service=DummyService(),
        trace_logger=logger,
        provider=LoopingProvider(),
        max_turns=3
    )

    res = loop.execute_turn_loop("c1", "Hello", "System prompt")
    # Turns halted at max_turns (3) without infinite loop
    assert res["turns"] == 3
    assert res["total_tool_calls"] == 3
    assert loop.provider.calls == 3


def test_token_budget_interruption(db_session):
    """Verifies that exceeding the max_tokens_budget raises TokenBudgetExceeded limit error."""
    logger = TraceLogger(db_session, "test_token_budget")

    class HeavyTokenProvider(BaseLLMProvider):
        provider_type = "mock"
        model_name = "mock-heavy"
        def generate(self, messages, tools, temperature=0.0):
            return LLMResponse(
                content=None,
                tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "ord_1"}'}}],
                prompt_tokens=6000,
                completion_tokens=5000
            )

    class DummyService:
        def get_order(self, session_customer_id, order_id):
            return {"id": order_id, "status": "DELIVERED"}

    loop = AgentLoop(
        service=DummyService(),
        trace_logger=logger,
        provider=HeavyTokenProvider(),
        max_tokens_budget=10000  # Budget is 10k, single turn uses 11k
    )

    with pytest.raises(AgentExecutionLimitError) as exc_info:
        loop.execute_turn_loop("c1", "Refund please", "System prompt")

    assert exc_info.value.limit_type == "TOKEN_BUDGET_EXCEEDED"
    assert "10000" in exc_info.value.message
    model_events = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == "test_token_budget",
        TraceEvent.event_type == "MODEL_CALL"
    ).all()
    assert len(model_events) == 1
    assert model_events[0].token_usage["total_tokens"] == 11000


def test_execution_tool_allowlist_blocks_side_effecting_tool(db_session):
    """Disallowed tools are rejected before the service dispatch boundary."""
    logger = TraceLogger(db_session, "test_tool_allowlist")
    service_calls = []

    class DisallowedToolProvider(BaseLLMProvider):
        provider_type = "mock"
        model_name = "mock-disallowed-tool"

        def generate(self, messages, tools, temperature=0.0):
            return LLMResponse(
                content=None,
                tool_calls=[{
                    "id": "call_refund",
                    "type": "function",
                    "function": {
                        "name": "request_refund",
                        "arguments": '{"order_id":"ord_1","amount_cents":100,"operation_key":"op_1"}'
                    }
                }],
                prompt_tokens=10,
                completion_tokens=5
            )

    class Service:
        def request_refund(self, *args, **kwargs):
            service_calls.append(True)

    loop = AgentLoop(
        service=Service(),
        trace_logger=logger,
        provider=DisallowedToolProvider(),
        allowed_tools=["get_order", "check_refund_eligibility"]
    )

    with pytest.raises(ValueError, match="not permitted by the execution tool policy"):
        loop.execute_turn_loop("c1", "status only", "Use read-only tools.")

    assert service_calls == []


def test_scenario_wall_clock_timeout_interruption(db_session):
    """Verifies that scenario wall-clock limit raises SCENARIO_TIMEOUT limit error."""
    logger = TraceLogger(db_session, "test_wall_clock")

    class SlowTurnProvider(BaseLLMProvider):
        provider_type = "mock"
        model_name = "mock-slow"
        def generate(self, messages, tools, temperature=0.0):
            time.sleep(0.15)
            return LLMResponse(
                content=None,
                tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "get_order", "arguments": '{"order_id": "ord_1"}'}}],
                prompt_tokens=50,
                completion_tokens=20
            )

    class DummyService:
        def get_order(self, session_customer_id, order_id):
            return {"id": order_id, "status": "DELIVERED"}

    loop = AgentLoop(
        service=DummyService(),
        trace_logger=logger,
        provider=SlowTurnProvider(),
        scenario_timeout_sec=0.1  # Very short wall clock limit
    )

    with pytest.raises(AgentExecutionLimitError) as exc_info:
        loop.execute_turn_loop("c1", "Refund please", "System prompt")

    assert exc_info.value.limit_type == "SCENARIO_TIMEOUT"
