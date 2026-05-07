from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db_session, make_templates, resolve_view
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

templates = make_templates()

router = APIRouter()

DEFAULT_LIMIT = 20


def _build_stats(db: Session) -> dict:
    return {
        "total": count_rumors(db),
        "by_status": count_by_status(db),
        "published": count_published(db),
        "recent_7d": count_recent(db),
    }


@router.get("/admin", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    view: str = "pending",
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status else None
    canonical_view, is_published = resolve_view(view)

    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        is_published=is_published,
        limit=DEFAULT_LIMIT,
        include_analysis=True,
    )

    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
        is_published=is_published,
    )
    all_tags = list_tags(db)
    stats = _build_stats(db)

    return templates.TemplateResponse(request, "index.html", {
        "rumors": rumors,
        "total": total,
        "has_more": total > DEFAULT_LIMIT,
        "next_offset": DEFAULT_LIMIT,
        "limit": DEFAULT_LIMIT,
        "q": q,
        "status": status,
        "tag": tag,
        "view": canonical_view,
        "tags": all_tags,
        "stats": stats,
    })


@router.get("/admin/rumors/{slug}", response_class=HTMLResponse)
def detail(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None:
        return HTMLResponse("<h1>404 — 未找到</h1>", status_code=404)

    return templates.TemplateResponse(request, "detail.html", {
        "rumor": rumor,
        "analysis": rumor.analysis,
    })
