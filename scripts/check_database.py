import sys
import os
from sqlalchemy import text

# Ensure src is in python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.db.base import engine
from src.config import settings

def check_database():
    print(f"Checking database: {settings.DB_NAME} on {settings.DB_HOST}:{settings.DB_PORT}")
    print(f"User: {settings.DB_USER}")
    
    try:
        with engine.connect() as connection:
            # Check connection
            result = connection.execute(text("SELECT version();"))
            version = result.fetchone()
            print(f"\nPostgreSQL Version: {version[0]}")
            
            # List tables
            result = connection.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """))
            tables = [row[0] for row in result]
            print(f"\nTables in 'public' schema: {tables}")
            
            # Check row counts if tables exist
            for table in tables:
                result = connection.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.fetchone()[0]
                print(f" - Table '{table}': {count} rows")
                
    except Exception as e:
        print(f"\nError connecting to database: {e}")

if __name__ == "__main__":
    check_database()
