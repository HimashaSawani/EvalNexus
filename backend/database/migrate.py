"""
AgentWindTunnel Database Migration & Initialization Utility
Supports both Alembic-driven migrations and direct schema initialization for SQLite and PostgreSQL.
"""

import os
import sys
from pathlib import Path
from alembic.config import Config
from alembic import command

from backend.database.connection import engine, Base


def run_migrations():
    """Runs Alembic migrations up to head, or initializes schema directly if needed."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    alembic_ini = root_dir / "alembic.ini"

    if alembic_ini.exists():
        try:
            print("Running Alembic migrations to head...")
            alembic_cfg = Config(str(alembic_ini))
            command.upgrade(alembic_cfg, "head")
            print("Alembic migrations completed successfully.")
            return
        except Exception as e:
            print(f"Alembic migration encountered notice: {e}. Ensuring schema tables exist...")

    # Fallback to direct SQLAlchemy table creation
    print("Ensuring all database tables are created via SQLAlchemy metadata...")
    Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")


if __name__ == "__main__":
    run_migrations()
