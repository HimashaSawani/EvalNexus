import os
import json
import re
import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database.models import CustomScenario, utc_now
from backend.scenarios.generic_scenario import (
    GenericScenarioPayload,
    is_generic_scenario
)

CUSTOM_SCENARIOS_DIR = os.path.join("scenarios", "custom")
os.makedirs(CUSTOM_SCENARIOS_DIR, exist_ok=True)


# -------------------------------------------------------------
# Pydantic Schemas for Scenario Definition & Input Validation
# -------------------------------------------------------------

class ScenarioCustomerSchema(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=128)


class ScenarioOrderSchema(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    status: str = Field(default="DELIVERED")
    amount_cents: int = Field(ge=0, le=10000000)
    currency: str = Field(default="USD", max_length=8)
    delivery_date: Optional[str] = None
    delivery_days_ago: Optional[int] = Field(default=None, ge=0, le=3650)


class ScenarioFaultSchema(BaseModel):
    tool_name: str = Field(min_length=1, max_length=64)
    fault_type: str = Field(default="TIMEOUT")  # TIMEOUT, SERVER_ERROR, RATE_LIMIT, LATENCY
    trigger_count: int = Field(default=1, ge=1, le=10)
    delay_sec: Optional[float] = Field(default=0.0, ge=0.0, le=30.0)
    status_code: Optional[int] = Field(default=500, ge=400, le=599)
    error_message: Optional[str] = Field(default=None, max_length=256)


class ScenarioInitialDataSchema(BaseModel):
    customer: ScenarioCustomerSchema
    orders: List[ScenarioOrderSchema] = Field(min_length=1, max_length=20)


class ExpectedChecksSchema(BaseModel):
    ownership: str = Field(default="PASS")      # PASS, FAIL, NOT_APPLICABLE
    eligibility: str = Field(default="PASS")
    duplicate: str = Field(default="PASS")
    state: str = Field(default="PASS")
    completion: str = Field(default="PASS")


class CustomScenarioPayload(BaseModel):
    id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=3, max_length=128)
    category: str = Field(default="CUSTOM", max_length=32)
    description: Optional[str] = Field(default=None, max_length=1000)
    version: int = Field(default=1, ge=1, le=1000)
    fixed_clock: str = Field(default="2026-10-31T12:00:00Z")
    initial_data: ScenarioInitialDataSchema
    customer_messages: List[str] = Field(min_length=1, max_length=20)
    fault_configs: Optional[List[ScenarioFaultSchema]] = Field(default_factory=list)
    expected_checks: ExpectedChecksSchema = Field(default_factory=ExpectedChecksSchema)
    tags: Optional[List[str]] = Field(default_factory=list)

    @field_validator("id")
    def validate_scenario_id(cls, v: str) -> str:
        v = v.strip()
        # Strict security validation: alphanumeric, dash, underscore only. No path traversal!
        if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
            raise ValueError("Scenario ID must contain only letters, numbers, hyphens, and underscores. Path traversal characters are strictly forbidden.")
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("Path traversal sequences are strictly forbidden.")
        return v

    @field_validator("fixed_clock")
    def validate_clock(cls, v: str) -> str:
        try:
            # Normalize ISO datetime
            dt = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            raise ValueError("fixed_clock must be a valid ISO 8601 datetime string (e.g. '2026-10-31T12:00:00Z').")


# -------------------------------------------------------------
# Service Operations: Validation, Storage, Import, Export
# -------------------------------------------------------------

def validate_and_parse_scenario(data: Dict[str, Any]) -> Any:
    """Validates raw scenario dictionary against secure Pydantic model (Generic V2 or Transactional V1)."""
    if not isinstance(data, dict):
        raise ValueError("Scenario data must be a JSON object.")
    # Prevent denial-of-service via huge payloads
    raw_str = json.dumps(data)
    if len(raw_str) > 500_000:
        raise ValueError("Scenario payload exceeds maximum permitted size of 500KB.")
    
    if is_generic_scenario(data):
        return GenericScenarioPayload(**data)
    return CustomScenarioPayload(**data)


