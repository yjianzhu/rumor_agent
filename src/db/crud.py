from uuid import UUID
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, joinedload

from src.db.models import Rumor, AnalysisResult, RumorStatus
from src.db.schemas import RumorCreate, RumorUpdate, AnalysisResultCreate
from src.config import settings


# ─── Rumor CRUD ───

def create_rumor(db: Session, data: RumorCreate) -> Rumor:
    """Create a new rumor. Raises ValueError if slug already exists."""
    existing = db.execute(select(Rumor).where(Rumor.slug == data.slug)).scalar_one_or_none()
    if existing:
        raise ValueError(f"Rumor with slug '{data.slug}' already exists")

    rumor = Rumor(**data.model_dump(exclude_none=True))
    db.add(rumor)
    db.flush()
    db.refresh(rumor)
    return rumor


def get_rumor_by_id(db: Session, rumor_id: UUID) -> Rumor | None:
    return db.get(Rumor, rumor_id)


def get_rumor_by_slug(db: Session, slug: str) -> Rumor | None:
    return db.execute(select(Rumor).where(Rumor.slug == slug)).scalar_one_or_none()


def list_rumors(
    db: Session,
    *,
    status: RumorStatus | None = None,
    tag: str | None = None,
    q: str | None = None,
    is_published: bool | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Rumor]:
    """List rumors with optional filtering, search, and pagination."""
    stmt = select(Rumor)

    if status is not None:
        stmt = stmt.where(Rumor.status == status)
    if tag is not None:
        stmt = stmt.where(Rumor.tags.any(tag))
    if is_published is not None:
        stmt = stmt.where(Rumor.is_published == is_published)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(
            Rumor.title.ilike(pattern),
            Rumor.summary.ilike(pattern),
            Rumor.rumor_content.ilike(pattern),
        ))

    stmt = stmt.order_by(Rumor.created_at.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def count_rumors(db: Session) -> int:
    return db.execute(select(func.count(Rumor.id))).scalar_one()


def count_rumors_filtered(
    db: Session,
    *,
    status: RumorStatus | None = None,
    tag: str | None = None,
    q: str | None = None,
    is_published: bool | None = None,
) -> int:
    """Count rumors with the same filter logic as list_rumors."""
    stmt = select(func.count(Rumor.id))
    if status is not None:
        stmt = stmt.where(Rumor.status == status)
    if tag is not None:
        stmt = stmt.where(Rumor.tags.any(tag))
    if is_published is not None:
        stmt = stmt.where(Rumor.is_published == is_published)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(
            Rumor.title.ilike(pattern),
            Rumor.summary.ilike(pattern),
            Rumor.rumor_content.ilike(pattern),
        ))
    return db.execute(stmt).scalar_one()


def update_rumor(db: Session, rumor_id: UUID, data: RumorUpdate) -> Rumor | None:
    """Update a rumor's fields. Returns None if not found."""
    rumor = db.get(Rumor, rumor_id)
    if not rumor:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rumor, field, value)

    db.flush()
    db.refresh(rumor)
    return rumor


def delete_rumor(db: Session, rumor_id: UUID) -> bool:
    """Delete a rumor by ID. Returns True if deleted, False if not found."""
    rumor = db.get(Rumor, rumor_id)
    if not rumor:
        return False
    db.delete(rumor)
    db.flush()
    return True


# ─── AnalysisResult CRUD ───

def create_analysis_result(db: Session, data: AnalysisResultCreate) -> AnalysisResult:
    """Create an analysis result. Raises ValueError if one already exists for the rumor."""
    existing = db.execute(
        select(AnalysisResult).where(AnalysisResult.rumor_id == data.rumor_id)
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"Analysis result already exists for rumor {data.rumor_id}")

    result = AnalysisResult(**data.model_dump())
    db.add(result)
    db.flush()
    db.refresh(result)
    return result


def get_analysis_by_rumor_id(db: Session, rumor_id: UUID) -> AnalysisResult | None:
    return db.execute(
        select(AnalysisResult).where(AnalysisResult.rumor_id == rumor_id)
    ).scalar_one_or_none()


# ─── Detail / Stats / Tags ───

def get_rumor_detail_by_slug(db: Session, slug: str) -> Rumor | None:
    """Get a single rumor with its analysis eagerly loaded."""
    stmt = (
        select(Rumor)
        .options(joinedload(Rumor.analysis))
        .where(Rumor.slug == slug)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def count_by_status(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Rumor.status, func.count(Rumor.id)).group_by(Rumor.status)
    ).all()
    return {row[0].value: row[1] for row in rows}


def count_published(db: Session) -> int:
    return db.execute(
        select(func.count(Rumor.id)).where(Rumor.is_published.is_(True))
    ).scalar_one()


def count_recent(db: Session, days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return db.execute(
        select(func.count(Rumor.id)).where(Rumor.created_at >= cutoff)
    ).scalar_one()


def list_tags(db: Session) -> list[str]:
    """Return all distinct tags across all rumors."""
    rows = db.execute(
        select(func.unnest(Rumor.tags)).distinct()
    ).scalars().all()
    return sorted(t for t in rows if t)


# ─── Semantic dedup ───

def find_similar_rumor(
    db: Session,
    embedding: list[float],
    threshold: float = settings.DEDUP_SIMILARITY_THRESHOLD,
) -> Rumor | None:
    distance = Rumor.embedding.cosine_distance(embedding)
    stmt = (
        select(Rumor)
        .where(Rumor.embedding.isnot(None))
        .order_by(distance)
        .limit(1)
    )
    rumor = db.execute(stmt).scalar_one_or_none()
    if rumor is None:
        return None
    cos_dist = db.execute(select(distance).where(Rumor.id == rumor.id)).scalar_one()
    if 1 - cos_dist >= threshold:
        return rumor
    return None
