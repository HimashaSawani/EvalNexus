import datetime
import time
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from backend.database.models import TraceEvent


class TraceLogger:
    def __init__(self, db: Session, scenario_run_id: str):
        self.db = db
        self.scenario_run_id = scenario_run_id
        self.seq_num = 0
        self.events: List[Dict[str, Any]] = []

    def log_event(
        self,
        event_type: str,
        tool_name: Optional[str] = None,
        tool_arguments: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        duration_ms: int = 0,
        token_usage: Optional[Dict[str, int]] = None,
        cost_estimate: int = 0
    ) -> TraceEvent:
        self.seq_num += 1
        event_id = f"trc_{self.scenario_run_id}_{self.seq_num}"

        trace_record = TraceEvent(
            id=event_id,
            scenario_run_id=self.scenario_run_id,
            seq_num=self.seq_num,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            duration_ms=duration_ms,
            event_type=event_type,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            error_message=error_message,
            token_usage=token_usage,
            cost_estimate=cost_estimate
        )

        self.db.add(trace_record)
        self.db.commit()
        self.db.refresh(trace_record)

        self.events.append({
            "seq_num": self.seq_num,
            "event_type": event_type,
            "tool_name": tool_name,
            "tool_arguments": tool_arguments,
            "tool_result": tool_result,
            "error_message": error_message,
            "duration_ms": duration_ms
        })

        return trace_record
