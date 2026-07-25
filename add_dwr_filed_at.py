"""One-time migration: add dwr_filed_at (date the DWR report was marked filed)."""
import os
import tomllib

with open(".streamlit/secrets.toml", "rb") as f:
    os.environ["DATABASE_URL"] = tomllib.load(f)["database_url"]

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS dwr_filed_at TEXT"))
with engine.connect() as conn:
    cols = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'sessions' AND column_name = 'dwr_filed_at'"
    )).scalar()
print("dwr_filed_at column:", "present" if cols else "MISSING")
