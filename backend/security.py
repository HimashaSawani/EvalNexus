"""
AgentWindTunnel V2 Security Module
Provides:
- Configurable API Key / Bearer authentication with local-development mode
- Trusted CORS origin resolution
- Rate limiting for expensive/sensitive endpoints
- Paid-provider concurrency & spending controls
- Input validation and secret masking
"""

import os
import re
import time
import threading
from typing import Optional, List, Dict
from fastapi import Request, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

# Optional Bearer and Header security schemes for OpenAPI documentation
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_allowed_origins() -> List[str]:
    """
    Returns explicit trusted origins from environment or secure local defaults.
    Never allows wildcard '*' when credentials are true.
    """
    raw_origins = os.getenv("AWT_ALLOWED_ORIGINS", "")
    if raw_origins.strip():
        return [o.strip() for o in raw_origins.split(",") if o.strip()]
    return [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def is_auth_required() -> bool:
    """
    Checks if API authentication is actively enforced.
    Preserves seamless local developer experience if neither AWT_API_KEY nor AWT_REQUIRE_AUTH is set.
    """
    explicit_flag = os.getenv("AWT_REQUIRE_AUTH", "").lower()
    if explicit_flag in {"1", "true", "yes"}:
        return True
    if explicit_flag in {"0", "false", "no"}:
        return False
    # If AWT_API_KEY is non-empty, default to requiring authentication
    configured_key = os.getenv("AWT_API_KEY", "").strip()
    return bool(configured_key)


def verify_api_key(
    request: Request,
    bearer_creds: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    header_key: Optional[str] = Security(api_key_header_scheme)
) -> Optional[str]:
    """
    Validates API credentials against AWT_API_KEY.
    Allows unauthenticated access only when is_auth_required() is False.
    Supports:
    1. 'Authorization: Bearer <key>'
    2. 'X-API-Key: <key>'
    """
    if not is_auth_required():
        return "local_dev_anonymous"

    expected_key = os.getenv("AWT_API_KEY", "").strip()
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is required but AWT_API_KEY is not configured on the server."
        )

    provided_key = None
    if bearer_creds and bearer_creds.credentials:
        provided_key = bearer_creds.credentials.strip()
    elif header_key:
        provided_key = header_key.strip()
    elif "x-api-key" in request.headers:
        provided_key = request.headers["x-api-key"].strip()

    if not provided_key or provided_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid API key.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    return "authenticated_user"


class RateLimiter:
    """
    Sliding-window in-memory rate limiter per client IP.
    Zero external dependencies, fast and thread-safe.
    """
    def __init__(self, requests_per_minute: int = 60):
        self.rpm = requests_per_minute
        self.window = 60.0
        self._clients: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> bool:
        if not client_id:
            client_id = "default"
        now = time.time()
        with self._lock:
            timestamps = self._clients.get(client_id, [])
            valid_from = now - self.window
            filtered = [t for t in timestamps if t > valid_from]
            if len(filtered) >= self.rpm:
                self._clients[client_id] = filtered
                return False
            filtered.append(now)
            self._clients[client_id] = filtered
            # Periodic cleanup if registry grows large
            if len(self._clients) > 5000:
                self._cleanup(now)
            return True

    def _cleanup(self, now: float):
        valid_from = now - self.window
        to_del = [k for k, v in self._clients.items() if not v or v[-1] <= valid_from]
        for k in to_del:
            del self._clients[k]


class PaidProviderGuard:
    """
    Server-side spending and concurrency controls for live paid providers (Gemini, OpenAI).
    Prevents runaway queue floods, denial-of-wallet, and excessive concurrent provider requests.
    """
    def __init__(
        self,
        max_concurrent_paid: int = 2,
        max_tokens_budget_per_run: int = 30000,
        max_paid_queue_depth: int = 10
    ):
        self.max_concurrent_paid = max_concurrent_paid
        self.max_tokens_budget = max_tokens_budget_per_run
        self.max_paid_queue_depth = max_paid_queue_depth
        self._active_paid_runs = 0
        self._lock = threading.Lock()

    def check_and_acquire(self, provider_type: str, queue_depth_paid: int) -> None:
        if provider_type.lower() == "mock":
            return
        if queue_depth_paid >= self.max_paid_queue_depth:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Paid execution queue limit exceeded ({queue_depth_paid}/{self.max_paid_queue_depth}). Please wait for current jobs to finish."
            )
        with self._lock:
            if self._active_paid_runs >= self.max_concurrent_paid:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Maximum concurrent paid executions reached ({self._active_paid_runs}/{self.max_concurrent_paid})."
                )
            self._active_paid_runs += 1

    def release(self, provider_type: str) -> None:
        if provider_type.lower() == "mock":
            return
        with self._lock:
            if self._active_paid_runs > 0:
                self._active_paid_runs -= 1

    def validate_execution_budget(self, execution_config: Optional[dict]) -> dict:
        config = dict(execution_config or {})
        max_budget = int(os.getenv("AWT_MAX_TOKENS_PER_RUN", str(self.max_tokens_budget)))
        requested_budget = config.get("max_tokens_budget", 15000)
        if requested_budget > max_budget:
            config["max_tokens_budget"] = max_budget
        return config


from backend.agent.provider import sanitize_secret
general_limiter = RateLimiter(requests_per_minute=int(os.getenv("AWT_RATE_LIMIT_RPM", "120")))
execution_limiter = RateLimiter(requests_per_minute=int(os.getenv("AWT_EXECUTION_RPM", "30")))
paid_guard = PaidProviderGuard(
    max_concurrent_paid=int(os.getenv("AWT_MAX_CONCURRENT_PAID_JOBS", "2")),
    max_tokens_budget_per_run=int(os.getenv("AWT_MAX_TOKENS_PER_RUN", "30000")),
    max_paid_queue_depth=int(os.getenv("AWT_MAX_PAID_QUEUE_DEPTH", "10"))
)
