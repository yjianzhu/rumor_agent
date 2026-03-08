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
        # Enable uuid-ossp extension for uuid_generate_v4()
        with engine.connect() as connection:
            connection.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
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
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")

if __name__ == "__main__":
    init_db()
