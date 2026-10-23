import sqlite3
import os

db_path = "agent_wind_tunnel.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(runs)")
    existing_cols = [row[1] for row in cursor.fetchall()]

    new_cols = {
        "provider_type": "VARCHAR(32) DEFAULT 'mock'",
        "model_name": "VARCHAR(64) DEFAULT 'mock-deterministic-v1'",
        "is_mock": "INTEGER DEFAULT 1",
        "execution_config": "JSON"
    }

    for col, col_def in new_cols.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_def}")
            print(f"Added column {col} to runs table.")

    conn.commit()
    conn.close()
    print("Database migration finished successfully.")
else:
    print("Database file does not exist yet. It will be initialized on first run.")
