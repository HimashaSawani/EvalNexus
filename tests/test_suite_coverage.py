import os
import json
import pytest

from backend.scenarios.generate_suite import SCENARIOS


def test_suite_total_count_and_partitions():
    assert len(SCENARIOS) == 30

    dev_cases = [s for s in SCENARIOS if s.get("dataset") == "development"]
    held_out_cases = [s for s in SCENARIOS if s.get("dataset") == "held_out"]

    assert len(dev_cases) == 20
    assert len(held_out_cases) == 10


def test_suite_category_balance():
    categories = [s["category"] for s in SCENARIOS]
    cat_counts = {}
    for c in categories:
        cat_counts[c] = cat_counts.get(c, 0) + 1

    assert cat_counts.get("NORMAL") == 6
    assert cat_counts.get("ELIGIBILITY") == 6
    assert cat_counts.get("OWNERSHIP") == 6
    assert cat_counts.get("TOOL_FAILURE") == 6
    assert cat_counts.get("DUPLICATE") == 6


def test_all_five_fault_modes_covered():
    fault_types = set()
    for s in SCENARIOS:
        configs = s.get("fault_configs", {})
        for tool, cfg in configs.items():
            if "fault_type" in cfg:
                fault_types.add(cfg["fault_type"])

    expected_faults = {
        "TIMEOUT_BEFORE_WRITE",
        "TIMEOUT_AFTER_WRITE",
        "TEMPORARY_UNAVAILABLE",
        "STALE_READ",
        "MALFORMED_RESPONSE"
    }

    assert expected_faults.issubset(fault_types)


def test_scenario_files_exist_and_parse():
    scen_dir = "scenarios"
    dev_dir = os.path.join(scen_dir, "dev")
    held_out_dir = os.path.join(scen_dir, "held_out")

    assert os.path.exists(dev_dir)
    assert os.path.exists(held_out_dir)

    dev_files = [f for f in os.listdir(dev_dir) if f.endswith(".json")]
    held_out_files = [f for f in os.listdir(held_out_dir) if f.endswith(".json")]

    assert len(dev_files) == 20
    assert len(held_out_files) == 10

    # Test reading and validating essential fields
    for f in dev_files:
        with open(os.path.join(dev_dir, f), "r", encoding="utf-8") as fp:
            data = json.load(fp)
            assert "id" in data
            assert "category" in data
            assert "fixed_clock" in data
            assert "initial_data" in data
            assert "expected_checks" in data
