from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_session, TEMPLATES_DIR
from src.db.crud import (
    count_by_status,
    count_published,
    count_recent,
    count_rumors,
    count_rumors_filtered,
    list_rumors,
)
from src.db.models import RumorStatus

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/partials")

DEFAULT_LIMIT = 20


@router.get("/rumors", response_class=HTMLResponse)
def rumor_list_partial(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status else None
    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        offset=offset,
        limit=limit,
    )
    for r in rumors:
        _ = r.analysis

    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
    )

    return templates.TemplateResponse("partials/rumor_list.html", {
        "request": request,
        "rumors": rumors,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
        "limit": limit,
        "q": q,
        "status": status,
        "tag": tag,
    })


@router.get("/stats", response_class=HTMLResponse)
def stats_partial(
    request: Request,
    db: Session = Depends(get_db_session),
):
    stats = {
        "total": count_rumors(db),
        "by_status": count_by_status(db),
        "published": count_published(db),
        "recent_7d": count_recent(db),
    }
    return templates.TemplateResponse("partials/stats_bar.html", {
        "request": request,
        "stats": stats,
    })
