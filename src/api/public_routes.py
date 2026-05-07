from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from src.api.deps import get_db_session, make_templates
from src.api.media_render import split_media
from src.db.crud import (
    count_rumors_filtered,
    get_rumor_detail_by_slug,
    list_rumors,
    list_tags,
)
from src.db.models import RumorStatus

templates = make_templates()

router = APIRouter()

DEFAULT_LIMIT = 12


def _public_tags(db: Session) -> list[str]:
    """Tags currently used by published rumors only."""
    rumors = list_rumors(db, is_published=True, limit=10_000)
    seen: set[str] = set()
    for r in rumors:
        for t in r.tags or []:
            if t:
                seen.add(t)
    return sorted(seen)


@router.get("/", response_class=HTMLResponse)
def public_index(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status in {s.value for s in RumorStatus} else None

    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        is_published=True,
        limit=DEFAULT_LIMIT,
        include_analysis=False,
    )
    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
        is_published=True,
    )

    return templates.TemplateResponse(request, "public_index.html", {
        "rumors": rumors,
        "total": total,
        "has_more": total > DEFAULT_LIMIT,
        "next_offset": DEFAULT_LIMIT,
        "limit": DEFAULT_LIMIT,
        "q": q,
        "status": status,
        "tag": tag,
        "tags": _public_tags(db),
    })


@router.get("/partials/rumors", response_class=HTMLResponse)
def public_rumor_list(
    request: Request,
    q: str = "",
    status: str = "",
    tag: str = "",
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    db: Session = Depends(get_db_session),
):
    status_enum = RumorStatus(status) if status in {s.value for s in RumorStatus} else None

    rumors = list_rumors(
        db,
        status=status_enum,
        tag=tag or None,
        q=q or None,
        is_published=True,
        offset=offset,
        limit=limit,
        include_analysis=False,
    )
    total = count_rumors_filtered(
        db, status=status_enum, tag=tag or None, q=q or None,
        is_published=True,
    )

    return templates.TemplateResponse(request, "public/partials/rumor_list.html", {
        "rumors": rumors,
        "total": total,
        "has_more": offset + limit < total,
        "next_offset": offset + limit,
        "limit": limit,
        "q": q,
        "status": status,
        "tag": tag,
    })


@router.get("/rumors/{slug}", response_class=HTMLResponse)
def public_detail(
    request: Request,
    slug: str,
    db: Session = Depends(get_db_session),
):
    rumor = get_rumor_detail_by_slug(db, slug)
    if rumor is None or not rumor.is_published:
        raise HTTPException(status_code=404, detail="Rumor not found")

    images, videos = split_media(rumor.media_files)
    return templates.TemplateResponse(request, "public_detail.html", {
        "rumor": rumor,
        "analysis": rumor.analysis,
        "images": images,
        "videos": videos,
    })