def save_custom_scenario(db: Session, payload_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validates, stores in database, and persists to scenarios/custom/{id}.json."""
    validated = validate_and_parse_scenario(payload_data)
    scenario_dict = validated.model_dump()
    scenario_id = validated.id

    if isinstance(validated, CustomScenarioPayload):
        # Calculate concrete delivery dates if delivery_days_ago was given
        clock_dt = datetime.datetime.fromisoformat(validated.fixed_clock)
        for ord_obj in scenario_dict.get("initial_data", {}).get("orders", []):
            if ord_obj.get("delivery_days_ago") is not None and not ord_obj.get("delivery_date"):
                deliv_dt = clock_dt - datetime.timedelta(days=ord_obj["delivery_days_ago"])
                ord_obj["delivery_date"] = deliv_dt.isoformat()
        category = validated.category
        eval_mode = "TRANSACTIONAL"
    else:
        category = getattr(validated, "domain", "GENERIC").upper()
        eval_mode = "GENERIC"
        scenario_dict["evaluation_mode"] = "GENERIC"
        scenario_dict["schema_version"] = "evalnexus-generic-scenario/v2"

    # 1. Save or update DB record
    existing = db.query(CustomScenario).filter(CustomScenario.id == scenario_id).first()
    if existing:
        existing.name = validated.name
        existing.description = validated.description
        existing.category = category
        existing.version = existing.version + 1
        scenario_dict["version"] = existing.version
        existing.scenario_data = scenario_dict
        existing.updated_at = utc_now()
    else:
        new_scen = CustomScenario(
            id=scenario_id,
            name=validated.name,
            description=validated.description,
            category=category,
            version=validated.version,
            scenario_data=scenario_dict
        )
        db.add(new_scen)
    db.commit()

    # 2. Persist to filesystem for compatibility with existing file-based loaders
    fpath = os.path.join(CUSTOM_SCENARIOS_DIR, f"{scenario_id}.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(scenario_dict, f, indent=2)

    return {
        "id": scenario_id,
        "name": validated.name,
        "category": category,
        "version": scenario_dict.get("version", 1),
        "file_path": fpath,
        "status": "SAVED",
        "evaluation_mode": eval_mode
    }


def list_custom_scenarios(db: Session) -> List[Dict[str, Any]]:
    """Returns all custom scenarios from database and filesystem."""
    records = db.query(CustomScenario).order_by(CustomScenario.updated_at.desc()).all()
    results = []
    seen = set()

    for r in records:
        seen.add(r.id)
        scen_data = r.scenario_data or {}
        eval_mode = "GENERIC" if is_generic_scenario(scen_data) else "TRANSACTIONAL"
        results.append({
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "version": r.version,
            "description": r.description,
            "evaluation_mode": eval_mode,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "source": "database",
            "scenario_data": scen_data
        })

    # Also include any files directly in scenarios/custom
    if os.path.exists(CUSTOM_SCENARIOS_DIR):
        for fname in os.listdir(CUSTOM_SCENARIOS_DIR):
            if fname.endswith(".json"):
                sid = fname[:-5]
                if sid not in seen:
                    try:
                        with open(os.path.join(CUSTOM_SCENARIOS_DIR, fname), "r", encoding="utf-8") as f:
                            data = json.load(f)
                        eval_mode = "GENERIC" if is_generic_scenario(data) else "TRANSACTIONAL"
                        results.append({
                            "id": sid,
                            "name": data.get("name", sid),
                            "category": data.get("category", "CUSTOM"),
                            "version": data.get("version", 1),
                            "description": data.get("description"),
                            "evaluation_mode": eval_mode,
                            "source": "filesystem",
                            "scenario_data": data
                        })
                    except Exception:
                        pass
    return results


def get_custom_scenario(db: Session, scenario_id: str) -> Optional[Dict[str, Any]]:
    """Safely retrieves custom scenario by ID."""
    # Check DB
    record = db.query(CustomScenario).filter(CustomScenario.id == scenario_id).first()
    if record and record.scenario_data:
        return record.scenario_data

    # Check filesystem
    fpath = os.path.join(CUSTOM_SCENARIOS_DIR, f"{scenario_id}.json")
    if os.path.isfile(fpath):
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def export_custom_scenario(db: Session, scenario_id: str) -> str:
    """Exports custom scenario as formatted JSON string."""
    data = get_custom_scenario(db, scenario_id)
    if not data:
        raise ValueError(f"Custom scenario '{scenario_id}' not found.")
    return json.dumps(data, indent=2)


def import_custom_scenario(db: Session, json_content: str) -> Dict[str, Any]:
    """Validates raw JSON string and saves scenario."""
    try:
        parsed = json.loads(json_content)
    except Exception as e:
        raise ValueError(f"Invalid JSON string: {str(e)}")
    return save_custom_scenario(db, parsed)


def delete_custom_scenario(db: Session, scenario_id: str) -> bool:
    """Deletes custom scenario from database and filesystem."""
    deleted = False
    record = db.query(CustomScenario).filter(CustomScenario.id == scenario_id).first()
    if record:
        db.delete(record)
        db.commit()
        deleted = True

    fpath = os.path.join(CUSTOM_SCENARIOS_DIR, f"{scenario_id}.json")
    if os.path.isfile(fpath):
        os.remove(fpath)
        deleted = True

    return deleted

