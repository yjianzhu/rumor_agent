from pathlib import Path

from src.db.base import get_db

get_db_session = get_db

TEMPLATES_DIR = Path(__file__).parent / "templates"
