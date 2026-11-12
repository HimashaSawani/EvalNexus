import pytest
import json
from backend.scenarios.generic_scenario import (
    GenericScenarioPayload,
    GenericAssertion,
    GenericToolContract,
    GenericExecutionLimits,
    is_generic_scenario
)
from backend.runner.generic_evaluator import resolve_json_path, extract_json_object
from backend.runner.generic_runner import execute_safe_synthetic_tool
from backend.scenarios.custom_scenario_service import (
    validate_and_parse_scenario,
    save_custom_scenario,
    list_custom_scenarios,
    get_custom_scenario,
    delete_custom_scenario
)


def test_generic_scenario_schema_valid():
    payload = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": "test_sentiment_valid",
        "name": "Test Sentiment Analysis",
        "domain": "sentiment",
        "evaluation_mode": "GENERIC",
        "input": {"text": "Great service!"},
        "assertions": [
            {
                "type": "json_schema",
                "schema_def": {
                    "type": "object",
                    "required": ["sentiment"],
                    "properties": {"sentiment": {"type": "string"}}
                }
            },
            {
                "type": "json_path_equals",
                "path": "sentiment",
                "expected": "POSITIVE"
            },
            {
                "type": "execution_completed"
            }
        ]
    }
    validated = validate_and_parse_scenario(payload)
    assert isinstance(validated, GenericScenarioPayload)
    assert validated.id == "test_sentiment_valid"
    assert validated.domain == "sentiment"
    assert is_generic_scenario(payload) is True


def test_generic_scenario_schema_invalid():
    # Missing assertions
    with pytest.raises(Exception):
        GenericScenarioPayload(
            id="bad_scen",
            name="Bad Scenario",
            domain="test",
            input={"text": "hello"},
            assertions=[]
        )

    # Invalid path traversal id
    with pytest.raises(Exception):
        GenericScenarioPayload(
            id="../bad_path",
            name="Bad Path",
            domain="test",
            input={"text": "hello"},
            assertions=[{"type": "execution_completed"}]
        )

    # Missing schema_def for json_schema
    with pytest.raises(Exception):
        GenericAssertion(type="json_schema")

    # Missing path for json_path_equals
    with pytest.raises(Exception):
        GenericAssertion(type="json_path_equals", expected="val")


def test_resolve_json_path_extractor():
    sample = {
        "status": "PLANNED",
        "destination": "Kyoto",
        "itinerary": {
            "days": [
                {"day": 1, "activity": "Shrines", "weather": "Sunny"},
                {"day": 2, "activity": "Gardens", "weather": "Rainy"}
            ]
        },
        "metrics": {
            "score": 0.98
        }
    }
    
    # Root level
    found, val = resolve_json_path(sample, "destination")
    assert found is True and val == "Kyoto"

    # Leading $.
    found, val = resolve_json_path(sample, "$.status")
    assert found is True and val == "PLANNED"

    # Nested object
    found, val = resolve_json_path(sample, "metrics.score")
    assert found is True and val == 0.98

    # Array indexing
    found, val = resolve_json_path(sample, "itinerary.days[0].activity")
    assert found is True and val == "Shrines"

    found, val = resolve_json_path(sample, "itinerary.days[1].weather")
    assert found is True and val == "Rainy"

    # Non-existent keys or out of bounds
    found, val = resolve_json_path(sample, "non_existent")
    assert found is False and val is None

    found, val = resolve_json_path(sample, "itinerary.days[99].activity")
    assert found is False and val is None


def test_extract_json_object_variants():
    # Direct dict
    d = {"sentiment": "POSITIVE"}
    assert extract_json_object(d) == d

    # Pure JSON string
    assert extract_json_object('{"sentiment": "POSITIVE"}') == d

    # Markdown code fence
    md = "Here is the response:\n```json\n{\"sentiment\": \"POSITIVE\"}\n```\nHope that helps!"
    assert extract_json_object(md) == d

    # Embedded braces
    emb = "The model evaluated the review: {\"sentiment\": \"POSITIVE\"} end of message."
    assert extract_json_object(emb) == d

    # Unparseable
    assert extract_json_object("No json anywhere here") is None


def test_safe_synthetic_tool_containment():
    # Allowlisted tools
    res_echo = execute_safe_synthetic_tool("echo_tool", {"message": "ping"}, [])
    assert res_echo == {"echo": "ping", "status": "ok"}

    res_weather = execute_safe_synthetic_tool("check_weather", {"city": "Paris"}, [])
    assert res_weather["city"] == "Paris"
    assert "temperature_c" in res_weather

    res_poi = execute_safe_synthetic_tool("lookup_poi", {"city": "Paris", "category": "museums"}, [])
    assert res_poi["city"] == "Paris"
    assert len(res_poi["pois"]) > 0

    # Custom contract stub
    contracts = [{"name": "custom_stub", "handler_type": "synthetic_stub"}]
    res_custom = execute_safe_synthetic_tool("custom_stub", {"arg1": "test"}, contracts)
    assert res_custom["status"] == "ok"

    # Prohibited / unauthorized tool
    res_prohibited = execute_safe_synthetic_tool("unauthorized_system_exec", {"cmd": "rm"}, [])
    assert res_prohibited.get("code") == "TOOL_NOT_PERMITTED"


def test_custom_scenario_service_generic_lifecycle(db_session):
    test_id = "test_generic_lifecycle_01"
    payload = {
        "schema_version": "evalnexus-generic-scenario/v2",
        "id": test_id,
        "name": "Generic Lifecycle Test Scenario",
        "domain": "sentiment",
        "evaluation_mode": "GENERIC",
        "input": {"text": "Lifecycle test input"},
        "assertions": [{"type": "execution_completed"}]
    }

    # Save
    saved = save_custom_scenario(db_session, payload)
    assert saved["id"] == test_id
    assert saved["evaluation_mode"] == "GENERIC"

    # Retrieve
    retrieved = get_custom_scenario(db_session, test_id)
    assert retrieved is not None
    assert retrieved["domain"] == "sentiment"
    assert is_generic_scenario(retrieved) is True

    # List
    all_scens = list_custom_scenarios(db_session)
    match = next((s for s in all_scens if s["id"] == test_id), None)
    assert match is not None
    assert match["evaluation_mode"] == "GENERIC"

    # Cleanup
    deleted = delete_custom_scenario(db_session, test_id)
    assert deleted is True
    assert get_custom_scenario(db_session, test_id) is None

