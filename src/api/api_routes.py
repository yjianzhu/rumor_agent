from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_db_session
from src.db.crud import (
    count_by_status,
    count_published,
    count_recent,
    count_rumors,
    get_rumor_detail_by_slug,
    list_tags,
)
from src.db.schemas import RumorDetailOut, StatsOut

router = APIRouter(prefix="/api")


@router.get("/rumors/{slug}", response_model=RumorDetailOut)
def api_rumor_detail(
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")
    return rumor


@router.get("/stats", response_model=StatsOut)
def api_stats(db: Session = Depends(get_db_session)):
    return StatsOut(
        total=count_rumors(db),
        by_status=count_by_status(db),
        published=count_published(db),
        recent_7d=count_recent(db),
    )


@router.get("/tags", response_model=list[str])
def api_tags(db: Session = Depends(get_db_session)):
    return list_tags(db)
