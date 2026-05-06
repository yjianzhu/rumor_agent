from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_session, TEMPLATES_DIR, resolve_view
from src.db.crud import (
    count_by_status,
    count_published,
    count_recent,
    count_rumors,
    count_rumors_filtered,
    get_rumor_by_slug,
    get_rumor_detail_by_slug,
    list_rumors,
    update_rumor,
)
from src.db.models import RumorStatus
from src.db.schemas import RumorUpdate

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/partials")

DEFAULT_LIMIT = 20


@router.get("/rumors", response_class=HTMLResponse)
def rumor_list_partial(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    view: str = "pending",
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
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
        offset=offset,
        limit=limit,
        include_analysis=True,
    )

    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
        is_published=is_published,
    )

    return templates.TemplateResponse(request, "partials/rumor_list.html", {
        "rumors": rumors,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
        "limit": limit,
        "q": q,
        "status": status,
        "tag": tag,
        "view": canonical_view,
    })


@router.get("/rumors/{slug}", response_class=HTMLResponse)
def rumor_detail_partial(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")
    return templates.TemplateResponse(request, "partials/rumor_detail.html", {
        "rumor": rumor,
    })


@router.post("/rumors/{slug}/review", response_class=HTMLResponse)
def rumor_review_partial(
    request: Request,
    slug: str,
    status: RumorStatus = Form(...),
    truth_content: str = Form(""),
    is_published: bool = Form(False),
    db: Session = Depends(get_db_session),
):
    """Form-friendly review submission. Updates the rumor and returns the refreshed article partial."""
    rumor = get_rumor_by_slug(db, slug)
    if rumor is None:
        raise HTTPException(status_code=404, detail="Rumor not found")

    update_rumor(db, rumor.id, RumorUpdate(
        status=status,
        truth_content=truth_content or None,
        is_published=is_published,
    ))

    refreshed = get_rumor_detail_by_slug(db, slug)
    return templates.TemplateResponse(request, "partials/rumor_detail.html", {
        "rumor": refreshed,
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
    return templates.TemplateResponse(request, "partials/stats_bar.html", {
        "stats": stats,
    })
