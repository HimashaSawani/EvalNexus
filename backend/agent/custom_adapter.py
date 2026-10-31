import time
import json
import re
import os
import ipaddress
import urllib.parse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
import httpx

from backend.agent.provider import BaseLLMProvider, LLMResponse, sanitize_secret


# -------------------------------------------------------------
# SSRF Protection & Safe Endpoint Validation
# -------------------------------------------------------------

BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.gcp.internal",
    "instance-data",
}

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / AWS / GCP / Azure metadata
    ipaddress.ip_network("fe80::/10"),          # IPv6 Link-local
    ipaddress.ip_network("0.0.0.0/8"),          # Current network
]


def validate_safe_endpoint(url: str) -> str:
    """
    Validates endpoint URL against SSRF vulnerabilities, cloud metadata services,
    and forbidden network protocols.
    """
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("Endpoint URL must use HTTP or HTTPS protocol.")

    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Invalid endpoint URL: hostname missing.")

    if hostname in BLOCKED_HOSTNAMES:
        raise ValueError(f"SSRF Protection: Access to cloud metadata service '{hostname}' is strictly blocked.")

    # Check for direct IP or resolved IP
    try:
        ip_obj = ipaddress.ip_address(hostname)
        for net in BLOCKED_IP_NETWORKS:
            if ip_obj in net:
                raise ValueError(f"SSRF Protection: Access to reserved/link-local address '{hostname}' is strictly blocked.")

        # If strict internal network blocking is enabled (production mode)
        block_internal = os.getenv("AWT_BLOCK_INTERNAL_NETWORKS", "0").lower() in {"1", "true", "yes"}
        if block_internal and (ip_obj.is_private or ip_obj.is_loopback):
            raise ValueError(f"SSRF Protection: Access to private/loopback network address '{hostname}' is blocked in production mode.")
    except ValueError as ve:
        if "SSRF Protection" in str(ve):
            raise
        # Hostname string (e.g. localhost or external domain)
        block_internal = os.getenv("AWT_BLOCK_INTERNAL_NETWORKS", "0").lower() in {"1", "true", "yes"}
        if block_internal and hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("SSRF Protection: Localhost access is blocked when AWT_BLOCK_INTERNAL_NETWORKS is enabled.")

    return url


# -------------------------------------------------------------
# Request & Response Pydantic Schemas for External Agents
# -------------------------------------------------------------

class CustomAgentToolSpec(BaseModel):
    type: str = "function"
    function: Dict[str, Any]


class CustomAgentMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class CustomAgentRequestPayload(BaseModel):
    messages: List[CustomAgentMessage]
    tools: List[CustomAgentToolSpec] = Field(default_factory=list)
    temperature: float = 0.0
    timeout_sec: Optional[float] = 15.0
    scenario_context: Optional[Dict[str, Any]] = None


class CustomAgentToolCallFunction(BaseModel):
    name: str
    arguments: Any  # Can be JSON string or dict

    @field_validator("arguments", mode="before")
    def serialize_arguments(cls, v):
        if isinstance(v, dict):
            return json.dumps(v)
        if isinstance(v, str):
            return v
        return json.dumps(v or {})


class CustomAgentToolCall(BaseModel):
    id: Optional[str] = None
    type: str = "function"
    function: CustomAgentToolCallFunction


class CustomAgentResponsePayload(BaseModel):
    content: Optional[str] = None
    tool_calls: Optional[List[CustomAgentToolCall]] = Field(default_factory=list)
    prompt_tokens: Optional[int] = 120
    completion_tokens: Optional[int] = 35
    metadata: Optional[Dict[str, Any]] = None


class CustomAgentRegistration(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=2, max_length=128)
    description: Optional[str] = None
    endpoint_url: str = Field(min_length=8, max_length=512)
    auth_header_name: str = Field(default="Authorization", max_length=64)
    auth_token: Optional[str] = None
    timeout_sec: float = Field(default=15.0, ge=1.0, le=60.0)

    @field_validator("endpoint_url")
    def validate_url(cls, v: str) -> str:
        return validate_safe_endpoint(v)


# -------------------------------------------------------------
# HTTP Agent Adapter Provider
# -------------------------------------------------------------

