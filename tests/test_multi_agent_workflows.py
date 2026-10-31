import pytest
from backend.workflows.models import (
    WorkflowDefinition,
    WorkflowStep,
    AgentRoleDefinition
)
from backend.workflows.runner import MultiAgentWorkflowRunner
from backend.agent.agent_loop import CancellationToken


def test_sequential_multi_agent_workflow():
    """
    Verifies Phase 1: Sequential Multi-Agent Workflow Evaluation.
    Pipeline: Research Agent -> Analysis Agent -> Reviewer/Synthesis Agent.
    """
    agents = [
        AgentRoleDefinition(
            agent_id="researcher",
            name="Research Specialist",
            role="Researcher",
            capabilities=["web_search", "document_retrieval"],
            system_prompt="You gather evidence and relevant facts.",
            tools=["web_search"],
            provider_type="mock"
        ),
        AgentRoleDefinition(
            agent_id="analyst",
            name="Data Analyst",
            role="Analyst",
            capabilities=["metric_calculation", "pattern_recognition"],
            system_prompt="You analyze facts and find trends.",
            tools=[],
            provider_type="mock"
        ),
        AgentRoleDefinition(
            agent_id="reviewer",
            name="Quality Reviewer",
            role="Reviewer",
            capabilities=["final_synthesis", "policy_audit"],
            system_prompt="You audit findings and synthesize final response.",
            tools=[],
            provider_type="mock"
        )
    ]

    steps = [
        WorkflowStep(
            step_id="step_research",
            name="Information Gathering",
            agent_id="researcher",
            input_template="Research topic: {context.topic}",
            expected_tools=["web_search"]
        ),
        WorkflowStep(
            step_id="step_analysis",
            name="Data Evaluation",
            agent_id="analyst",
            input_template="Analyze findings from research: {steps.step_research.output}",
            depends_on=["step_research"]
        ),
        WorkflowStep(
            step_id="step_review",
            name="Final Review & Synthesis",
            agent_id="reviewer",
            input_template="Review analysis and synthesize response: {steps.step_analysis.output}",
            depends_on=["step_analysis"]
        )
    ]

    wf_def = WorkflowDefinition(
        name="Sequential Analysis Pipeline",
        description="Three-stage multi-agent evaluation pipeline",
        agents=agents,
        steps=steps,
        initial_context={"topic": "Customer Return Anomaly"}
    )

    runner = MultiAgentWorkflowRunner(wf_def)
    result = runner.run_workflow()

    assert result.status == "PASSED"
    assert len(result.step_results) == 3
    assert len(result.handoff_events) == 2

    # Check handoff progression
    assert result.handoff_events[0].from_agent_id == "researcher"
    assert result.handoff_events[0].to_agent_id == "analyst"
    assert result.handoff_events[1].from_agent_id == "analyst"
    assert result.handoff_events[1].to_agent_id == "reviewer"

    # Evaluator check assertions
    checks = {c["check_name"]: c["status"] for c in result.checks}
    assert checks["WORKFLOW_COMPLETION"] == "PASSED"
    assert checks["CYCLE_PREVENTION"] == "PASSED"
    assert checks["MULTI_AGENT_COLLABORATION"] == "PASSED"


