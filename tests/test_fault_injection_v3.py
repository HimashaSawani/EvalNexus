import pytest
from backend.faults.fault_injector import FaultInjector, FaultInjectionError


def test_fault_rate_limit_429():
    config = {
        "lookup_order": {
            "fault_type": "HTTP_429_RATE_LIMIT",
            "trigger_on_call": 1,
            "retry_after_sec": 3
        }
    }
    injector = FaultInjector(fault_configs=config)

    with pytest.raises(FaultInjectionError) as exc_info:
        injector.before_tool_call("lookup_order", {"order_id": "ord_101"})

    err = exc_info.value
    assert err.fault_type == "HTTP_429_RATE_LIMIT"
    assert err.status_code == 429
    assert "Retry-After: 3s" in err.agent_visible_message
    assert err.internal_evidence["retry_after_sec"] == 3


def test_fault_internal_error_500():
    config = {
        "refund_order": {
            "fault_type": "HTTP_500_INTERNAL_ERROR",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)

    with pytest.raises(FaultInjectionError) as exc_info:
        injector.before_tool_call("refund_order", {"order_id": "ord_102"})

    err = exc_info.value
    assert err.fault_type == "HTTP_500_INTERNAL_ERROR"
    assert err.status_code == 500


def test_fault_dropout():
    config = {
        "charge_card": {
            "fault_type": "DROPOUT",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)

    with pytest.raises(FaultInjectionError) as exc_info:
        injector.before_tool_call("charge_card", {})

    err = exc_info.value
    assert err.fault_type == "DROPOUT"
    assert err.status_code == 502
    assert "ECONNRESET" in err.agent_visible_message


def test_fault_partial_payload():
    config = {
        "get_profile": {
            "fault_type": "PARTIAL_PAYLOAD",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)
    injector.before_tool_call("get_profile", {})
    
    raw = {"user_id": "usr_99", "email": "usr@example.com", "balance": 100}
    corrupted = injector.after_tool_call("get_profile", raw)
    assert len(corrupted) == 1
    assert "user_id" in corrupted


def test_fault_schema_mutation():
    config = {
        "fetch_price": {
            "fault_type": "SCHEMA_MUTATION",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)
    injector.before_tool_call("fetch_price", {})

    raw = {"price": 4999, "status": "active"}
    mutated = injector.after_tool_call("fetch_price", raw)
    assert "mutated_price" in mutated
    assert mutated["mutated_price"] == "CORRUPT_4999"
    assert mutated["STATUS"] == "active"


def test_fault_token_flood():
    config = {
        "dump_log": {
            "fault_type": "TOKEN_FLOOD",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)
    injector.before_tool_call("dump_log", {})

    raw = {"order_id": "ord_flood", "status": "OK"}
    flooded = injector.after_tool_call("dump_log", raw)
    assert "debug_dump" in flooded
    assert len(flooded["debug_dump"]) > 1000


def test_resilience_metrics_calculation():
    config = {
        "service_x": {
            "fault_type": "DROPOUT",
            "trigger_on_call": 1
        }
    }
    injector = FaultInjector(fault_configs=config)
    try:
        injector.before_tool_call("service_x", {})
    except FaultInjectionError:
        pass

    # Agent recovered and passed
    metrics_passed = injector.calculate_resilience_metrics(final_status="PASSED", execution_duration_ms=1200)
    assert metrics_passed["total_faults_injected"] == 1
    assert metrics_passed["recovered"] is True
    assert metrics_passed["recovery_rate"] == 1.0
    assert metrics_passed["verdict"] == "RESILIENT"
    assert metrics_passed["resilience_score"] > 80

    # Agent failed
    metrics_failed = injector.calculate_resilience_metrics(final_status="FAILED", execution_duration_ms=1200)
    assert metrics_failed["recovered"] is False
    assert metrics_failed["recovery_rate"] == 0.0
    assert metrics_failed["verdict"] == "FAILED_RECOVERY"
