import json
import re
from pathlib import Path

# Import functions from notebook (we'll import the cell code as module?)
# For simplicity, we replicate the relevant logic here.

def build_tools_spec(tools_contract):
    return [
        {
            "type": "function",
            "function": {
                "name": tc["name"],
                "description": tc.get("description", ""),
                "parameters": tc.get("parameters", {}),
            },
        }
        for tc in tools_contract
    ]

def extract_tool_calls(text: str):
    """Extract <tool_call> JSON blocks from model output."""
    pattern = re.compile(r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>")
    calls = []
    for m in pattern.findall(text):
        try:
            calls.append(json.loads(m))
        except Exception:
            continue
    return calls

def test_build_tools_spec_matches_bundle():
    # Load the travel bundle to get expected contracts
    bundle_path = Path(__file__).parents[1] / "docs" / "scenarios" / "generic_travel_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    scenario = bundle["scenario"]
    contracts = scenario["tool_contracts"]
    spec = build_tools_spec(contracts)
    # Verify each contract appears in the spec with correct fields
    for tc, s in zip(contracts, spec):
        assert s["type"] == "function"
        func = s["function"]
        assert func["name"] == tc["name"]
        assert func["description"] == tc.get("description", "")
        assert func["parameters"] == tc.get("parameters", {})

def test_extract_tool_calls_parses_example():
    example = """<tool_call>\n{\"name\": \"check_weather\", \"arguments\": {\"city\": \"Kyoto\"}}\n</tool_call>"""
    calls = extract_tool_calls(example)
    assert len(calls) == 1
    assert calls[0]["name"] == "check_weather"
    assert calls[0]["arguments"]["city"] == "Kyoto"

