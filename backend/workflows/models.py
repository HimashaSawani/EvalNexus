import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator


class AgentRoleDefinition(BaseModel):
    """Defines an individual agent's role, persona, and execution parameters in a workflow."""
    agent_id: str = Field(..., description="Unique identifier for the agent in this workflow")
    name: str = Field(..., description="Human-readable name")
    role: str = Field(..., description="Role title (e.g. Researcher, Analyst, Reviewer, Synthesizer)")
    capabilities: List[str] = Field(default_factory=list, description="Declared capabilities")
    system_prompt: str = Field(default="", description="Base prompt instructions for this role")
    provider_type: str = Field(default="mock", description="Provider engine: mock, custom_http, gemini, openai")
    model_name: Optional[str] = Field(default="mock-deterministic-v1")
    endpoint_url: Optional[str] = Field(default=None, description="Custom agent endpoint URL if custom_http")
    tools: List[str] = Field(default_factory=list, description="Tool names allowed for this agent")
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)


class WorkflowStep(BaseModel):
    """A discrete task step in a multi-agent workflow."""
    step_id: str = Field(..., description="Unique step ID within the workflow")
    name: str = Field(..., description="Human-readable step name")
    agent_id: str = Field(..., description="ID of the agent role executing this step")
    input_template: str = Field(..., description="Instruction template; supports {context.variable} substitutions")
    depends_on: List[str] = Field(default_factory=list, description="Step IDs that must complete before this step")
    parallel_group: Optional[str] = Field(default=None, description="Steps sharing this group execute concurrently")
    timeout_sec: float = Field(default=15.0, ge=1.0, le=120.0)
    expected_tools: List[str] = Field(default_factory=list, description="Tools expected to be called during this step")
    handoff_target: Optional[str] = Field(default=None, description="Target step or agent for direct handoff")
    evaluator_criteria: Dict[str, Any] = Field(default_factory=dict, description="Step-level evaluation criteria")


class WorkflowDefinition(BaseModel):
    """Complete specification of a multi-agent evaluation workflow."""
    workflow_id: str = Field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:8]}")
    name: str = Field(..., min_length=2, max_length=128)
    description: Optional[str] = Field(default="")
    agents: List[AgentRoleDefinition] = Field(..., min_length=1)
    steps: List[WorkflowStep] = Field(..., min_length=1)
    max_handoffs: int = Field(default=10, ge=1, le=50, description="Cycle prevention ceiling")
    max_total_turns: int = Field(default=25, ge=1, le=100)
    workflow_timeout_sec: float = Field(default=60.0, ge=5.0, le=300.0)
    initial_context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("agents")
    @classmethod
    def validate_unique_agent_ids(cls, v: List[AgentRoleDefinition]) -> List[AgentRoleDefinition]:
        ids = [a.agent_id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Agent IDs must be unique across the workflow: {ids}")
        return v

    @field_validator("steps")
    @classmethod
    def validate_steps_and_dependencies(cls, v: List[WorkflowStep]) -> List[WorkflowStep]:
        step_ids = [s.step_id for s in v]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError(f"Step IDs must be unique across the workflow: {step_ids}")
        
        # Verify dependency existence
        for s in v:
            for dep in s.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{s.step_id}' depends on non-existent step '{dep}'")
                if dep == s.step_id:
                    raise ValueError(f"Step '{s.step_id}' cannot depend on itself")
        return v


class StepExecutionResult(BaseModel):
    """Detailed record of a single step execution by an agent."""
    step_id: str
    agent_id: str
    status: str  # PASSED, FAILED, TIMEOUT, SKIPPED, ERROR
    input_text: str
    output_text: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    state_updates: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    error_message: Optional[str] = None
    evaluator_checks: List[Dict[str, Any]] = Field(default_factory=list)


class HandoffEvent(BaseModel):
    """Auditable log of an agent-to-agent delegation/handoff."""
    handoff_id: str = Field(default_factory=lambda: f"ho_{uuid.uuid4().hex[:6]}")
    from_agent_id: str
    to_agent_id: str
    from_step_id: str
    to_step_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    reason: str = "workflow_transition"
    timestamp: str = ""


class WorkflowRunResult(BaseModel):
    """Aggregate result of executing a complete multi-agent workflow."""
    workflow_run_id: str
    workflow_id: str
    workflow_name: str
    status: str  # PASSED, FAILED, CANCELLED, TIMEOUT, CYCLE_DETECTED, ERROR
    duration_ms: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    step_results: List[StepExecutionResult] = Field(default_factory=list)
    handoff_events: List[HandoffEvent] = Field(default_factory=list)
    final_output: str = ""
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    checks: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
