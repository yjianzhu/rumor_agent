import json
from pathlib import Path

import pytest

from src.db.base import SessionLocal
from src.db.crud import delete_rumor, get_analysis_by_rumor_id, get_rumor_by_slug


# ─── Shared helpers ──────────────────────────────────────────────────────────

def write_jsonl(tmp_path: Path, rows: list, filename: str = "test.jsonl") -> Path:
    path = tmp_path / filename
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            if isinstance(row, str):
                f.write(row + "\n")
            else:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def write_md(tmp_path: Path, content: str, filename: str = "test.md") -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


class FakeAnalyzer:
    def __init__(self, responses):
        self.responses = iter(responses)

    def analyze(self, sample):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


# ─── Shared fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def created_slugs(db):
    slugs: list[str] = []
    yield slugs
    for slug in slugs:
        rumor = get_rumor_by_slug(db, slug)
        if rumor:
            analysis = get_analysis_by_rumor_id(db, rumor.id)
            if analysis:
                db.delete(analysis)
            delete_rumor(db, rumor.id)
    db.commit()
