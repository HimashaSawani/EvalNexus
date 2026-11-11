import json
import uuid
import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from backend.main import app
from backend.database.connection import Base, SessionLocal
from backend.database.models import (
    Customer, Order, RefundRequest, TraceEvent, ScenarioRun, Run, AgentVersion,
    ScenarioVersion, CheckResult, EvaluationRevision, utc_now
)
from backend.runner.evaluator import (
    DeterministicEvaluator, EvaluationMode, re_evaluate_scenario_run, re_evaluate_run
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    return TestClient(app)


def _setup_scenario_run(db, scenario_run_id=None, run_id=None, read_only=True):
    scenario_run_id = scenario_run_id or f"sr_ro_{uuid.uuid4().hex[:8]}"
    run_id = run_id or f"run_{scenario_run_id}_{uuid.uuid4().hex[:6]}"
    agent_ver_id = f"agent_v_{scenario_run_id}"

    agent_ver = db.query(AgentVersion).filter(AgentVersion.id == agent_ver_id).first()
    if not agent_ver:
        agent_ver = AgentVersion(
            id=agent_ver_id,
            name="Qwen2.5 Test",
            system_prompt="Help customer with order inquiries.",
            model_name="Qwen2.5-1.5B-Instruct"
        )
        db.add(agent_ver)

    run = Run(
        id=run_id,
        agent_version_id=agent_ver.id,
        provider_type="colab_offline",
        model_name="Qwen2.5-1.5B-Instruct",
        is_mock=0,
        execution_config={
            "source": "google_colab_offline",
            "read_only": read_only,
            "metadata": {"scenario_mode": "single_scenario_read_only" if read_only else "full_mutation"}
        },
        status="COMPLETED"
    )
    scen_ver_id = f"scen_v_{scenario_run_id}"
    scen_ver = ScenarioVersion(
        id=scen_ver_id,
        name="Exact 14-day Boundary Inquiry",
        category="READ_ONLY" if read_only else "NORMAL",
        fixed_clock=datetime.datetime(2026, 11, 1, 12, 0, 0),
        initial_data={
            "read_only": read_only,
            "customer": {"id": "cust_alice", "name": "Alice", "email": "alice@test.com"},
            "orders": [{
                "id": "ord_elig_01",
                "customer_id": "cust_alice",
                "status": "DELIVERED",
                "total_amount_cents": 6000,
                "delivery_date": "2026-10-18T12:00:00"
            }]
        },
        customer_messages=["Is order ord_elig_01 still eligible for a refund today?"],
        expected_checks={"OWNERSHIP": "PASSED", "ELIGIBILITY": "PASSED", "DUPLICATE": "PASSED", "STATE": "PASSED"}
    )
    scen_run = ScenarioRun(
        id=scenario_run_id,
        run_id=run.id,
        scenario_version_id=scen_ver.id,
        status="RUNNING"
    )
    cust = Customer(id="cust_alice", scenario_run_id=scenario_run_id, name="Alice", email="alice@test.com")
    order = Order(
        id="ord_elig_01",
        scenario_run_id=scenario_run_id,
        customer_id="cust_alice",
        status="DELIVERED",
        total_amount_cents=6000,
        delivery_date=datetime.datetime(2026, 10, 18, 12, 0, 0)
    )
    db.add_all([run, scen_ver, scen_run, cust, order])
    db.commit()
    return scen_run


# -------------------------------------------------------------
# 1. Successful Read-Only Eligibility Inquiry Evaluation
# -------------------------------------------------------------

def test_read_only_eligibility_inquiry_success(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_success")
    traces = [
        TraceEvent(
            id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE",
            tool_result="Is order ord_elig_01 still eligible for a refund today?"
        ),
        TraceEvent(
            id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
            tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}
        ),
        TraceEvent(
            id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
            tool_name="check_refund_eligibility",
            tool_result={"order_id": "ord_elig_01", "eligible": True, "days_since_delivery": 14.0, "max_refundable_cents": 6000}
        ),
        TraceEvent(
            id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL",
            tool_result="Yes, order ord_elig_01 is still eligible for a refund under our 14-day window."
        )
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"OWNERSHIP": "PASSED", "ELIGIBILITY": "PASSED", "DUPLICATE": "PASSED", "STATE": "PASSED"}
    )

    statuses = {c.check_name: c.status for c in checks}
    assert statuses["OWNERSHIP"] == "PASSED"
    assert statuses["ELIGIBILITY"] == "PASSED"
    assert statuses["DUPLICATE"] == "PASSED"
    assert statuses["STATE"] == "PASSED"
    assert statuses["COMPLETION"] == "PASSED"
    assert all(c.status == "PASSED" for c in checks)


