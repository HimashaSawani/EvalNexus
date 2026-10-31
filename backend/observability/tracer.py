import re
import uuid
import time
import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


SECRET_KEY_NAMES = {
    "token", "secret", "api_key", "apikey", "password", "authorization", 
    "auth_token", "access_token", "bearer_token", "token_secret", "private_key"
}

SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-\.]{8,})"), r"Bearer ***MASKED***"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|access_token)\s*[:=]\s*['\"]?([^'\"\s,;]+)['\"]?"), r"\1=***MASKED***"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), r"***@***.***"),
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), r"****-****-****-****"),  # Card numbers
]


def mask_sensitive_data(obj: Any) -> Any:
    """Recursively scrub sensitive keys and patterns from strings, dicts, and lists."""
    if isinstance(obj, str):
        masked = obj
        for pattern, repl in SENSITIVE_PATTERNS:
            masked = pattern.sub(repl, masked)
        return masked
    elif isinstance(obj, dict):
        scrubbed = {}
        for k, v in obj.items():
            k_lower = str(k).lower().strip()
            # Only match actual secret credential keys, not token metrics like tokens.prompt
            is_secret = (
                k_lower in SECRET_KEY_NAMES or 
                any(s in k_lower for s in ("api_key", "apikey", "secret", "password")) or
                (k_lower.endswith("_token") and not k_lower.startswith("total_") and not "count" in k_lower)
            )
            if is_secret:
                scrubbed[k] = "***MASKED***"
            else:
                scrubbed[k] = mask_sensitive_data(v)
        return scrubbed
    elif isinstance(obj, list):
        return [mask_sensitive_data(item) for item in obj]
    return obj


class SpanEvent(BaseModel):
    name: str
    timestamp: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class Span(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    kind: str = "INTERNAL"  # INTERNAL, CLIENT, SERVER
    start_time_iso: str
    end_time_iso: Optional[str] = None
    duration_ms: int = 0
    status: str = "OK"  # OK, ERROR
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[SpanEvent] = Field(default_factory=list)
    error_message: Optional[str] = None


class ExecutionTracer:
    """
    Hierarchical OpenTelemetry-compatible execution tracer
    capturing spans, token breakdowns, and timing with automatic redaction.
    """
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:16]}"
        self.spans: Dict[str, Span] = {}
        self.span_start_times: Dict[str, float] = {}
        self.active_stack: List[str] = []

    def start_span(
        self,
        name: str,
        parent_span_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        kind: str = "INTERNAL"
    ) -> str:
        """Starts a new span within the current trace context."""
        span_id = f"span_{uuid.uuid4().hex[:12]}"
        
        # Infer parent from active stack if not specified
        if parent_span_id is None and self.active_stack:
            parent_span_id = self.active_stack[-1]

        safe_attrs = mask_sensitive_data(attributes or {})
        span = Span(
            trace_id=self.trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            start_time_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            attributes=safe_attrs
        )
        self.spans[span_id] = span
        self.span_start_times[span_id] = time.time()
        self.active_stack.append(span_id)
        return span_id

    def add_event(self, span_id: str, event_name: str, attributes: Optional[Dict[str, Any]] = None):
        """Attaches an instant timeline event to an active span."""
        span = self.spans.get(span_id)
        if span:
            span.events.append(SpanEvent(
                name=event_name,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                attributes=mask_sensitive_data(attributes or {})
            ))

    def end_span(
        self,
        span_id: str,
        status: str = "OK",
        error_message: Optional[str] = None,
        extra_attributes: Optional[Dict[str, Any]] = None
    ) -> Span:
        """Finishes the span and calculates wall-clock latency."""
        span = self.spans.get(span_id)
        if not span:
            raise ValueError(f"Span ID '{span_id}' not found.")

        t_start = self.span_start_times.get(span_id, time.time())
        duration_ms = int((time.time() - t_start) * 1000)

        span.end_time_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        span.duration_ms = duration_ms
        span.status = status
        span.error_message = error_message

        if extra_attributes:
            span.attributes.update(mask_sensitive_data(extra_attributes))

        if self.active_stack and self.active_stack[-1] == span_id:
            self.active_stack.pop()
        elif span_id in self.active_stack:
            self.active_stack.remove(span_id)

        return span

    def get_summary(self) -> Dict[str, Any]:
        """Calculates token totals, cumulative costs, and duration across all spans."""
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_cost_usd = 0.0

        for s in self.spans.values():
            attrs = s.attributes
            try:
                p_tok = int(attrs.get("tokens.prompt", 0) or 0)
            except (ValueError, TypeError):
                p_tok = 0
            try:
                c_tok = int(attrs.get("tokens.completion", 0) or 0)
            except (ValueError, TypeError):
                c_tok = 0
            try:
                t_tok = int(attrs.get("tokens.total", p_tok + c_tok) or 0)
            except (ValueError, TypeError):
                t_tok = p_tok + c_tok
            try:
                cost = float(attrs.get("cost.usd", 0.0) or 0.0)
            except (ValueError, TypeError):
                cost = 0.0

            total_prompt_tokens += p_tok
            total_completion_tokens += c_tok
            total_tokens += t_tok
            total_cost_usd += cost

        root_span = next((s for s in self.spans.values() if s.parent_span_id is None), None)
        total_duration = root_span.duration_ms if root_span else max((s.duration_ms for s in self.spans.values()), default=0)

        return {
            "trace_id": self.trace_id,
            "span_count": len(self.spans),
            "total_duration_ms": total_duration,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "has_errors": any(s.status == "ERROR" for s in self.spans.values())
        }

    def export_opentelemetry_format(self) -> Dict[str, Any]:
        """Exports spans conforming to OpenTelemetry ResourceSpans schema."""
        resource_spans = {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "AgentWindTunnel"}},
                    {"key": "service.version", "value": {"stringValue": "3.0.0"}},
                    {"key": "telemetry.sdk.language", "value": {"stringValue": "python"}}
                ]
            },
            "scopeSpans": [
                {
                    "scope": {"name": "agentwindtunnel.tracer", "version": "3.0.0"},
                    "spans": [
                        {
                            "traceId": span.trace_id,
                            "spanId": span.span_id,
                            "parentSpanId": span.parent_span_id or "",
                            "name": span.name,
                            "kind": span.kind,
                            "startTimeUnixNano": int(time.time() * 1e9),
                            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in span.attributes.items()],
                            "status": {"code": 1 if span.status == "OK" else 2, "message": span.error_message or ""}
                        }
                        for span in self.spans.values()
                    ]
                }
            ]
        }
        return resource_spans
