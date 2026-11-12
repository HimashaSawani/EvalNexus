import re
import json
import datetime
from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# -------------------------------------------------------------
# Generic Scenario Assertion Schema (Version 2)
# -------------------------------------------------------------

AssertionTypeLiteral = Literal[
    "json_schema",
    "json_path_equals",
    "tool_called",
    "tool_not_called",
    "execution_completed"
]


class GenericAssertion(BaseModel):
    id: Optional[str] = None
    type: AssertionTypeLiteral
    name: Optional[str] = None
    description: Optional[str] = None
    # For json_schema
    schema_def: Optional[Dict[str, Any]] = None
    # For json_path_equals
    path: Optional[str] = None
    expected: Optional[Any] = None
    # For tool_called / tool_not_called
    tool: Optional[str] = None
    argument_matches: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def validate_assertion_fields(self):
        if self.type == "json_schema" and not self.schema_def:
            raise ValueError("Assertion type 'json_schema' requires 'schema_def' field.")
        if self.type == "json_path_equals":
            if not self.path:
                raise ValueError("Assertion type 'json_path_equals' requires 'path' field.")
            if self.expected is None:
                raise ValueError("Assertion type 'json_path_equals' requires 'expected' field.")
        if self.type in ["tool_called", "tool_not_called"] and not self.tool:
            raise ValueError(f"Assertion type '{self.type}' requires 'tool' field.")
        return self


# -------------------------------------------------------------
# Generic Tool Contract Schema
# -------------------------------------------------------------

class GenericToolContract(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=512)
    parameters: Dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    handler_type: str = Field(default="synthetic_stub", max_length=64)


# -------------------------------------------------------------
# Generic Execution Limits
# -------------------------------------------------------------

class GenericExecutionLimits(BaseModel):
    max_turns: int = Field(default=4, ge=1, le=10)
    max_tool_calls: int = Field(default=6, ge=0, le=20)
    max_tokens_budget: int = Field(default=5000, ge=100, le=50000)
    scenario_timeout_sec: float = Field(default=20.0, ge=1.0, le=120.0)


# -------------------------------------------------------------
# Generic Scenario V2 Model
# -------------------------------------------------------------

class GenericScenarioPayload(BaseModel):
    schema_version: Literal["evalnexus-generic-scenario/v2"] = "evalnexus-generic-scenario/v2"
    id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=3, max_length=128)
    domain: str = Field(default="general", min_length=2, max_length=64)
    evaluation_mode: Literal["GENERIC"] = "GENERIC"
    description: Optional[str] = Field(default=None, max_length=1000)
    version: int = Field(default=1, ge=1, le=1000)
    
    # Input payload provided to the agent
    input: Dict[str, Any]
    customer_messages: Optional[List[str]] = None
    
    # Tool contracts allowed / expected in this scenario
    tool_contracts: List[GenericToolContract] = Field(default_factory=list)
    
    # Declarative assertions to evaluate
    assertions: List[GenericAssertion] = Field(min_length=1, max_length=30)
    
    # Execution constraints
    execution_limits: GenericExecutionLimits = Field(default_factory=GenericExecutionLimits)
    tags: Optional[List[str]] = Field(default_factory=list)

    @field_validator("id")
    def validate_scenario_id(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
            raise ValueError("Scenario ID must contain only alphanumeric characters, dashes, and underscores.")
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("Path traversal sequences are strictly forbidden.")
        return v

    @model_validator(mode="after")
    def populate_messages_if_missing(self):
        if not self.customer_messages or len(self.customer_messages) == 0:
            if "prompt" in self.input:
                self.customer_messages = [str(self.input["prompt"])]
            elif "text" in self.input:
                self.customer_messages = [str(self.input["text"])]
            elif "message" in self.input:
                self.customer_messages = [str(self.input["message"])]
            else:
                self.customer_messages = [json.dumps(self.input)]
        return self


def is_generic_scenario(scenario_data: Dict[str, Any]) -> bool:
    """Detects whether a scenario dictionary conforms to Generic V2 contract."""
    if not isinstance(scenario_data, dict):
        return False
    return (
        scenario_data.get("schema_version") == "evalnexus-generic-scenario/v2"
        or scenario_data.get("evaluation_mode") == "GENERIC"
    )