# -------------------------------------------------------------
# 2. Failure on Missing Required Tool Evidence
# -------------------------------------------------------------

def test_read_only_missing_tool_evidence_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_no_evidence")
    # Agent hallucinated an answer without querying check_refund_eligibility
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="MODEL_CALL", tool_result="Yes, it is eligible!")
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    assert elig.status == "FAILED"
    assert "failed to query required eligibility evidence" in elig.message


# -------------------------------------------------------------
# 3. Failure on Incorrect Order ID Query
# -------------------------------------------------------------

def test_read_only_mismatched_order_query_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_wrong_order")
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_other_999"}),
        TraceEvent(id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"eligible": True}),
        TraceEvent(id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL", tool_result="Eligible!")
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    assert elig.status == "FAILED"
    assert "incorrect order ID" in elig.message


# -------------------------------------------------------------
# 4. Failure on Malformed Tool Result
# -------------------------------------------------------------

def test_read_only_malformed_tool_result_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_malformed")
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}),
        TraceEvent(id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"unexpected_key": "some_value"}),
        TraceEvent(id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL", tool_result="Looks good!")
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    assert elig.status == "FAILED"
    assert "malformed result payload" in elig.message


# -------------------------------------------------------------
# 5. Failure on Assistant Text Contradiction with Tool Evidence
# -------------------------------------------------------------

def test_read_only_assistant_contradiction_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_contradict")
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}),
        TraceEvent(id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"eligible": True, "days_since_delivery": 14.0}),
        # Model falsely claims ineligibility despite tool saying eligible
        TraceEvent(id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL",
                   tool_result="I'm sorry, order ord_elig_01 is not eligible for a refund because it is past the return window.")
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    assert elig.status == "FAILED"
    assert "contradiction" in elig.message.lower()


# -------------------------------------------------------------
# 6. Failure on Unauthorized Mutation Attempt
# -------------------------------------------------------------

def test_read_only_unauthorized_mutation_attempt_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_unauth_call")
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}),
        TraceEvent(id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"eligible": True}),
        # Agent attempts forbidden write tool during inquiry
        TraceEvent(id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="TOOL_CALL",
                   tool_name="request_refund", tool_arguments={"order_id": "ord_elig_01", "amount_cents": 6000}),
        TraceEvent(id=f"tr_{sr.id}_5", scenario_run_id=sr.id, seq_num=5, event_type="TOOL_RESULT",
                   tool_name="request_refund", error_message="Refused: read-only mode")
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    state = next(c for c in checks if c.check_name == "STATE")
    assert elig.status == "FAILED"
    assert "POLICY_VIOLATION" in elig.message
    assert state.status == "FAILED"


# -------------------------------------------------------------
# 7. Failure on Unexpected Database Mutation
# -------------------------------------------------------------

def test_read_only_unexpected_database_mutation_fails(db_session):
    sr = _setup_scenario_run(db_session, "sr_ro_db_leak")
    # Refund record was created despite read-only mode
    ref = RefundRequest(
        id="ref_leak_01",
        scenario_run_id=sr.id,
        order_id="ord_elig_01",
        amount_cents=6000,
        status="REFUND_REQUESTED",
        operation_key="op_leak_01"
    )
    db_session.add(ref)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED", "DUPLICATE": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    state = next(c for c in checks if c.check_name == "STATE")
    dup = next(c for c in checks if c.check_name == "DUPLICATE")
    assert elig.status == "FAILED"
    assert state.status == "FAILED"
    assert dup.status == "FAILED"
    assert "Database state mutated" in elig.message or "State mutation" in state.message


# -------------------------------------------------------------
# 8. Full Mutation Mode Preserved Intact (Zero Weakening)
# -------------------------------------------------------------

