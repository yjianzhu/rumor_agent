"""Database initialization.

Run once on a fresh database (or after `DROP DATABASE` during dev):

    uv run python init_db.py

Creates all ORM tables and ensures the ``updated_at`` trigger is in place.

**Prerequisites** (run once by a superuser, since rad_user cannot CREATE EXTENSION):

    psql -U postgres -d rumor_agent_db -c \\
        "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"; CREATE EXTENSION IF NOT EXISTS vector;"

Schema changes during current dev phase are handled by drop & recreate.
"""

import sys
from pathlib import Path
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parent))

from src.db.base import Base, engine
from src.db import models  # noqa: F401  — register models with Base


REQUIRED_EXTENSIONS = ("uuid-ossp", "vector")


def init_db():
    print("Initializing database...")

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = ANY(:names)"),
            {"names": list(REQUIRED_EXTENSIONS)},
        ).all()
        installed = {row[0] for row in rows}
    missing = [ext for ext in REQUIRED_EXTENSIONS if ext not in installed]
    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL extension(s): {missing}. Run as superuser:\n"
            f'  psql -U postgres -d <db> -c "CREATE EXTENSION IF NOT EXISTS \\"uuid-ossp\\"; '
            f'CREATE EXTENSION IF NOT EXISTS vector;"'
        )
    print(f"Extensions verified: {', '.join(REQUIRED_EXTENSIONS)}.")

    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    with engine.begin() as conn:
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = now();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_rumors_updated_at'
                ) THEN
                    CREATE TRIGGER trg_rumors_updated_at
                    BEFORE UPDATE ON rumors
                    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
                END IF;
            END
            $$;
        """))
    print("Trigger trg_rumors_updated_at ensured.")


if __name__ == "__main__":
    init_db()
