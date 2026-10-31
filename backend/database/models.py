import datetime
from typing import Optional, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    UniqueConstraint,
    Index
)
from sqlalchemy.orm import relationship
from backend.database.connection import Base


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)



# ---------------------------------------------------------
# Testing Platform Models
# ---------------------------------------------------------

class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=False)
    model_name = Column(String(64), nullable=False, default="gemini-1.5-flash")
    temperature = Column(Integer, default=0)  # stored as integer percentage or float
    tool_schema_version = Column(String(32), default="v1")
    created_at = Column(DateTime, default=utc_now)

    runs = relationship("Run", back_populates="agent_version")


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)  # NORMAL, ELIGIBILITY, OWNERSHIP, FAULT, DUPLICATE
    description = Column(Text, nullable=True)
    fixed_clock = Column(DateTime, nullable=False)
    initial_data = Column(JSON, nullable=False)       # { customer: {...}, orders: [...] }
    customer_messages = Column(JSON, nullable=False)  # list of prompts / messages
    fault_configs = Column(JSON, nullable=True)       # fault injection rules
    expected_checks = Column(JSON, nullable=False)     # { ownership: PASS, eligibility: PASS, ... }
    created_at = Column(DateTime, default=utc_now)

    scenario_runs = relationship("ScenarioRun", back_populates="scenario_version")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(64), primary_key=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id"), nullable=False)
    provider_type = Column(String(32), default="mock")  # mock, openai, gemini
    model_name = Column(String(64), default="mock-deterministic-v1")
    is_mock = Column(Integer, default=1)  # 1 for mock, 0 for real model
    execution_config = Column(JSON, nullable=True)  # max_turns, limits, timeouts
    status = Column(String(32), default="QUEUED")  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    total_scenarios = Column(Integer, default=0)
    passed_scenarios = Column(Integer, default=0)
    failed_scenarios = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    agent_version = relationship("AgentVersion", back_populates="runs")
    scenario_runs = relationship("ScenarioRun", back_populates="run", cascade="all, delete-orphan")
    queue_job = relationship("QueueJob", uselist=False, back_populates="run", cascade="all, delete-orphan")


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("runs.id"), nullable=False)
    scenario_version_id = Column(String(64), ForeignKey("scenario_versions.id"), nullable=False)
    status = Column(String(32), default="RUNNING")  # RUNNING, PASSED, FAILED, ERROR
    started_at = Column(DateTime, default=utc_now)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, default=0)

    run = relationship("Run", back_populates="scenario_runs")
    scenario_version = relationship("ScenarioVersion", back_populates="scenario_runs")
    trace_events = relationship("TraceEvent", back_populates="scenario_run", cascade="all, delete-orphan")
    check_results = relationship("CheckResult", back_populates="scenario_run", cascade="all, delete-orphan")


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id = Column(String(64), primary_key=True)
    scenario_run_id = Column(String(64), ForeignKey("scenario_runs.id"), nullable=False)
    seq_num = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=utc_now)
    duration_ms = Column(Integer, default=0)
    event_type = Column(String(64), nullable=False)  # USER_MESSAGE, MODEL_CALL, TOOL_CALL, TOOL_RESULT, FAULT, ERROR
    tool_name = Column(String(64), nullable=True)
    tool_arguments = Column(JSON, nullable=True)
    tool_result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    token_usage = Column(JSON, nullable=True)  # { prompt_tokens: ..., completion_tokens: ..., total: ... }
    cost_estimate = Column(Integer, default=0)  # minor units micro-cents

    scenario_run = relationship("ScenarioRun", back_populates="trace_events")

    __table_args__ = (
        Index("ix_trace_run_seq", "scenario_run_id", "seq_num"),
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id = Column(String(64), primary_key=True)
    scenario_run_id = Column(String(64), ForeignKey("scenario_runs.id"), nullable=False)
    check_name = Column(String(64), nullable=False)  # OWNERSHIP, ELIGIBILITY, DUPLICATE, STATE, COMPLETION
    status = Column(String(32), nullable=False)       # PASSED, FAILED, NOT_APPLICABLE
    message = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=True)

    scenario_run = relationship("ScenarioRun", back_populates="check_results")


# ---------------------------------------------------------
# Business Simulation Models (Scoped per scenario_run_id)
# ---------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"

    id = Column(String(64), primary_key=True)
    scenario_run_id = Column(String(64), ForeignKey("scenario_runs.id"), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=utc_now)


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(64), primary_key=True)
    scenario_run_id = Column(String(64), ForeignKey("scenario_runs.id"), primary_key=True, index=True)
    customer_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)  # DELIVERED, CANCELLED, PENDING, UNKNOWN, REFUNDED
    total_amount_cents = Column(Integer, nullable=False)
    currency = Column(String(8), default="USD")
    delivery_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)


class RefundRequest(Base):
    __tablename__ = "refund_requests"

    id = Column(String(64), primary_key=True)
    scenario_run_id = Column(String(64), ForeignKey("scenario_runs.id"), primary_key=True, index=True)
    order_id = Column(String(64), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="REFUND_REQUESTED")  # REFUND_REQUESTED, MONEY_RETURNED, REJECTED
    operation_key = Column(String(128), nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        # Constraint 1: Prevent duplicate refunds for the same order within a scenario run
        UniqueConstraint("order_id", "scenario_run_id", name="uq_order_scenario_refund"),
        # Constraint 2: Idempotent operation key protection
        UniqueConstraint("operation_key", "scenario_run_id", name="uq_opkey_scenario_refund"),
    )


# ---------------------------------------------------------
# Persistent Background Queue Model
# ---------------------------------------------------------

class QueueJob(Base):
    __tablename__ = "queue_jobs"

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("runs.id"), nullable=False, index=True)
    status = Column(String(32), default="QUEUED", index=True)  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id"), nullable=False)
    provider_type = Column(String(32), default="mock")  # mock, gemini, etc.
    model_name = Column(String(64), nullable=False)
    scenario_ids = Column(JSON, nullable=False)  # List[str] of scenario files or IDs
    execution_config = Column(JSON, nullable=True)
    is_paid = Column(Integer, default=0)  # 1 for paid execution, 0 for mock
    retry_count = Column(Integer, default=0)
    worker_id = Column(String(64), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    run = relationship("Run", back_populates="queue_job")


# ---------------------------------------------------------
# Custom Agent and Custom Scenario Models (Stage 2 & 3)
# ---------------------------------------------------------

class CustomAgent(Base):
    __tablename__ = "custom_agents"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    endpoint_url = Column(String(512), nullable=False)
    auth_header_name = Column(String(64), default="Authorization")
    auth_token_masked = Column(String(64), nullable=True)
    auth_token_secret = Column(Text, nullable=True)
    timeout_sec = Column(Integer, default=15)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class CustomScenario(Base):
    __tablename__ = "custom_scenarios"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), default="CUSTOM")
    version = Column(Integer, default=1)
    scenario_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)