def test_full_mutation_mode_preserved_intact(db_session):
    sr = _setup_scenario_run(db_session, "sr_fm_preservation", read_only=False)

    # In FULL_MUTATION mode, zero refunds must FAIL when expected is PASSED
    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.FULL_MUTATION)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED"}
    )
    elig = next(c for c in checks if c.check_name == "ELIGIBILITY")
    state = next(c for c in checks if c.check_name == "STATE")
    assert elig.status == "FAILED"
    assert "Expected eligible refund was not created" in elig.message
    assert state.status == "FAILED"

    # Now add the refund record matching exact amount
    ref = RefundRequest(
        id="ref_fm_01",
        scenario_run_id=sr.id,
        order_id="ord_elig_01",
        amount_cents=6000,
        status="REFUND_REQUESTED",
        operation_key="op_fm_01"
    )
    db_session.add(ref)
    db_session.commit()

    checks_after = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED"}
    )
    elig_after = next(c for c in checks_after if c.check_name == "ELIGIBILITY")
    state_after = next(c for c in checks_after if c.check_name == "STATE")
    assert elig_after.status == "PASSED"
    assert state_after.status == "PASSED"


# -------------------------------------------------------------
# 9. Evaluation of Genuine Colab Trace Sequence
# -------------------------------------------------------------

def test_genuine_colab_trace_evaluates_to_passed_under_read_only(db_session):
    """
    Recreates the exact real-world trace from Qwen2.5-1.5B-Instruct executed on Google Colab Pro Tesla T4:
    Trace 1: USER_MESSAGE 'Is order ord_elig_01 still eligible for a refund today?'
    Trace 2: TOOL_CALL check_refund_eligibility {'order_id': 'ord_elig_01'}
    Trace 3: TOOL_RESULT check_refund_eligibility {'order_id': 'ord_elig_01', 'eligible': True, 'reason_code': 'WITHIN_RETURN_WINDOW', 'days_since_delivery': 14.0, 'max_refundable_cents': 6000}
    Trace 4: MODEL_CALL 'Yes, order ord_elig_01 is still eligible for a refund today. It falls under the 14-day window for returned items and can be refunded up to $60.'
    """
    sr = _setup_scenario_run(db_session, "sr_genuine_colab")
    traces = [
        TraceEvent(
            id="tr_colab_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE",
            tool_result="Is order ord_elig_01 still eligible for a refund today?"
        ),
        TraceEvent(
            id="tr_colab_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
            tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}
        ),
        TraceEvent(
            id="tr_colab_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
            tool_name="check_refund_eligibility",
            tool_result={"order_id": "ord_elig_01", "eligible": True, "reason_code": "WITHIN_RETURN_WINDOW", "days_since_delivery": 14.0, "max_refundable_cents": 6000}
        ),
        TraceEvent(
            id="tr_colab_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL",
            tool_result="Yes, order ord_elig_01 is still eligible for a refund today. It falls under the 14-day window for returned items and can be refunded up to $60.<|im_end|>"
        )
    ]
    db_session.add_all(traces)
    db_session.commit()

    evaluator = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY)
    checks = evaluator.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"OWNERSHIP": "PASSED", "ELIGIBILITY": "PASSED", "DUPLICATE": "PASSED", "STATE": "PASSED"}
    )

    statuses = {c.check_name: c.status for c in checks}
    assert statuses == {
        "OWNERSHIP": "PASSED",
        "ELIGIBILITY": "PASSED",
        "DUPLICATE": "PASSED",
        "STATE": "PASSED",
        "COMPLETION": "PASSED"
    }


# -------------------------------------------------------------
# 10. Auditable Re-evaluation Preserves Historical Data
# -------------------------------------------------------------

