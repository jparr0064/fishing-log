"""Enable Row-Level Security on all app tables.

The app connects directly as the table owner (postgres role), which bypasses
RLS - so the app keeps working exactly as before. What this changes: the
Supabase auto-generated public REST API can no longer read or write these
tables, closing the vulnerability flagged in Supabase's security email.
"""
import os
import tomllib

with open(".streamlit/secrets.toml", "rb") as f:
    secrets = tomllib.load(f)
os.environ["DATABASE_URL"] = secrets["database_url"]

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT tablename, rowsecurity
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)).mappings().all()

print("Current state:")
for r in rows:
    status = "RLS ENABLED" if r["rowsecurity"] else "RLS OFF  <-- exposed"
    print(f"  {r['tablename']:<12} {status}")

tables = [r["tablename"] for r in rows if not r["rowsecurity"]]
if not tables:
    print("\nAll tables already secured. Nothing to do.")
else:
    print(f"\nEnabling RLS on: {', '.join(tables)}")
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY'))

    # verify
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT tablename, rowsecurity
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)).mappings().all()
    print("\nAfter fix:")
    for r in rows:
        status = "RLS ENABLED" if r["rowsecurity"] else "STILL OFF - PROBLEM"
        print(f"  {r['tablename']:<12} {status}")

    # sanity check: app queries still work through the direct connection
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM sessions")).scalar()
    print(f"\nSanity check - direct connection still reads sessions table: {n} rows. OK.")
