from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from src.db.models import Rumor, AnalysisResult, RumorStatus
from src.db.schemas import RumorCreate, RumorUpdate, AnalysisResultCreate


# ─── Rumor CRUD ───

def create_rumor(db: Session, data: RumorCreate) -> Rumor:
    """Create a new rumor. Raises ValueError if slug already exists."""
    existing = db.execute(select(Rumor).where(Rumor.slug == data.slug)).scalar_one_or_none()
    if existing:
        raise ValueError(f"Rumor with slug '{data.slug}' already exists")

    rumor = Rumor(**data.model_dump(exclude_none=True))
    db.add(rumor)
    db.commit()
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
    is_published: bool | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Rumor]:
    """List rumors with optional filtering and pagination."""
    stmt = select(Rumor)

    if status is not None:
        stmt = stmt.where(Rumor.status == status)
    if tag is not None:
        stmt = stmt.where(Rumor.tags.any(tag))
    if is_published is not None:
        stmt = stmt.where(Rumor.is_published == is_published)

    stmt = stmt.order_by(Rumor.created_at.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def count_rumors(db: Session) -> int:
    return db.execute(select(func.count(Rumor.id))).scalar_one()


def update_rumor(db: Session, rumor_id: UUID, data: RumorUpdate) -> Rumor | None:
    """Update a rumor's fields. Returns None if not found."""
    rumor = db.get(Rumor, rumor_id)
    if not rumor:
        return None

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rumor, field, value)

    db.commit()
    db.refresh(rumor)
    return rumor


def delete_rumor(db: Session, rumor_id: UUID) -> bool:
    """Delete a rumor by ID. Returns True if deleted, False if not found."""
    rumor = db.get(Rumor, rumor_id)
    if not rumor:
        return False
    db.delete(rumor)
    db.commit()
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
    db.commit()
    db.refresh(result)
    return result


def get_analysis_by_rumor_id(db: Session, rumor_id: UUID) -> AnalysisResult | None:
    return db.execute(
        select(AnalysisResult).where(AnalysisResult.rumor_id == rumor_id)
    ).scalar_one_or_none()
