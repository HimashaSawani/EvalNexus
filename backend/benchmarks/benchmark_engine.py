import math
import time
import statistics
from typing import List, Dict, Any, Optional, Tuple, Callable
from pydantic import BaseModel, Field


def calculate_percentile(values: List[float], p: float) -> float:
    """Calculates the p-th percentile (0 <= p <= 100) of a list of numeric values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(d0 + d1)


def wilson_score_interval(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """
    Calculates the Wilson score confidence interval for a binomial proportion.
    Default z = 1.96 corresponds to a 95% confidence level.
    """
    if total <= 0:
        return (0.0, 0.0)
    p_hat = successes / total
    denom = 1 + (z ** 2) / total
    center_adj = p_hat + (z ** 2) / (2 * total)
    spread = z * math.sqrt((p_hat * (1 - p_hat) + (z ** 2) / (4 * total)) / total)
    lower = max(0.0, (center_adj - spread) / denom)
    upper = min(1.0, (center_adj + spread) / denom)
    return (round(lower, 4), round(upper, 4))


class BenchmarkIterationResult(BaseModel):
    iteration: int
    status: str  # PASSED, FAILED, ERROR
    duration_ms: int
    tokens_used: int = 0
    cost_usd: float = 0.0
    tools_called: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class BenchmarkSummary(BaseModel):
    benchmark_name: str
    iterations: int
    passed_count: int
    failed_count: int
    pass_rate: float
    confidence_interval_95: Tuple[float, float]
    latency_p50_ms: float
    latency_p90_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    latency_stddev_ms: float
    total_tokens: int
    total_cost_usd: float
    stability_score: int  # 0 to 100
    iteration_details: List[BenchmarkIterationResult] = Field(default_factory=list)


class BenchmarkEngine:
    """
    Executes multi-run reliability benchmarks across deterministic scenarios,
    computing latency distribution percentiles, sample confidence intervals, and stability scores.
    """
    def __init__(self, name: str, iterations: int = 5):
        self.name = name
        self.iterations = max(1, iterations)

    def execute(self, test_runner_fn: Callable[[int], Dict[str, Any]]) -> BenchmarkSummary:
        """
        Runs the benchmark test function across `iterations` repetitions.
        test_runner_fn receives the iteration index (0-based) and returns a dict:
        {"status": "PASSED"|"FAILED", "duration_ms": int, "tokens": int, "cost_usd": float, "tools": list, "error": str}
        """
        results: List[BenchmarkIterationResult] = []
        latencies: List[float] = []
        total_tokens = 0
        total_cost = 0.0
        passed = 0

        for i in range(self.iterations):
            t0 = time.time()
            try:
                out = test_runner_fn(i)
                dur = out.get("duration_ms", int((time.time() - t0) * 1000))
                status = out.get("status", "PASSED")
                tok = out.get("tokens", 0)
                cost = out.get("cost_usd", 0.0)
                tools = out.get("tools", [])
                err = out.get("error")
            except Exception as e:
                dur = int((time.time() - t0) * 1000)
                status = "FAILED"
                tok = 0
                cost = 0.0
                tools = []
                err = str(e)

            if status == "PASSED":
                passed += 1

            latencies.append(float(dur))
            total_tokens += tok
            total_cost += cost

            results.append(BenchmarkIterationResult(
                iteration=i + 1,
                status=status,
                duration_ms=dur,
                tokens_used=tok,
                cost_usd=round(cost, 6),
                tools_called=tools,
                error_message=err
            ))

        pass_rate = round(passed / self.iterations, 4)
        ci_95 = wilson_score_interval(passed, self.iterations)

        p50 = calculate_percentile(latencies, 50)
        p90 = calculate_percentile(latencies, 90)
        p95 = calculate_percentile(latencies, 95)
        mean_lat = round(statistics.mean(latencies), 2) if latencies else 0.0
        stddev_lat = round(statistics.stdev(latencies), 2) if len(latencies) > 1 else 0.0

        # Stability score: accounts for pass rate (70%) and latency variance CV (30%)
        pass_component = pass_rate * 70.0
        cv = (stddev_lat / mean_lat) if mean_lat > 0 else 0.0
        variance_penalty = min(30.0, cv * 20.0)
        stability_score = max(0, min(100, int(pass_component + (30.0 - variance_penalty))))

        return BenchmarkSummary(
            benchmark_name=self.name,
            iterations=self.iterations,
            passed_count=passed,
            failed_count=self.iterations - passed,
            pass_rate=pass_rate,
            confidence_interval_95=ci_95,
            latency_p50_ms=round(p50, 2),
            latency_p90_ms=round(p90, 2),
            latency_p95_ms=round(p95, 2),
            latency_mean_ms=mean_lat,
            latency_stddev_ms=stddev_lat,
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 6),
            stability_score=stability_score,
            iteration_details=results
        )
