"""Backfill embeddings for existing rumors that have embedding IS NULL."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from src.config import settings
from src.db.base import SessionLocal
from src.db.models import Rumor
from src.embedding import get_embedding
from src.logger import configure_logging, get_logger

logger = get_logger(__name__)

BATCH_SIZE = settings.IMPORT_BATCH_SIZE


def backfill():
    configure_logging()
    db = SessionLocal()
    try:
        stmt = select(Rumor).where(Rumor.embedding.is_(None))
        rumors = list(db.execute(stmt).scalars().all())
        total = len(rumors)
        logger.info("Found %d rumors without embeddings", total)

        done = 0
        for rumor in rumors:
            text = f"{rumor.title}\n{rumor.rumor_content or ''}"
            try:
                rumor.embedding = get_embedding(text)
                done += 1
                if done % BATCH_SIZE == 0:
                    db.commit()
                    logger.info("Progress: %d / %d", done, total)
            except Exception as exc:
                logger.error("Failed to embed rumor %s: %s", rumor.id, exc)

        db.commit()
        logger.info("Backfill complete: %d / %d succeeded", done, total)
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
