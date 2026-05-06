from pathlib import Path

from src.db.base import get_db

get_db_session = get_db

TEMPLATES_DIR = Path(__file__).parent / "templates"


# View modes for the rumor listing.
# Maps view name → is_published filter (None = no filter).
VIEW_TO_PUBLISHED: dict[str, bool | None] = {
    "pending": False,
    "published": True,
    "all": None,
}


def resolve_view(view: str) -> tuple[str, bool | None]:
    """Normalize view name and return (canonical_view, is_published filter)."""
    if view not in VIEW_TO_PUBLISHED:
        view = "pending"
    return view, VIEW_TO_PUBLISHED[view]