def test_bounded_parallel_agent_execution():
    """
    Verifies that steps sharing a parallel_group execute concurrently
    and their outputs are properly synthesized by a downstream dependent step.
    """
    agents = [
        AgentRoleDefinition(
            agent_id="agent_fast",
            name="Fast Analyst",
            role="SpeedAnalyst",
            system_prompt="Fast analysis",
            provider_type="mock"
        ),
        AgentRoleDefinition(
            agent_id="agent_thorough",
            name="Deep Analyst",
            role="DeepAnalyst",
            system_prompt="Deep analysis",
            provider_type="mock"
        ),
        AgentRoleDefinition(
            agent_id="agent_lead",
            name="Lead Synthesizer",
            role="Lead",
            system_prompt="Combines reports",
            provider_type="mock"
        )
    ]

    steps = [
        WorkflowStep(
            step_id="step_fast",
            name="Quick Scan",
            agent_id="agent_fast",
            input_template="Quick scan for {context.target}",
            parallel_group="parallel_analysis"
        ),
        WorkflowStep(
            step_id="step_deep",
            name="Deep Investigation",
            agent_id="agent_thorough",
            input_template="Deep investigation for {context.target}",
            parallel_group="parallel_analysis"
        ),
        WorkflowStep(
            step_id="step_merge",
            name="Executive Summary",
            agent_id="agent_lead",
            input_template="Synthesize: {step_fast} and {step_deep}",
            depends_on=["step_fast", "step_deep"]
        )
    ]

    wf_def = WorkflowDefinition(
        name="Parallel Branching Evaluation",
        agents=agents,
        steps=steps,
        initial_context={"target": "Supply Chain Bottleneck"}
    )

    runner = MultiAgentWorkflowRunner(wf_def)
    result = runner.run_workflow()

    assert result.status == "PASSED"
    assert len(result.step_results) == 3
    assert "Supply Chain Bottleneck" in result.final_output


def test_workflow_cycle_detection_and_safeguards():
    """
    Verifies that cyclical handoffs or unresolvable dependencies are intercepted
    and classified as CYCLE_DETECTED before unbounded recursion occurs.
    """
    agents = [
        AgentRoleDefinition(agent_id="a1", name="Agent A", role="LoopA", provider_type="mock"),
        AgentRoleDefinition(agent_id="a2", name="Agent B", role="LoopB", provider_type="mock")
    ]

    # Mutual dependency deadlock
    steps = [
        WorkflowStep(step_id="s1", name="Step 1", agent_id="a1", input_template="Go", depends_on=["s2"]),
        WorkflowStep(step_id="s2", name="Step 2", agent_id="a2", input_template="Go", depends_on=["s1"])
    ]

    wf_def = WorkflowDefinition(
        name="Deadlock Test",
        agents=agents,
        steps=steps
    )

    runner = MultiAgentWorkflowRunner(wf_def)
    result = runner.run_workflow()

    assert result.status == "CYCLE_DETECTED"
    assert "deadlock" in result.error_message.lower()


def test_workflow_cancellation():
    """Verifies that an active CancellationToken halts workflow execution cleanly."""
    agents = [
        AgentRoleDefinition(agent_id="agent_1", name="Agent 1", role="Worker", provider_type="mock")
    ]
    steps = [
        WorkflowStep(step_id="step_1", name="Step 1", agent_id="agent_1", input_template="Run")
    ]

    token = CancellationToken()
    token.cancel()

    wf_def = WorkflowDefinition(name="Cancel Test", agents=agents, steps=steps)
    runner = MultiAgentWorkflowRunner(wf_def, cancellation_token=token)
    result = runner.run_workflow()

    assert result.status == "CANCELLED"
    assert "cancelled" in result.error_message.lower()


def test_workflow_schema_validation_rejections():
    """Verifies that invalid configurations (duplicate agents, unknown dependencies) are rejected."""
    # 1. Duplicate agent IDs
    with pytest.raises(ValueError, match="Agent IDs must be unique"):
        WorkflowDefinition(
            name="Duplicate Agent",
            agents=[
                AgentRoleDefinition(agent_id="dup", name="One", role="R1"),
                AgentRoleDefinition(agent_id="dup", name="Two", role="R2")
            ],
            steps=[
                WorkflowStep(step_id="s1", name="S1", agent_id="dup", input_template="X")
            ]
        )

    # 2. Dependency on non-existent step
    with pytest.raises(ValueError, match="depends on non-existent step"):
        WorkflowDefinition(
            name="Bad Dependency",
            agents=[AgentRoleDefinition(agent_id="a1", name="A", role="R")],
            steps=[
                WorkflowStep(step_id="s1", name="S1", agent_id="a1", input_template="X", depends_on=["ghost_step"])
            ]
        )
