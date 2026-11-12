"""Keep API-import and worker-constructor side effects out of the user database."""
import os
import tempfile
from pathlib import Path
import pytest

_test_directory = Path(tempfile.mkdtemp(prefix="awt-pytest-"))
os.environ["DATABASE_URL"] = "sqlite:///" + str(_test_directory / "suite.db").replace("\\", "/")
os.environ["AWT_EMBEDDED_WORKER"] = "0"

@pytest.fixture
def db_session():
    from backend.database.connection import SessionLocal, Base, engine
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