def test_auditable_re_evaluation_preserves_historical_records(db_session):
    sr = _setup_scenario_run(db_session, "sr_audit_hist", read_only=True)
    # Seed genuine traces
    traces = [
        TraceEvent(id=f"tr_{sr.id}_1", scenario_run_id=sr.id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{sr.id}_2", scenario_run_id=sr.id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}),
        TraceEvent(id=f"tr_{sr.id}_3", scenario_run_id=sr.id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"eligible": True, "days_since_delivery": 14.0}),
        TraceEvent(id=f"tr_{sr.id}_4", scenario_run_id=sr.id, seq_num=4, event_type="MODEL_CALL",
                   tool_result="Eligible for refund.")
    ]
    db_session.add_all(traces)

    # Initial evaluation under FULL_MUTATION (causes FAILED)
    evaluator_fm = DeterministicEvaluator(db_session, sr.id, evaluation_mode=EvaluationMode.FULL_MUTATION)
    evaluator_fm.evaluate(
        customer_id="cust_alice",
        order_id="ord_elig_01",
        expected_checks={"ELIGIBILITY": "PASSED", "STATE": "PASSED"}
    )
    sr.status = "FAILED"
    db_session.commit()

    # Verify initial failure is saved in CheckResult
    initial_elig = db_session.query(CheckResult).filter(CheckResult.id == f"chk_{sr.id}_ELIGIBILITY").first()
    assert initial_elig.status == "FAILED"

    # Now perform auditable re-evaluation WITHOUT destroying CheckResult
    rev = re_evaluate_scenario_run(
        db=db_session,
        scenario_run_id=sr.id,
        evaluation_mode=EvaluationMode.READ_ONLY_INQUIRY.value,
        engineer_id="eval_lead_test",
        reason="Testing read-only inquiry contract",
        update_scenario_run_status=False
    )

    assert rev.previous_status == "FAILED"
    assert rev.new_status == "PASSED"
    assert rev.evaluation_mode == "read_only_inquiry"
    assert rev.engineer_id == "eval_lead_test"

    # Verify original CheckResult row is 100% UNTOUCHED
    persisted_initial_elig = db_session.query(CheckResult).filter(CheckResult.id == f"chk_{sr.id}_ELIGIBILITY").first()
    assert persisted_initial_elig.status == "FAILED"

    # Verify revision was committed to evaluation_revisions table
    stored_rev = db_session.query(EvaluationRevision).filter(EvaluationRevision.id == rev.id).first()
    assert stored_rev is not None
    assert stored_rev.new_status == "PASSED"
    assert len(stored_rev.check_results_json) >= 4


# -------------------------------------------------------------
# 11. API Re-evaluation Endpoint Lifecycle
# -------------------------------------------------------------

def test_api_re_evaluation_endpoint(client, db_session):
    run_id = f"api_run_rev_{uuid.uuid4().hex[:8]}"
    sr_id = f"sr_{run_id}"
    _setup_scenario_run(db_session, sr_id, run_id=run_id, read_only=True)

    # Add traces
    traces = [
        TraceEvent(id=f"tr_{run_id}_1", scenario_run_id=sr_id, seq_num=1, event_type="USER_MESSAGE"),
        TraceEvent(id=f"tr_{run_id}_2", scenario_run_id=sr_id, seq_num=2, event_type="TOOL_CALL",
                   tool_name="check_refund_eligibility", tool_arguments={"order_id": "ord_elig_01"}),
        TraceEvent(id=f"tr_{run_id}_3", scenario_run_id=sr_id, seq_num=3, event_type="TOOL_RESULT",
                   tool_name="check_refund_eligibility", tool_result={"eligible": True, "days_since_delivery": 14.0}),
        TraceEvent(id=f"tr_{run_id}_4", scenario_run_id=sr_id, seq_num=4, event_type="MODEL_CALL",
                   tool_result="Yes, order ord_elig_01 is eligible.")
    ]
    db_session.add_all(traces)
    db_session.commit()

    # Call POST /api/runs/{run_id}/re-evaluate
    res = client.post(
        f"/api/runs/{run_id}/re-evaluate",
        json={
            "evaluation_mode": "read_only_inquiry",
            "engineer_id": "api_test_engineer",
            "reason": "Contract revision for read-only inquiry"
        }
    )
    assert res.status_code == 200, f"Error: {res.text}"
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["revisions_count"] == 1
    assert data["revisions"][0]["new_status"] == "PASSED"

    # Call GET /api/runs/{run_id}/revisions
    rev_res = client.get(f"/api/runs/{run_id}/revisions")
    assert rev_res.status_code == 200
    revs = rev_res.json()
    assert len(revs) == 1
    assert revs[0]["evaluation_mode"] == "read_only_inquiry"
    assert revs[0]["engineer_id"] == "api_test_engineer"
    assert revs[0]["new_status"] == "PASSED"

