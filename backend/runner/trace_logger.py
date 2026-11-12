import datetime
import uuid
import time
import threading
import queue
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from backend.database.models import TraceEvent


class TraceLogger:
    def __init__(self, db: Session, scenario_run_id: str):
        self.db = db
        self.scenario_run_id = scenario_run_id
        self.seq_num = 0
        self._owner_thread = threading.get_ident()
        self._pending = queue.SimpleQueue()
        self._draining = False
        self.events: List[Dict[str, Any]] = []

    def _gen_event_id(self) -> str:
        """Generate a unique primary‑key for a TraceEvent.
        Keeps the original ordering via seq_num and adds a short UUID
        to avoid collisions while staying under the 64‑char column limit.
        """
        base = f"trc_{self.scenario_run_id}_{self.seq_num}_"
        uniq = uuid.uuid4().hex[:6]
        return (base + uniq)[:64]

    def flush_pending(self):
        if threading.get_ident() != self._owner_thread or self._draining:
            return
        self._draining = True
        try:
            while True:
                try:
                    payload = self._pending.get_nowait()
                except queue.Empty:
                    return
                self.log_event(**payload)
        finally:
            self._draining = False

    def log_event(
        self,
        event_type: str,
        tool_name: Optional[str] = None,
        tool_arguments: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        duration_ms: int = 0,
        token_usage: Optional[Dict[str, int]] = None,
        cost_estimate: int = 0,
    ) -> TraceEvent:
        if threading.get_ident() != self._owner_thread:
            self._pending.put(dict(
                event_type=event_type,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                tool_result=tool_result,
                error_message=error_message,
                duration_ms=duration_ms,
                token_usage=token_usage,
                cost_estimate=cost_estimate,
            ))
            return None
        self.flush_pending()
        self.seq_num += 1
        event_id = self._gen_event_id()

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
            cost_estimate=cost_estimate,
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
            "duration_ms": duration_ms,
        })

        return trace_record