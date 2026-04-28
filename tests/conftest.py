import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.db.base import engine


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


# ─── DB fixture: transaction rollback ────────────────────────────────────────

@pytest.fixture
def db(monkeypatch):
    """Session wrapped in a transaction that rolls back after the test.

    ``SessionLocal`` is monkeypatched so that production code
    (``import_jsonl_file``, ``import_md_file``, etc.) shares the same
    connection / transaction.  No manual cleanup needed.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    factory = lambda: session
    monkeypatch.setattr("src.db.base.SessionLocal", factory)
    monkeypatch.setattr("src.main.SessionLocal", factory)

    # Prevent production code from closing our controlled session
    real_close = session.close
    session.close = lambda: None

    yield session

    session.close = real_close
    transaction.rollback()
    session.close()
    connection.close()
