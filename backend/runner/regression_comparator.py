import math
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from backend.database.models import Run, ScenarioRun, TraceEvent, CheckResult
from backend.agent.provider import COST_DISCLAIMER


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculates percentile (0-100) from list of floats."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(d0 + d1)


class RegressionComparator:
    """
    Automated Regression Engine:
    Compares baseline vs candidate agent runs, classifies behavioral differences,
    computes latency and token deltas, and outputs machine-readable reports.
    """

    def __init__(self, db: Session):
        self.db = db

    def compare(self, baseline_run_id: str, candidate_run_id: str) -> Dict[str, Any]:
        baseline_run = self.db.query(Run).filter(Run.id == baseline_run_id).first()
        candidate_run = self.db.query(Run).filter(Run.id == candidate_run_id).first()

        if not baseline_run:
            raise ValueError(f"Baseline run '{baseline_run_id}' not found.")
        if not candidate_run:
            raise ValueError(f"Candidate run '{candidate_run_id}' not found.")

        # Load scenario runs
        base_srs = {
            sr.scenario_version_id: sr
            for sr in self.db.query(ScenarioRun).filter(ScenarioRun.run_id == baseline_run_id).all()
        }
        cand_srs = {
            sr.scenario_version_id: sr
            for sr in self.db.query(ScenarioRun).filter(ScenarioRun.run_id == candidate_run_id).all()
        }

        all_scenario_ids = sorted(list(set(base_srs.keys()).union(set(cand_srs.keys()))))

        scenario_comparisons = []
        regressions_count = 0
        improvements_count = 0
        parity_count = 0

        base_durations: List[float] = []
        cand_durations: List[float] = []

        base_tokens_total = 0
        cand_tokens_total = 0
        base_cost_microcents = 0
        cand_cost_microcents = 0

        for sid in all_scenario_ids:
            b_sr = base_srs.get(sid)
            c_sr = cand_srs.get(sid)

            b_status = b_sr.status if b_sr else "NOT_RUN"
            c_status = c_sr.status if c_sr else "NOT_RUN"

            b_dur = b_sr.duration_ms if b_sr else 0
            c_dur = c_sr.duration_ms if c_sr else 0

            if b_sr and b_sr.duration_ms:
                base_durations.append(float(b_sr.duration_ms))
            if c_sr and c_sr.duration_ms:
                cand_durations.append(float(c_sr.duration_ms))

            # Fetch traces to compute behavioral tool call sequences
            b_traces = (
                self.db.query(TraceEvent)
                .filter(TraceEvent.scenario_run_id == b_sr.id)
                .order_by(TraceEvent.seq_num)
                .all()
                if b_sr
                else []
            )
            c_traces = (
                self.db.query(TraceEvent)
                .filter(TraceEvent.scenario_run_id == c_sr.id)
                .order_by(TraceEvent.seq_num)
                .all()
                if c_sr
                else []
            )

            # Tool sequences
            b_tools = [t.tool_name for t in b_traces if t.tool_name]
            c_tools = [t.tool_name for t in c_traces if t.tool_name]

            # Token usage & cost accumulation
            for t in b_traces:
                if t.token_usage and isinstance(t.token_usage, dict):
                    base_tokens_total += t.token_usage.get("total", 0)
                base_cost_microcents += (t.cost_estimate or 0)

            for t in c_traces:
                if t.token_usage and isinstance(t.token_usage, dict):
                    cand_tokens_total += t.token_usage.get("total", 0)
                cand_cost_microcents += (t.cost_estimate or 0)

            # Behavioral classification
            diff_tools = b_tools != c_tools
            if b_status == "PASSED" and c_status in ["FAILED", "PROVIDER_ERROR"]:
                classification = "REGRESSION"
                regressions_count += 1
            elif b_status in ["FAILED", "PROVIDER_ERROR"] and c_status == "PASSED":
                classification = "IMPROVEMENT"
                improvements_count += 1
            elif b_status == c_status and b_status != "NOT_RUN":
                classification = "PARITY"
                parity_count += 1
            else:
                classification = "OBSERVATIONAL"

            scenario_comparisons.append({
                "scenario_id": sid,
                "baseline_status": b_status,
                "candidate_status": c_status,
                "classification": classification,
                "baseline_duration_ms": b_dur,
                "candidate_duration_ms": c_dur,
                "duration_delta_ms": c_dur - b_dur,
                "baseline_tool_sequence": b_tools,
                "candidate_tool_sequence": c_tools,
                "behavioral_tool_sequence_changed": diff_tools
            })

        # Overall verdict
        if regressions_count > 0:
            overall_verdict = "REGRESSION_DETECTED"
        elif improvements_count > 0 and regressions_count == 0:
            overall_verdict = "IMPROVED"
        elif parity_count > 0 and regressions_count == 0 and improvements_count == 0:
            overall_verdict = "PARITY"
        else:
            overall_verdict = "NEUTRAL"

        # Statistical sample size evaluation
        n_scenarios = len(all_scenario_ids)
        statistical_confidence = (
            f"INSUFFICIENT_SAMPLE_SIZE (N={n_scenarios} < 10; observational only, do not claim statistical reliability)"
            if n_scenarios < 10
            else f"VALID_BENCHMARK_SAMPLE (N={n_scenarios} >= 10)"
        )

        # Latency statistics
        p50_base = round(calculate_percentile(base_durations, 50), 1)
        p50_cand = round(calculate_percentile(cand_durations, 50), 1)
        p90_base = round(calculate_percentile(base_durations, 90), 1)
        p90_cand = round(calculate_percentile(cand_durations, 90), 1)

        base_pass_rate = round(
            (baseline_run.passed_scenarios / baseline_run.total_scenarios * 100.0)
            if baseline_run.total_scenarios
            else 0.0,
            1
        )
        cand_pass_rate = round(
            (candidate_run.passed_scenarios / candidate_run.total_scenarios * 100.0)
            if candidate_run.total_scenarios
            else 0.0,
            1
        )

        return {
            "verdict": overall_verdict,
            "statistical_confidence": statistical_confidence,
            "cost_disclaimer": COST_DISCLAIMER,
            "summary": {
                "total_scenarios": n_scenarios,
                "regressions": regressions_count,
                "improvements": improvements_count,
                "parity": parity_count,
                "baseline_pass_rate": base_pass_rate,
                "candidate_pass_rate": cand_pass_rate,
                "pass_rate_delta": round(cand_pass_rate - base_pass_rate, 1)
            },
            "latency": {
                "baseline_p50_ms": p50_base,
                "candidate_p50_ms": p50_cand,
                "delta_p50_ms": round(p50_cand - p50_base, 1),
                "baseline_p90_ms": p90_base,
                "candidate_p90_ms": p90_cand,
                "delta_p90_ms": round(p90_cand - p90_base, 1)
            },
            "token_and_cost": {
                "baseline_tokens": base_tokens_total,
                "candidate_tokens": cand_tokens_total,
                "tokens_delta": cand_tokens_total - base_tokens_total,
                "baseline_cost_microcents": base_cost_microcents,
                "candidate_cost_microcents": cand_cost_microcents,
                "cost_microcents_delta": cand_cost_microcents - base_cost_microcents,
                "baseline_cost_usd": round(base_cost_microcents / 100_000_000.0, 6),
                "candidate_cost_usd": round(cand_cost_microcents / 100_000_000.0, 6),
                "cost_usd_delta": round((cand_cost_microcents - base_cost_microcents) / 100_000_000.0, 6)
            },
            "runs": {
                "baseline": {
                    "id": baseline_run.id,
                    "agent_version": baseline_run.agent_version_id,
                    "provider_type": baseline_run.provider_type,
                    "model_name": baseline_run.model_name
                },
                "candidate": {
                    "id": candidate_run.id,
                    "agent_version": candidate_run.agent_version_id,
                    "provider_type": candidate_run.provider_type,
                    "model_name": candidate_run.model_name
                }
            },
            "scenarios": scenario_comparisons
        }

