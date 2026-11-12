import copy
import json
import uuid
from pathlib import Path

import pytest

from backend.database.models import Run, ScenarioRun, TraceEvent, CheckResult
from backend.scenarios.offline_bundle import (
    import_colab_results,
    detect_incomplete_execution,
    _trace_event_id,
)
from backend.runner.generic_evaluator import extract_json_object

ARTIFACT = (
    Path(__file__).parents[1]
    / "experiments"
    / "colab_generic_travel_20261112_065358_8af322_result.json"
)

VALID_ANSWER = json.dumps({
    "destination": "Kyoto", "days": 3, "status": "PLANNED",
    "itinerary": {"days": [
        {"day": 1, "activity": "Shrines", "weather": "Sunny"},
        {"day": 2, "activity": "Gardens", "weather": "Sunny"},
        {"day": 3, "activity": "Markets", "weather": "Sunny"},
    ]},
})


def _tool_traces(n):
    names = ["check_weather", "lookup_poi"]
    return [
        {"seq": i + 1, "event_type": "TOOL_EXECUTION", "tool": names[i % 2],
         "arguments": {"city": "Kyoto"}, "result": {"ok": True}, "duration_ms": 1}
        for i in range(n)
    ]


def _payload(final_answer, traces, **extra):
    p = {
        "schema_version": "evalnexus-generic-run-result/v2",
        "run_id": f"integrity_{uuid.uuid4().hex[:10]}",
        "scenario_id": "generic_travel_planner",
        "domain": "travel",
        "final_answer": final_answer,
        "duration_ms": 10,
        "status": "COMPLETED",
        "traces": traces,
    }
    p.update(extra)
    return p


def _checks(db, payload):
    sr = db.query(ScenarioRun).filter(ScenarioRun.run_id == payload["run_id"]).first()
    rows = db.query(CheckResult).filter(CheckResult.scenario_run_id == sr.id).all()
    return sr, {c.check_name: c.status for c in rows}


def _by_type(db, payload, atype):
    sr = db.query(ScenarioRun).filter(ScenarioRun.run_id == payload["run_id"]).first()
    rows = db.query(CheckResult).filter(CheckResult.scenario_run_id == sr.id).all()
    return [c.status for c in rows if (c.evidence or {}).get("assertion_type") == atype]


# ---------------- final-answer / completion detection ----------------

def test_tool_call_markup_is_not_a_final_answer():
    err = detect_incomplete_execution('<tool_call>{"name": "x"}</tool_call>', [], {}, {})
    assert err and "tool_call" in err


def test_missing_final_answer_detected():
    assert detect_incomplete_execution(None, [], {}, {})
    assert detect_incomplete_execution("   ", [], {}, {})


def test_valid_final_answer_not_flagged():
    assert detect_incomplete_execution(VALID_ANSWER, [], {}, {}) is None


def test_tool_call_limit_detected_from_scenario_limits():
    class T:
        tool = "lookup_poi"
    err = detect_incomplete_execution(VALID_ANSWER, [T()] * 5, {"execution_limits": {"max_tool_calls": 4}}, {})
    assert err and "limit" in err.lower()


def test_embedded_json_inside_tool_call_not_accepted_as_completion(db_session):
    # Valid JSON embedded in unresolved tool-call markup, execution_error null.
    answer = "<tool_call>\n" + VALID_ANSWER + "\n</tool_call>"
    p = _payload(answer, _tool_traces(2), execution_error=None)
    import_colab_results(db_session, p)
    sr, _ = _checks(db_session, p)
    assert _by_type(db_session, p, "execution_completed") == ["FAILED"]
    assert _by_type(db_session, p, "json_schema") == ["FAILED"]
    assert sr.status == "FAILED"


def test_valid_standalone_answer_still_passes(db_session):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    res = import_colab_results(db_session, p)
    assert res["passed"] is True
    assert res["passed_checks"] == res["total_checks"] == 6


# ---------------- trace-ID collision ----------------

def test_old_scheme_collides_and_new_scheme_does_not():
    run = "scen_run_" + "x" * 52 + "_generic_travel_planner"
    run = run[:64]
    old = {f"tr_{run}_{s}"[:64] for s in range(1, 8)}
    assert len(old) == 1  # reproduces the defect
    new = {_trace_event_id(run, s) for s in range(1, 8)} | {_trace_event_id(run, "resp")}
    assert len(new) == 8
    assert all(len(i) <= 64 for i in new)
    assert _trace_event_id(run, 3) == _trace_event_id(run, 3)  # deterministic
    assert _trace_event_id(run, 3) != _trace_event_id(run + "z", 3)  # ownership-scoped


def test_import_many_tool_calls_with_long_run_id(db_session):
    long_id = "colab_generic_travel_" + "a" * 40  # 61 chars
    p = _payload("<tool_call>x</tool_call>", _tool_traces(5))
    p["run_id"] = long_id
    import_colab_results(db_session, p)
    sr = db_session.query(ScenarioRun).filter(ScenarioRun.run_id == long_id).first()
    ev = db_session.query(TraceEvent).filter(TraceEvent.scenario_run_id == sr.id).order_by(TraceEvent.seq_num).all()
    assert [e.seq_num for e in ev] == [1, 2, 3, 4, 5, 6]
    assert len({e.id for e in ev}) == 6