class CustomHTTPAgentProvider(BaseLLMProvider):
    """
    Evaluates developer-owned AI agents over validated HTTP APIs without
    executing arbitrary code. Validates request and response schemas strictly.
    """
    provider_type: str = "custom_http"

    def __init__(
        self,
        endpoint_url: str,
        name: str = "custom-agent",
        auth_header_name: str = "Authorization",
        auth_token: Optional[str] = None,
        timeout_sec: float = 15.0,
        model_name: Optional[str] = None
    ):
        self.endpoint_url = validate_safe_endpoint(endpoint_url)
        self.name = name
        self.auth_header_name = auth_header_name.strip()
        self.auth_token = auth_token.strip() if auth_token else None
        self.timeout_sec = max(1.0, min(float(timeout_sec), 60.0))
        self.model_name = model_name or f"custom-{self.name}"

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AgentWindTunnel/2.0-Adapter"
        }
        if self.auth_token:
            # Handle Bearer prefix if header is Authorization and user omitted Bearer
            if self.auth_header_name.lower() == "authorization" and not self.auth_token.lower().startswith("bearer "):
                headers[self.auth_header_name] = f"Bearer {self.auth_token}"
            else:
                headers[self.auth_header_name] = self.auth_token
        return headers

    def ping(self) -> Dict[str, Any]:
        """
        Sends a lightweight preflight probe to verify endpoint reachability and latency.
        """
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "tools": [],
            "temperature": 0.0,
            "probe": True
        }
        t0 = time.time()
        try:
            validate_safe_endpoint(self.endpoint_url)
            with httpx.Client(timeout=min(self.timeout_sec, 5.0), follow_redirects=False) as client:
                res = client.post(self.endpoint_url, json=payload, headers=self._build_headers())
                elapsed_ms = int((time.time() - t0) * 1000)
                return {
                    "status": "ONLINE" if res.status_code == 200 else f"HTTP_{res.status_code}",
                    "status_code": res.status_code,
                    "latency_ms": elapsed_ms,
                    "endpoint_url": self.endpoint_url,
                    "response_preview": res.text[:200]
                }
        except httpx.TimeoutException:
            return {
                "status": "TIMEOUT",
                "latency_ms": int((time.time() - t0) * 1000),
                "error": f"Endpoint timed out after {min(self.timeout_sec, 5.0)}s",
                "endpoint_url": self.endpoint_url
            }
        except Exception as e:
            sanitized = sanitize_secret(str(e), self.auth_token or "")
            return {
                "status": "UNREACHABLE",
                "latency_ms": int((time.time() - t0) * 1000),
                "error": sanitized,
                "endpoint_url": self.endpoint_url
            }

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
        timeout: Optional[float] = None
    ) -> LLMResponse:
        effective_timeout = float(timeout) if timeout else self.timeout_sec

        # Construct and validate outgoing payload
        req_payload = {
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "timeout_sec": effective_timeout
        }
        validated_req = CustomAgentRequestPayload(**req_payload)

        headers = self._build_headers()
        t0 = time.time()
        try:
            validate_safe_endpoint(self.endpoint_url)
            with httpx.Client(timeout=effective_timeout, follow_redirects=False) as client:
                resp = client.post(
                    self.endpoint_url,
                    json=validated_req.model_dump(),
                    headers=headers
                )
        except httpx.TimeoutException:
            raise RuntimeError(
                f"Custom agent '{self.name}' timed out after {effective_timeout:.1f}s at endpoint {self.endpoint_url}"
            )
        except Exception as e:
            sanitized = sanitize_secret(str(e), self.auth_token or "")
            raise RuntimeError(f"Custom agent HTTP transport error: {sanitized}")

        if resp.status_code != 200:
            error_body = sanitize_secret(resp.text[:300], self.auth_token or "")
            raise RuntimeError(
                f"Custom agent HTTP endpoint returned status {resp.status_code}: {error_body}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Custom agent returned invalid JSON response: {str(e)}")

        try:
            validated_resp = CustomAgentResponsePayload(**data)
        except Exception as e:
            raise RuntimeError(f"Custom agent response schema validation failed: {str(e)}")

        # Convert tool calls to internal dict representation
        tool_calls_out = []
        for i, tc in enumerate(validated_resp.tool_calls or []):
            tc_id = tc.id or f"custom_tc_{int(time.time()*1000)}_{i}"
            tool_calls_out.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })

        return LLMResponse(
            content=validated_resp.content,
            tool_calls=tool_calls_out,
            prompt_tokens=validated_resp.prompt_tokens or 100,
            completion_tokens=validated_resp.completion_tokens or 30
        )

