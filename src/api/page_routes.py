from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_db_session, TEMPLATES_DIR
from src.db.crud import (
    count_by_status,
    count_published,
    count_recent,
    count_rumors,
    count_rumors_filtered,
    get_rumor_detail_by_slug,
    list_rumors,
    list_tags,
)
from src.db.models import RumorStatus

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

DEFAULT_LIMIT = 20


def _build_stats(db: Session) -> dict:
    return {
        "total": count_rumors(db),
        "by_status": count_by_status(db),
        "published": count_published(db),
        "recent_7d": count_recent(db),
    }


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status else None
    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        limit=DEFAULT_LIMIT,
    )
    # eagerly load analysis for card display
    for r in rumors:
        _ = r.analysis

    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
    )
    all_tags = list_tags(db)
    stats = _build_stats(db)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "rumors": rumors,
        "total": total,
        "has_more": total > DEFAULT_LIMIT,
        "next_offset": DEFAULT_LIMIT,
        "limit": DEFAULT_LIMIT,
        "q": q,
        "status": status,
        "tag": tag,
        "tags": all_tags,
        "stats": stats,
    })


@router.get("/rumors/{slug}", response_class=HTMLResponse)
def detail(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None:
        return HTMLResponse("<h1>404 — 未找到</h1>", status_code=404)

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "rumor": rumor,
        "analysis": rumor.analysis,
    })