def test_duplicate_import_rejected(db_session):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    import_colab_results(db_session, p)
    with pytest.raises(ValueError, match="Duplicate import detected"):
        import_colab_results(db_session, p)


# ---------------- original historical Qwen artifact ----------------

@pytest.mark.skipif(not ARTIFACT.exists(), reason="original Qwen artifact not present")
def test_original_qwen_artifact_fails_completion(db_session):
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert not payload.get("execution_error")  # historical export claims no error
    payload["run_id"] = "rehearsal_" + uuid.uuid4().hex[:8]
    res = import_colab_results(db_session, payload)
    sr, checks = _checks(db_session, payload)
    assert res["passed"] is False
    assert sr.status == "FAILED"
    run = db_session.query(Run).filter(Run.id == payload["run_id"]).first()
    assert run.failed_scenarios == 1
    execution = _by_type(db_session, payload, "execution_completed")
    assert execution == ["FAILED"]
    n_tools = db_session.query(TraceEvent).filter(
        TraceEvent.scenario_run_id == sr.id, TraceEvent.tool_name.isnot(None)
    ).count()
    assert n_tools == 5


# ---------------- Colab notebook Step 14 contract ----------------

def test_notebook_step14_fails_closed_and_records_termination():
    nb = json.loads((Path(__file__).parents[1] / "EvalNexus_Colab_LLM.ipynb").read_text(encoding="utf-8"))
    src = next(
        "".join(c["source"]) for c in nb["cells"]
        if c["cell_type"] == "code" and "Step 14: Canonical Generic Scenario Bundle Runner" in "".join(c["source"])
    )
    for reason in ("FINAL_ANSWER", "MAX_TURNS_EXHAUSTED", "TOOL_BLOCKED", "EXECUTION_ERROR"):
        assert reason in src
    assert '"execution_error": execution_error' in src
    assert "Fallback simulation" not in src  # no fabricated model output
    assert "if not final_response_text:\n    final_response_text = turn_output" not in src


# ---------------- Atomic Import & Failure Injection Tests ----------------

def _assert_zero_partial_records(db, run_id):
    assert db.query(Run).filter(Run.id == run_id).first() is None
    assert db.query(ScenarioRun).filter(ScenarioRun.run_id == run_id).all() == []
    assert db.query(TraceEvent).filter(TraceEvent.scenario_run_id.like(f"%{run_id}%")).all() == []
    assert db.query(CheckResult).filter(CheckResult.scenario_run_id.like(f"%{run_id}%")).all() == []


def test_atomic_rollback_on_run_creation_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    orig_add = db_session.add
    def failing_add(instance):
        if isinstance(instance, Run) and instance.id == run_id:
            raise RuntimeError("Injected failure at Run creation")
        return orig_add(instance)

    monkeypatch.setattr(db_session, "add", failing_add)
    with pytest.raises(RuntimeError, match="Injected failure at Run creation"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)


def test_atomic_rollback_on_scenario_run_creation_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    orig_add = db_session.add
    def failing_add(instance):
        if isinstance(instance, ScenarioRun) and instance.run_id == run_id:
            raise RuntimeError("Injected failure at ScenarioRun creation")
        return orig_add(instance)

    monkeypatch.setattr(db_session, "add", failing_add)
    with pytest.raises(RuntimeError, match="Injected failure at ScenarioRun creation"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)


def test_atomic_rollback_on_trace_event_persistence_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    orig_add = db_session.add
    def failing_add(instance):
        if isinstance(instance, TraceEvent) and run_id in instance.scenario_run_id:
            raise RuntimeError("Injected failure at TraceEvent persistence")
        return orig_add(instance)

    monkeypatch.setattr(db_session, "add", failing_add)
    with pytest.raises(RuntimeError, match="Injected failure at TraceEvent persistence"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)


def test_atomic_rollback_on_evaluator_execution_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    from backend.runner.generic_evaluator import GenericAssertionEvaluator
    def failing_evaluate(*args, **kwargs):
        raise RuntimeError("Injected failure during GenericAssertionEvaluator execution")

    monkeypatch.setattr(GenericAssertionEvaluator, "evaluate_all", failing_evaluate)
    with pytest.raises(RuntimeError, match="Injected failure during GenericAssertionEvaluator execution"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)


def test_atomic_rollback_on_check_result_persistence_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    orig_add = db_session.add
    def failing_add(instance):
        if isinstance(instance, CheckResult) and run_id in instance.scenario_run_id:
            raise RuntimeError("Injected failure at CheckResult persistence")
        return orig_add(instance)

    monkeypatch.setattr(db_session, "add", failing_add)
    with pytest.raises(RuntimeError, match="Injected failure at CheckResult persistence"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)


def test_atomic_rollback_on_final_commit_failure(db_session, monkeypatch):
    p = _payload(VALID_ANSWER, _tool_traces(2))
    run_id = p["run_id"]

    orig_commit = db_session.commit
    def failing_commit():
        raise RuntimeError("Injected failure at final commit")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError, match="Injected failure at final commit"):
        import_colab_results(db_session, p)
    _assert_zero_partial_records(db_session, run_id)

