import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base
from backend.datasets.dataset_service import (
    create_dataset,
    add_dataset_items,
    list_datasets,
    get_dataset,
    get_dataset_items,
    export_dataset_json,
    export_dataset_jsonl,
    import_dataset_from_json,
    delete_dataset
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_and_populate_dataset(db_session):
    ds = create_dataset(
        db=db_session,
        name="Refund Edge Cases v1",
        description="Dataset containing high-value and duplicate refund requests",
        version="1.0.0",
        metadata_json={"domain": "ecommerce"}
    )
    assert ds.id.startswith("ds_")
    assert ds.name == "Refund Edge Cases v1"
    assert ds.item_count == 0

    items = [
        {
            "scenario_id": "scen_high_val",
            "input_data": {"order_id": "ord_100", "amount": 50000},
            "expected_output": {"status": "FLAGGED_FOR_MANUAL_REVIEW"},
            "tags": ["fraud", "high_value"]
        },
        {
            "scenario_id": "scen_dup",
            "input_data": {"order_id": "ord_100", "operation_key": "op_same"},
            "expected_output": {"status": "REJECTED_DUPLICATE"},
            "tags": ["idempotency"]
        }
    ]

    added = add_dataset_items(db_session, ds.id, items)
    assert added == 2

    # Check updated dataset record
    db_session.refresh(ds)
    assert ds.item_count == 2
    assert ds.checksum_sha256 is not None
    assert len(ds.checksum_sha256) == 64

    # List items
    fetched_items = get_dataset_items(db_session, ds.id)
    assert len(fetched_items) == 2
    assert fetched_items[0]["scenario_id"] == "scen_high_val"
    assert "fraud" in fetched_items[0]["tags"]


def test_export_json_and_jsonl(db_session):
    ds = create_dataset(db=db_session, name="Export Test Dataset")
    add_dataset_items(db_session, ds.id, [
        {"input_data": {"q": 1}, "expected_output": {"a": 1}},
        {"input_data": {"q": 2}, "expected_output": {"a": 2}}
    ])

    exported_json = export_dataset_json(db_session, ds.id)
    assert exported_json["name"] == "Export Test Dataset"
    assert exported_json["item_count"] == 2
    assert len(exported_json["items"]) == 2

    exported_jsonl = export_dataset_jsonl(db_session, ds.id)
    lines = exported_jsonl.strip().split("\n")
    assert len(lines) == 2


def test_import_dataset_with_checksum_verification(db_session):
    ds1 = create_dataset(db=db_session, name="Source Dataset")
    add_dataset_items(db_session, ds1.id, [
        {"input_data": {"text": "hello"}, "expected_output": {"reply": "world"}}
    ])
    exported = export_dataset_json(db_session, ds1.id)

    # Import into different dataset name with matching checksum
    exported["name"] = "Imported Clean Dataset"
    imported = import_dataset_from_json(db_session, exported)
    assert imported.name == "Imported Clean Dataset"
    assert imported.item_count == 1

    # Tampered checksum should raise ValueError
    exported["name"] = "Tampered Dataset"
    exported["checksum_sha256"] = "badc0ffee" * 7 + "bad"
    with pytest.raises(ValueError) as exc:
        import_dataset_from_json(db_session, exported)
    assert "Checksum mismatch" in str(exc.value)
