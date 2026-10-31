import json
import uuid
import hashlib
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database.models import EvaluationDataset, EvaluationDatasetItem, utc_now


def _compute_sha256(data: Any) -> str:
    """Computes a deterministic SHA-256 hex digest for serializable data."""
    raw = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_dataset(
    db: Session,
    name: str,
    description: Optional[str] = None,
    version: str = "1.0.0",
    metadata_json: Optional[Dict[str, Any]] = None
) -> EvaluationDataset:
    """Creates a new empty evaluation dataset."""
    existing = db.query(EvaluationDataset).filter(EvaluationDataset.name == name).first()
    if existing:
        raise ValueError(f"Dataset with name '{name}' already exists.")

    dataset = EvaluationDataset(
        id=f"ds_{uuid.uuid4().hex[:10]}",
        name=name,
        description=description,
        version=version,
        item_count=0,
        metadata_json=metadata_json or {},
        created_at=utc_now(),
        updated_at=utc_now()
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def add_dataset_items(
    db: Session,
    dataset_id: str,
    items: List[Dict[str, Any]]
) -> int:
    """Appends items to a dataset and recalculates its SHA-256 integrity checksum."""
    dataset = db.query(EvaluationDataset).filter(EvaluationDataset.id == dataset_id).first()
    if not dataset:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    current_count = dataset.item_count
    for i, item in enumerate(items):
        item_obj = EvaluationDatasetItem(
            id=f"dsitem_{uuid.uuid4().hex[:10]}",
            dataset_id=dataset_id,
            item_index=current_count + i,
            scenario_id=item.get("scenario_id"),
            input_data=item.get("input_data", {}),
            expected_output=item.get("expected_output", {}),
            tags=item.get("tags", []),
            created_at=utc_now()
        )
        db.add(item_obj)

    dataset.item_count = current_count + len(items)
    dataset.updated_at = utc_now()
    db.commit()

    # Recompute checksum across all items
    all_items = (
        db.query(EvaluationDatasetItem)
        .filter(EvaluationDatasetItem.dataset_id == dataset_id)
        .order_by(EvaluationDatasetItem.item_index)
        .all()
    )
    items_repr = [{"input": it.input_data, "expected": it.expected_output} for it in all_items]
    dataset.checksum_sha256 = _compute_sha256(items_repr)
    db.commit()
    db.refresh(dataset)

    return len(items)


def list_datasets(db: Session) -> List[Dict[str, Any]]:
    """Returns all registered datasets with metadata and item counts."""
    datasets = db.query(EvaluationDataset).order_by(desc(EvaluationDataset.updated_at)).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "version": d.version,
            "item_count": d.item_count,
            "checksum_sha256": d.checksum_sha256,
            "metadata": d.metadata_json or {},
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None
        }
        for d in datasets
    ]


def get_dataset(db: Session, dataset_id: str) -> Optional[Dict[str, Any]]:
    """Fetches dataset metadata by ID."""
    d = db.query(EvaluationDataset).filter(EvaluationDataset.id == dataset_id).first()
    if not d:
        return None
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "version": d.version,
        "item_count": d.item_count,
        "checksum_sha256": d.checksum_sha256,
        "metadata": d.metadata_json or {},
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None
    }


def get_dataset_items(
    db: Session,
    dataset_id: str,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Fetches paginated items for a dataset."""
    items = (
        db.query(EvaluationDatasetItem)
        .filter(EvaluationDatasetItem.dataset_id == dataset_id)
        .order_by(EvaluationDatasetItem.item_index)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": it.id,
            "item_index": it.item_index,
            "scenario_id": it.scenario_id,
            "input_data": it.input_data,
            "expected_output": it.expected_output,
            "tags": it.tags or [],
            "created_at": it.created_at.isoformat() if it.created_at else None
        }
        for it in items
    ]


def export_dataset_json(db: Session, dataset_id: str) -> Dict[str, Any]:
    """Exports dataset and all items as a structured JSON object with checksum."""
    dataset = db.query(EvaluationDataset).filter(EvaluationDataset.id == dataset_id).first()
    if not dataset:
        raise ValueError(f"Dataset '{dataset_id}' not found.")

    items = (
        db.query(EvaluationDatasetItem)
        .filter(EvaluationDatasetItem.dataset_id == dataset_id)
        .order_by(EvaluationDatasetItem.item_index)
        .all()
    )
    items_list = [
        {
            "scenario_id": it.scenario_id,
            "input_data": it.input_data,
            "expected_output": it.expected_output,
            "tags": it.tags or []
        }
        for it in items
    ]

    return {
        "name": dataset.name,
        "description": dataset.description,
        "version": dataset.version,
        "item_count": len(items_list),
        "checksum_sha256": dataset.checksum_sha256,
        "metadata": dataset.metadata_json or {},
        "items": items_list
    }


def export_dataset_jsonl(db: Session, dataset_id: str) -> str:
    """Exports dataset items as newline-delimited JSON (JSONL)."""
    data = export_dataset_json(db, dataset_id)
    lines = [json.dumps(it) for it in data["items"]]
    return "\n".join(lines)


def import_dataset_from_json(db: Session, payload: Dict[str, Any]) -> EvaluationDataset:
    """Imports a dataset and items from a JSON payload, validating integrity."""
    name = payload.get("name")
    if not name:
        raise ValueError("Dataset payload missing mandatory 'name' field.")

    items = payload.get("items", [])
    expected_checksum = payload.get("checksum_sha256")

    # If checksum provided, verify integrity before saving
    if expected_checksum:
        items_repr = [{"input": it.get("input_data", {}), "expected": it.get("expected_output", {})} for it in items]
        actual_checksum = _compute_sha256(items_repr)
        if actual_checksum != expected_checksum:
            raise ValueError(f"Checksum mismatch: expected '{expected_checksum}', computed '{actual_checksum}'.")

    # If dataset already exists with this name, append or version
    ds = db.query(EvaluationDataset).filter(EvaluationDataset.name == name).first()
    if not ds:
        ds = create_dataset(
            db=db,
            name=name,
            description=payload.get("description"),
            version=payload.get("version", "1.0.0"),
            metadata_json=payload.get("metadata", {})
        )

    add_dataset_items(db, ds.id, items)
    return ds


def delete_dataset(db: Session, dataset_id: str) -> bool:
    """Deletes a dataset and all associated items."""
    ds = db.query(EvaluationDataset).filter(EvaluationDataset.id == dataset_id).first()
    if not ds:
        return False
    db.delete(ds)
    db.commit()
    return True
