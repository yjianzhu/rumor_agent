import sys
import os
from sqlalchemy import text

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from src.db.base import Base, engine
# Import models so they are registered with Base
from src.db import models

def init_db():
    print("Initializing database...")
    try:
        # Enable required extensions
        with engine.connect() as connection:
            connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
            connection.execute(text('CREATE EXTENSION IF NOT EXISTS vector;'))
            connection.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_enum e
                        JOIN pg_type t ON t.oid = e.enumtypid
                        WHERE t.typname = 'rumorstatus' AND e.enumlabel = 'outdated'
                    ) THEN
                        ALTER TYPE rumorstatus RENAME VALUE 'outdated' TO 'OUTDATED';
                    END IF;
                END
                $$;
            """))
            connection.commit()
            print("Extension 'uuid-ossp' ensured.")

        # Migrate analysis_results.id from Integer to UUID if needed
        with engine.connect() as connection:
            connection.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'analysis_results'
                          AND column_name = 'id'
                          AND data_type = 'integer'
                    ) THEN
                        ALTER TABLE analysis_results ALTER COLUMN id DROP DEFAULT;
                        ALTER TABLE analysis_results
                            ALTER COLUMN id TYPE UUID USING uuid_generate_v4();
                        ALTER TABLE analysis_results
                            ALTER COLUMN id SET DEFAULT uuid_generate_v4();
                    END IF;
                END
                $$;
            """))
            connection.commit()

        # Migrate source_urls from JSONB to TEXT[] if needed.
        # ALTER COLUMN ... USING doesn't support subqueries, so use a temp-column approach.
        with engine.connect() as connection:
            connection.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'rumors'
                          AND column_name = 'source_urls'
                          AND data_type = 'jsonb'
                    ) THEN
                        ALTER TABLE rumors ADD COLUMN source_urls_tmp TEXT[];
                        UPDATE rumors SET source_urls_tmp =
                            CASE
                                WHEN source_urls IS NULL OR source_urls = 'null'::jsonb
                                    THEN '{}'::text[]
                                ELSE ARRAY(SELECT jsonb_array_elements_text(source_urls))
                            END;
                        ALTER TABLE rumors DROP COLUMN source_urls;
                        ALTER TABLE rumors RENAME COLUMN source_urls_tmp TO source_urls;
                        ALTER TABLE rumors
                            ALTER COLUMN source_urls SET DEFAULT '{}'::text[];
                    END IF;
                END
                $$;
            """))
            connection.commit()

        # Create tables
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully.")

        # Install a DB-level trigger so updated_at is refreshed even for raw SQL
        # updates that bypass the SQLAlchemy ORM layer.
        with engine.connect() as connection:
            connection.execute(text("""
                CREATE OR REPLACE FUNCTION set_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = now();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
            """))
            connection.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'trg_rumors_updated_at'
                    ) THEN
                        CREATE TRIGGER trg_rumors_updated_at
                        BEFORE UPDATE ON rumors
                        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
                    END IF;
                END
                $$;
            """))
            connection.commit()
            print("Trigger 'trg_rumors_updated_at' ensured.")
    except Exception as e:
        print(f"Error initializing database: {e}")

if __name__ == "__main__":
    init_db()
