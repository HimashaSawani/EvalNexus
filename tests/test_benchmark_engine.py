import pytest
from backend.benchmarks.benchmark_engine import (
    calculate_percentile,
    wilson_score_interval,
    BenchmarkEngine
)


def test_percentile_calculation():
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50 = calculate_percentile(data, 50)
    p90 = calculate_percentile(data, 90)
    p95 = calculate_percentile(data, 95)

    assert p50 == pytest.approx(55.0, abs=1.0)
    assert p90 == pytest.approx(91.0, abs=1.0)
    assert p95 == pytest.approx(95.5, abs=1.0)


def test_wilson_confidence_interval():
    # 10 out of 10 successes
    low, high = wilson_score_interval(10, 10)
    assert low > 0.65
    assert high == 1.0

    # 0 out of 10 successes
    low_0, high_0 = wilson_score_interval(0, 10)
    assert low_0 == 0.0
    assert high_0 < 0.35

    # 8 out of 10
    low_8, high_8 = wilson_score_interval(8, 10)
    assert 0.44 < low_8 < 0.8
    assert 0.8 < high_8 <= 1.0


def test_benchmark_engine_execution():
    engine = BenchmarkEngine(name="Order Refund Latency Benchmark", iterations=8)

    # Mock runner function returning consistent results
    def mock_agent_runner(i: int):
        latencies = [110, 120, 115, 130, 125, 140, 118, 122]
        return {
            "status": "PASSED",
            "duration_ms": latencies[i],
            "tokens": 150,
            "cost_usd": 0.00015,
            "tools": ["lookup_order", "refund_order"]
        }

    summary = engine.execute(mock_agent_runner)

    assert summary.iterations == 8
    assert summary.passed_count == 8
    assert summary.failed_count == 0
    assert summary.pass_rate == 1.0
    assert len(summary.iteration_details) == 8
    assert summary.confidence_interval_95[0] > 0.6
    assert 110 <= summary.latency_p50_ms <= 130
    assert summary.stability_score >= 85
    assert summary.total_tokens == 8 * 150
